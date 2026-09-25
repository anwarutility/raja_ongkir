from odoo import models, fields, api
from odoo.exceptions import UserError
import requests
import math

courier_code = [
    ('jne', 'JNE'),
    ('pos', 'POS'),
    ('tiki', 'TIKI'),
    ('rpx', 'RPX'),
    ('pandu', 'Pandu Logistics'),
    ('wahana', 'Wahana'),
    ('sicepat', 'SiCepat'),
    ('jnt', 'J&T Express'),
    ('pahala', 'Pahala'),
    ('sap', 'SAP Express'),
    ('jet', 'JET Express'),
    ('indah', 'Indah Cargo'),
    ('dse', 'DSE'),
    ('slis', 'SLIS'),
    ('first', 'First Logistics'),
    ('ncs', 'NCS'),
    ('star', 'Star Cargo'),
    ('ninja', 'Ninja Xpress'),
    ('lion', 'Lion Parcel'),
    ('idl', 'IDL Cargo'),
    ('rex', 'REX'),
    ('ide', 'IDE'),
    ('sentral', 'Sentral Cargo'),
    ('anteraja', 'Anteraja'),
    ('jtl', 'JTL')
]

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    currency_id = fields.Many2one('res.currency', related="sale_id.currency_id", store=True)
    city_id = fields.Many2one(comodel_name='res.country.city', string='Destination City', ondelete='cascade', related="sale_id.city_id", store=True)
    subdistrict_id = fields.Many2one(comodel_name='res.city.subdistrict', string='Destination Subdistrict', ondelete='cascade', related="sale_id.subdistrict_id", store=True)
    weight_total = fields.Float(string='Weight Total')
    courier = fields.Selection(courier_code, string='Courier')
    courier_name = fields.Char(string='Courier Name', related="sale_id.courier_name", store=True)
    service_name = fields.Char(string='Service Name')
    cost_delivery = fields.Monetary(string='Cost Delivery')
    etd = fields.Char(string='ETD')

    realitation_courier_name = fields.Char(string='Realitation Courier Name')
    realitation_service_name = fields.Char(string='Realitation Service Name')
    realitation_cost_delivery = fields.Monetary(string='Realitation Cost Delivery')
    realitation_etd = fields.Char(string='Realitation ETD')

    partner_delivery_cost_id = fields.Many2one(comodel_name='res.partner', string='Partner Delivery Cost', compute="_compute_account_data", store=True)
    product_delivery_cost_id = fields.Many2one(comodel_name='product.product', string='Product Delivery Cost', compute="_compute_account_data", store=True)
    account_delivery_cost_id = fields.Many2one(comodel_name='account.account', string='Account Delivery Cost', compute="_compute_account_data", store=True)

    bill_delivery_id = fields.Many2one(comodel_name='account.move', string='Delivery Cost Bill')
    has_bill = fields.Boolean(string='Has Bill', compute="_compute_has_bill")

    @api.depends('bill_delivery_id')
    def _compute_has_bill(self):
        for rec in self:
            rec.has_bill = bool(rec.bill_delivery_id)

    def create_delivery_bill(self):
        bill_data = {
            'partner_id': self.partner_delivery_cost_id.id,
            'move_type': 'in_invoice',
            'picking_id': self.id,  # Link the GD/Out record
            'source_document': self.origin,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {
                'name': self.product_delivery_cost_id.name,
                'product_id': self.product_delivery_cost_id.id,
                'quantity': 1,
                'price_unit': self.realitation_cost_delivery,
            })],
        }

        move_id = self.env['account.move'].create(bill_data)
        self.bill_delivery_id = move_id
        return True

    @api.depends('sale_id')
    def _compute_account_data(self):
        for rec in self:
            api = rec.sale_id.raja_ongkir_api
            rec.partner_delivery_cost_id = api.partner_delivery_cost_id
            rec.product_delivery_cost_id = api.product_delivery_cost_id
            rec.account_delivery_cost_id = api.account_delivery_cost_id

    @api.onchange('city_id')
    def _city_id_onchange(self):
        res = {}
        res['domain'] = {'subdistrict_id': [('city_id', '=', self.city_id.city_id)]}
        return res

    def _auto_weight_from_moves(self):
        """Auto weight (kg) derived from the move lines. Used to prefill the
        editable Weight Total field; a manual value is always respected."""
        self.ensure_one()
        totalweight = 0
        for move in self.move_ids_without_package:
            totalweight += (move.product_id.weight or 0) * move.quantity_done
        return math.ceil(totalweight)

    @api.onchange('move_ids_without_package')
    def _onchange_weight_from_moves(self):
        for rec in self:
            if not rec.weight_total:
                rec.weight_total = rec._auto_weight_from_moves()

    def _resolve_ongkir_origin(self):
        """Return (origin_id, origin_type) for the RajaOngkir /api/cost call."""
        api = self.sale_id.raja_ongkir_api
        if not api:
            raise UserError('Please set Raja Ongkir API in Sale Order.')
        origin_type = self.sale_id.origin_city_type or 'city'
        if origin_type == 'subdistrict':
            if not api.origin_subdistrict_id:
                raise UserError('Please set Origin Subdistrict on the Raja Ongkir API config.')
            return api.origin_subdistrict_id.subdistrict_id, origin_type
        if not api.origin_city_id:
            raise UserError('Please set Origin City on the Raja Ongkir API config.')
        return api.origin_city_id.city_id, origin_type

    def _resolve_ongkir_destination(self):
        """Return (destination_id, destination_type) for the RajaOngkir call."""
        destination_type = self.sale_id.destination_city_type or 'city'
        if destination_type == 'subdistrict':
            if not self.subdistrict_id:
                raise UserError('Please set Destination Subdistrict (Kecamatan) on the Sale Order / customer.')
            return self.subdistrict_id.subdistrict_id, destination_type
        if not self.city_id:
            raise UserError('Please set Destination City (Kabupaten/Kota) on the Sale Order / customer.')
        return self.city_id.city_id, destination_type

    def _ongkir_weight_grams(self):
        """Ongkos kirim needs a minimum of 1 kg; fall back to the auto weight
        derived from the move lines, then to 1000 grams."""
        weight_kg = self.weight_total or self._auto_weight_from_moves() or 1
        if weight_kg <= 0:
            weight_kg = 1
        return int(weight_kg * 1000)

    def _is_komerce(self, api):
        """Komerce (rajaongkir.komerce.id) exposes a different API layout and
        response format than the classic RajaOngkir (/api/cost)."""
        return bool(api.api_url) and 'komerce.id' in api.api_url

    def _ongkir_url(self, api, path):
        """Build the endpoint URL, tolerating both the default RajaOngkir
        layout (``https://pro.rajaongkir.com/api``) and full bases such as
        ``https://rajaongkir.komerce.id/api/v1``."""
        base = (api.api_url or 'https://pro.rajaongkir.com').strip().rstrip('/')
        if not base.endswith('/api/v1') and not base.endswith('/api') \
                and not base.endswith('/cost'):
            base += '/api'
        return base + path

    def _fetch_ongkir_services(self, api, courier, origin, origin_type,
                               destination, destination_type, weight):
        """Query the shipping cost for one courier and return a normalized
        list of services. Handles both the classic RajaOngkir and the
        Komerce API layouts."""
        headers = {
            'content-type': 'application/x-www-form-urlencoded',
            'key': api.api_key,
        }

        if self._is_komerce(api):
            endpoint = '/calculate/district/domestic-cost'
            payload = {
                'origin': origin,
                'destination': destination,
                'weight': weight,
                'courier': courier,
            }
            url = self._ongkir_url(api, endpoint)
            response = requests.post(url, headers=headers, data=payload, timeout=25)
            try:
                parsed_response = response.json()
            except ValueError:
                raise UserError(
                    'Komerce returned HTTP %s (invalid JSON). Response body: %s'
                    % (response.status_code, (response.text or '')[:200])
                )
            try:
                meta = parsed_response.get('meta') or {}
                results = parsed_response.get('data') or []
            except AttributeError:
                raise UserError('Komerce returned an unexpected response format.')
            if meta.get('code') not in (200, '200') or meta.get('status') is False:
                message = meta.get('message', '') or ''
                # A courier without a rate on this route simply has no options.
                if 'not found' in message.lower():
                    return []
                raise UserError('Komerce error: %s' % message)
            services = [{
                'code': result.get('code'),
                'name': result.get('name'),
                'service': result.get('service'),
                'description': result.get('description'),
                'value': result.get('cost'),
                'etd': result.get('etd'),
                'note': result.get('description'),
            } for result in results]
            return services

        data = "origin=%(origin)s&destination=%(destination)s&weight=%(weight)s&courier=%(courier)s&originType=%(originType)s&destinationType=%(destinationType)s" % {
            "origin": origin,
            "destination": destination,
            "weight": weight,
            "courier": courier,
            "originType": origin_type,
            "destinationType": destination_type,
        }
        url = self._ongkir_url(api, '/cost')
        response = requests.post(url, headers=headers, data=data, timeout=25)
        try:
            parsed_response = response.json()
        except ValueError:
            raise UserError(
                'Raja Ongkir returned HTTP %s (invalid JSON). Response body: %s'
                % (response.status_code, (response.text or '')[:200])
            )
        try:
            status = parsed_response['rajaongkir']['status']
            results = parsed_response['rajaongkir']['results'] or []
        except (KeyError, TypeError, ValueError):
            raise UserError('Raja Ongkir returned an unexpected response format.')
        if status.get('code') != 200:
            raise UserError(
                'Raja Ongkir error: %s'
                % status.get('description', '')
            )
        services = []
        for result in results:
            for costs in result.get('costs') or []:
                for cost in costs.get('cost') or []:
                    services.append({
                        'code': result.get('code'),
                        'name': result.get('name'),
                        'service': costs.get('service'),
                        'description': costs.get('description'),
                        'value': cost.get('value'),
                        'etd': cost.get('etd'),
                        'note': cost.get('note'),
                    })
        return services

    def _open_ongkir_popup(self, mode):
        return {
            'name': 'List Ongkir',
            'view_mode': 'tree',
            'view_type': 'form',
            'res_model': 'ongkir.list',
            'type': 'ir.actions.act_window',
            'target': 'new',
            'context': dict(self.env.context, ongkir_mode=mode),
            'domain': [('picking_id', '=', self.id)],
        }

    def compute_estimation_ongkir(self):
        """Fetch the rates of the chosen courier. A single option fills the
        Estimation group automatically; several options open the list popup so
        the user can pick the service (e.g. Lion: Regpack / Jagopack)."""
        self.ensure_one()
        if not self.sale_id:
            raise UserError('Please set source Sale Order.')

        api = self.sale_id.raja_ongkir_api
        if not api:
            raise UserError('Please set Raja Ongkir API in Sale Order.')
        if api.status != 'enable':
            raise UserError('Raja Ongkir API is disabled. Enable it first under '
                            'Inventory > Configuration > Raja Ongkir > Api.')

        courier = self.courier or self.sale_id.origin_courier
        if not courier:
            raise UserError('Please choose a courier (default Courier field starts empty; '
                            'set it on this tab or on the Raja Ongkir API config).')

        weight = self._ongkir_weight_grams()
        origin, origin_type = self._resolve_ongkir_origin()
        destination, destination_type = self._resolve_ongkir_destination()

        try:
            services = self._fetch_ongkir_services(
                api, courier, origin, origin_type, destination, destination_type, weight
            )
        except requests.exceptions.RequestException as exc:
            raise UserError('Failed to reach Raja Ongkir: %s' % exc)

        if not services:
            raise UserError('No rate for courier %s on this route/weight. '
                            'Try another courier or weight.'
                            % (dict(courier_code).get(courier) or courier))

        # Exactly one option: fill the Estimation group directly.
        if len(services) == 1:
            self.env['ongkir.list'].search([('picking_id', '=', self.id)]).unlink()
            entry = services[0]
            self.write({
                'courier': courier,
                'courier_name': entry['name'],
                'service_name': entry['service'],
                'cost_delivery': entry['value'],
                'etd': entry['etd'],
            })
            return True

        # Several options: let the user pick the service.
        self.env['ongkir.list'].search([('picking_id', '=', self.id)]).unlink()
        for entry in services:
            self.env['ongkir.list'].create({
                'picking_id': self.id,
                'name': entry['name'],
                'service': entry['service'],
                'value': entry['value'],
                'etd': entry['etd'],
                'note': entry['note'],
            })
        return self._open_ongkir_popup('estimation')

    def getBiaya(self):
        """Compute the rates of ALL available couriers and open the list popup
        so the user can pick the desired courier/service (Realitation Cost)."""
        self.ensure_one()
        if not self.sale_id:
            raise UserError('Please set source Sale Order.')

        api = self.sale_id.raja_ongkir_api
        if not api:
            raise UserError('Please set Raja Ongkir API in Sale Order.')
        if api.status != 'enable':
            raise UserError('Raja Ongkir API is disabled. Enable it first under '
                            'Inventory > Configuration > Raja Ongkir > Api.')

        self.env['ongkir.list'].search([('picking_id', '=', self.id)]).unlink()

        weight = self._ongkir_weight_grams()
        courier_list = list(dict(courier_code).keys())
        origin, origin_type = self._resolve_ongkir_origin()
        destination, destination_type = self._resolve_ongkir_destination()

        errors = []
        created = 0
        for courier in courier_list:
            try:
                services = self._fetch_ongkir_services(
                    api, courier, origin, origin_type, destination, destination_type, weight
                )
            except (UserError, requests.exceptions.RequestException) as exc:
                errors.append('%s: %s' % (courier, exc))
                continue
            for entry in services:
                self.env['ongkir.list'].create({
                    'picking_id': self.id,
                    'name': entry['name'],
                    'service': entry['service'],
                    'value': entry['value'],
                    'etd': entry['etd'],
                    'note': entry['note'],
                })
                created += 1

        if not created:
            if errors:
                raise UserError('Tidak ada tarif tersedia untuk rute/berat ini.\n'
                                'Kurir tanpa tarif:\n%s' % '\n'.join(errors))
            raise UserError('No rate found for this route/weight.')

        return self._open_ongkir_popup('realitation')

class ListOngkir(models.Model):
    _name = 'ongkir.list'
    _order = 'value, name, service'

    picking_id = fields.Many2one(comodel_name='stock.picking', string='Picking Id')
    name = fields.Char(string='Courier Name')
    service = fields.Char(string='Service Name')
    value = fields.Integer(string='Cost Delivery')
    etd = fields.Char(string='ETD')
    note = fields.Char(string='Note')

    def pilihLayanan(self):
        record = self.env['stock.picking'].search([('id', '=', self.picking_id.id)])
        label_to_code = {label: code for code, label in courier_code}
        if self.env.context.get('ongkir_mode') == 'estimation':
            record.write({
                'courier': label_to_code.get(self.name),
                'courier_name': self.name,
                'service_name': self.service,
                'cost_delivery': self.value,
                'etd': self.etd,
            })
        else:
            record.write({
                'realitation_courier_name': self.name,
                'realitation_service_name': self.service,
                'realitation_cost_delivery': self.value,
                'realitation_etd': self.etd,
            })

class AccountMove(models.Model):
    _inherit = 'account.move'

    picking_id = fields.Many2one('stock.picking', string="GD/Out", help="Link to the related GD/Out")
    source_document = fields.Char(string='Source Document')
