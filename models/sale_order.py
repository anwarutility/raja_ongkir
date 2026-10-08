from odoo import fields, models, api
from odoo.exceptions import UserError
import json
import requests
import math

from .ongkir_utils import is_komerce, komerce_route, ongkir_url


def _cost_value(value):
    """Numeric cost out of an API answer, tolerating strings and nulls."""
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def pick_service(results, wanted_service=None):
    """Choose one rate row from a provider answer.

    The service configured on the API record (``api.list.service``, default
    ``REG``) is matched first. Providers name services differently -- Biteship
    answers ``"Reguler"`` where RajaOngkir answers ``"REG"`` -- so an exact
    match is tried before a prefix match ("REG" is a prefix of "REGULER").
    Without that, configuring REG silently fell through to the cheapest service
    and a quotation was priced with JNE Trucking instead of JNE Reguler.

    Providers also do not return the configured service on every route --
    Komerce answers ``CTC`` (JNE City Courier) for some destinations -- and
    failing with "No service returned" left the Sales Order without any cost.
    In that case the cheapest available service is used, so the button always
    fills a usable rate instead of raising.
    """
    wanted = (wanted_service or 'REG').strip().upper()
    for result in results:
        if (result.get('service') or '').strip().upper() == wanted:
            return result
    if wanted:
        for result in results:
            service = (result.get('service') or '').strip().upper()
            if service and (service.startswith(wanted) or wanted.startswith(service)):
                return result
    if not results:
        return None
    return min(
        results,
        key=lambda row: _cost_value(row.get('cost') or row.get('value')),
    )


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.depends('order_line.weight_subtotal')
    def _calctotalweight(self):
        for rec in self:
            totalweight = 0
            for order_line in rec.order_line:
                totalweight += order_line.weight_subtotal
            rec.weight_total = math.ceil(totalweight)

    @api.depends('raja_ongkir_api')
    def _get_raja_ongkir_api(self):
        for rec in self:
            if rec.raja_ongkir_api:
                rec.origin_city_type = rec.raja_ongkir_api.origin_city_type_default
                rec.destination_city_type = rec.raja_ongkir_api.destination_city_type_default
                rec.origin_courier = rec.raja_ongkir_api.origin_courier

    @api.onchange('partner_id')
    def onchange_partner_id(self):
        for rec in self:
            if rec.partner_id:
                rec.city_id = rec.partner_id.city_id
                rec.subdistrict_id = rec.partner_id.subdistrict_id

    @api.onchange('raja_ongkir_api')
    def _onchange_raja_ongkir_api(self):
        """Auto-default `origin_courier` to 'jne' when an API is selected."""
        for rec in self:
            if rec.raja_ongkir_api and not rec.origin_courier:
                rec.origin_courier = 'jne'

    def _default_raja_ongkir_api(self):
        """Return the first enabled API, so every new Sales Order has an API set by default."""
        return self.env['api.list'].search([('status', '=', 'enable')], limit=1)

    raja_ongkir_api = fields.Many2one(comodel_name='api.list', string='Biteship Api', ondelete='cascade', default=_default_raja_ongkir_api)
    origin_city_type = fields.Char(compute='_get_raja_ongkir_api', string='Origin City Type', store=True)
    destination_city_type = fields.Char(compute='_get_raja_ongkir_api', string='Destination City Type', store=True)
    origin_courier = fields.Char(compute='_get_raja_ongkir_api', string='Origin Courier', store=True)
    city_id = fields.Many2one(comodel_name='res.country.city', string='Destination City', ondelete='cascade')
    subdistrict_id = fields.Many2one(comodel_name='res.city.subdistrict', string='Destination Subdistrict', ondelete='cascade')
    weight_total = fields.Float(compute='_calctotalweight', string='Total Gross Weight')
    courier_name = fields.Char(string='Courier Name')
    service_name = fields.Char(string='Service Name')
    cost_delivery = fields.Monetary(string='Cost Delivery')
    etd = fields.Char(string='ETD')

    @api.onchange('city_id')
    def _city_id_onchange(self):
        res = {}
        res['domain'] = {'subdistrict_id': [('city_id', '=', self.city_id.city_id)]}
        return res

    def _is_komerce(self, api):
        """Komerce (rajaongkir.komerce.id) exposes a different API layout and
        response format than the classic RajaOngkir (/api/cost)."""
        return is_komerce(api.api_url)

    def _ongkir_url(self, api, path):
        """Build the endpoint URL, tolerating both the default RajaOngkir
        layout (``https://pro.rajaongkir.com/api``) and full bases such as
        ``https://rajaongkir.komerce.id/api/v1``."""
        return ongkir_url(api.api_url, path)

    def _ongkir_area(self, record, city_type):
        """Describe one end of the route as an area dict.

        Shape expected by ``stock.picking._fetch_ongkir_services``:
        ``{'type', 'city_id', 'subdistrict_id', 'city_record',
        'subdistrict_record'}``. Biteship needs the master records to resolve
        its own ``area_id``, Komerce needs the ids.
        """
        if city_type == 'subdistrict' and record:
            return {
                'type': 'subdistrict',
                'city_id': record.city_rel.city_id,
                'subdistrict_id': record.subdistrict_id,
                'city_record': record.city_rel,
                'subdistrict_record': record,
            }
        return {
            'type': 'city',
            'city_id': record.city_id if record else None,
            'subdistrict_id': None,
            'city_record': record,
            'subdistrict_record': None,
        }

    def _fetch_services(self, api, courier, origin_area, destination_area, weight):
        """Delegate the provider call to ``stock.picking``.

        The picking holds the multi-provider implementation (Biteship /
        Komerce / classic RajaOngkir); reusing it keeps the Sales Order and
        Delivery Order buttons on one code path instead of two that drift.
        """
        picking = self.env['stock.picking']
        return picking._fetch_ongkir_services(
            api, courier, origin_area, destination_area, weight)

    def compute_ongkir(self):
        if not self.raja_ongkir_api:
            raise UserError('Please charge the API or activate the API.')

        api = self.raja_ongkir_api
        weight = self.weight_total * 1000
        # Default courier = JNE. Falls back to 'jne' when the API config has no
        # courier set, so every Sales Order uses JNE unless changed explicitly.
        courier = self.origin_courier or 'jne'

        if self.origin_city_type == 'city':
            if not api.origin_city_id:
                raise UserError('Please Set Origin City.')
            origin = api.origin_city_id.city_id
        elif self.origin_city_type == 'subdistrict':
            if not api.origin_subdistrict_id:
                raise UserError('Please Set Origin Subdistrict.')
            origin = api.origin_subdistrict_id.subdistrict_id
        else:
            raise UserError('Origin city type not configured on API.')

        if self.destination_city_type == 'city':
            if not self.city_id:
                raise UserError('Please Set Destination City.')
            destination = self.city_id.city_id
        elif self.destination_city_type == 'subdistrict':
            if not self.subdistrict_id:
                raise UserError('Please Set Destination Subdistrict.')
            destination = self.subdistrict_id.subdistrict_id
        else:
            raise UserError('Destination city type not configured on API.')

        # Area descriptions for the provider call: Komerce needs ids that
        # follow the area type (city vs kecamatan live in different id spaces),
        # while Biteship needs the master records to resolve its own area_id.
        origin_area = self._ongkir_area(
            api.origin_subdistrict_id if self.origin_city_type == 'subdistrict'
            else api.origin_city_id,
            self.origin_city_type)
        destination_area = self._ongkir_area(
            self.subdistrict_id if self.destination_city_type == 'subdistrict'
            else self.city_id,
            self.destination_city_type)

        try:
            # Biteship prices by its own area_id and returns every service of
            # the requested couriers in one call. The RajaOngkir/Komerce
            # layouts are still supported: they are picked from `api.api_url`.
            services = self._fetch_services(
                api, courier, origin_area, destination_area, weight)
            chosen = pick_service(services, api.service)
            compute_service_cost = {}
            if chosen:
                compute_service_cost = {
                    'code': chosen.get('code'),
                    'name': chosen.get('name'),
                    'service': chosen.get('service'),
                    'description': chosen.get('description'),
                    'value': _cost_value(chosen.get('value')),
                    'etd': chosen.get('etd'),
                    'note': chosen.get('note'),
                }
            if not compute_service_cost:
                raise UserError(
                    'No service returned by the shipping API for courier %s.' % courier
                )

            # Store the courier *code* the provider returned: Biteship and
            # Komerce answer with their own code (jne, jnt, ...), which is what
            # the stock.picking.courier selection expects. Imported locally to
            # keep the model import order free of cycles.
            from .stock import resolve_courier_code
            resolved_courier = resolve_courier_code(
                compute_service_cost.get('code'),
                compute_service_cost.get('name')) or courier
            self.courier_name = compute_service_cost['name']
            self.service_name = compute_service_cost['service']
            self.cost_delivery = compute_service_cost['value']
            self.etd = compute_service_cost['etd']
            self.origin_courier = resolved_courier
            return True
        except requests.exceptions.Timeout as e:
            raise UserError('Shipping API timeout: %s' % e)
        except requests.exceptions.RequestException as e:
            raise UserError('Shipping API request failed: %s' % e)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.depends('product_uom_qty', 'weight')
    def _calcsubtotalweight(self):
        for rec in self:
            subtotal_weight = 0
            subtotal_weight = (rec.weight * rec.product_uom_qty)
            rec.weight_subtotal = subtotal_weight

    @api.depends('product_id')
    def _calcweight(self):
        for rec in self:
            if rec.product_id:
                rec.weight = rec.product_id.weight

    weight = fields.Float(compute='_calcweight', string='Weight Unit', store=True)
    weight_subtotal = fields.Float(compute='_calcsubtotalweight', string='Subtotal Weight', store=True)
