from odoo import models, fields, api
from odoo.exceptions import UserError
import requests
import math

from .ongkir_utils import (
    BITESHIP_RATES_PATH,
    biteship_base,
    biteship_headers,
    is_komerce,
    komerce_route,
    ongkir_url,
    parse_biteship_pricing,
)

# Biteship prices by courier, not by the RajaOngkir courier selection. Asking
# for all of them returns every service (JNE reg/jtr/yes, SiCepat, ...), so the
# Sales Order can offer a real choice instead of a single hardcoded courier.
BITESHIP_COURIER_CODES = (
    'jne,jnt,sicepat,anteraja,ninja,lion,pos,tiki,idexpress,rex,'
    'sap,sentralcargo,wahana,jtl,ncs,star,pandu,dse,slis,first'
)

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

def resolve_courier_code(code=None, name=None):
    """Map one API rate row back to a `stock.picking.courier` selection value.

    Providers return their own legal/trade name -- Komerce answers
    ``"Jalur Nugraha Ekakurir (JNE)"`` -- which never matches our selection
    labels, so matching on the name is unreliable. The machine ``code`` the API
    returns is authoritative and is used first; ``name`` is only a fallback for
    rows saved before `ongkir.list.code` existed.

    Returns None when the courier is unknown instead of silently storing an
    empty courier on the picking.
    """
    code_to_label = dict(courier_code)
    if code and code in code_to_label:
        return code

    label_to_code = {label: code for code, label in courier_code}
    if not name:
        return None

    normalised_name = ' '.join(name.split()).casefold()
    normalised_labels = {
        ' '.join(label.split()).casefold(): code
        for code, label in courier_code
    }
    if normalised_name in normalised_labels:
        return normalised_labels[normalised_name]
    for label, code in normalised_labels.items():
        if label in normalised_name:
            return code
    return None

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
        editable Weight Total field; a manual value is always respected.

        ``quantity_done`` is the truth once a move is processed, but before that
        it is still 0 while Odoo has already reserved ``product_uom_qty``. Only
        then is the reserved demand used -- counting a not-yet-done bulk line as
        zero quoted 40 printers as a 1 kg parcel. Cancelled moves are skipped
        because they no longer ship. Ceiling to whole kilograms matches how
        couriers bill. Same rule as the Delivery Cost tab so the two tabs of one
        Delivery Order never disagree.
        """
        self.ensure_one()
        totalweight = 0
        for move in self.move_ids_without_package:
            if move.state == 'cancel':
                continue
            quantity = move.quantity_done or move.product_uom_qty or 0
            totalweight += (move.product_id.weight or 0) * quantity
        return math.ceil(totalweight)

    @api.onchange('move_ids_without_package')
    def _onchange_weight_from_moves(self):
        for rec in self:
            if not rec.weight_total:
                rec.weight_total = rec._auto_weight_from_moves()

    def _resolve_ongkir_origin(self):
        """Return the origin area for the rate call.

        Shape: ``{'type': 'city'|'subdistrict', 'city_id': int,
        'subdistrict_id': int|None}``. ``city_id`` is always filled -- a
        kecamatan carries its parent city -- so the route can be demoted to
        city pricing when the other end is a city.
        """
        api = self.sale_id.raja_ongkir_api
        if not api:
            raise UserError('Please set Biteship API in Sale Order.')
        origin_type = self.sale_id.origin_city_type or 'city'
        if origin_type == 'subdistrict':
            sub = api.origin_subdistrict_id
            if not sub:
                raise UserError('Please set Origin Subdistrict on the Biteship API config.')
            city_id = sub.city_rel.city_id
            if not city_id and api.origin_city_id:
                city_id = api.origin_city_id.city_id
            return {'type': 'subdistrict', 'city_id': city_id,
                    'subdistrict_id': sub.subdistrict_id,
                    'city_record': sub.city_rel,
                    'subdistrict_record': sub}
        if not api.origin_city_id:
            raise UserError('Please set Origin City on the Biteship API config.')
        return {'type': 'city', 'city_id': api.origin_city_id.city_id,
                'subdistrict_id': None,
                'city_record': api.origin_city_id,
                'subdistrict_record': None}

    def _resolve_ongkir_destination(self):
        """Return the destination area for the rate call (same shape as
        ``_resolve_ongkir_origin``)."""
        destination_type = self.sale_id.destination_city_type or 'city'
        if destination_type == 'subdistrict':
            sub = self.subdistrict_id
            if not sub:
                raise UserError('Please set Destination Subdistrict (Kecamatan) on the Sale Order / customer.')
            city_id = sub.city_rel.city_id
            if not city_id and self.city_id:
                city_id = self.city_id.city_id
            return {'type': 'subdistrict', 'city_id': city_id,
                    'subdistrict_id': sub.subdistrict_id,
                    'city_record': sub.city_rel or self.city_id,
                    'subdistrict_record': sub}
        if not self.city_id:
            raise UserError('Please set Destination City (Kabupaten/Kota) on the Sale Order / customer.')
        return {'type': 'city', 'city_id': self.city_id.city_id,
                'subdistrict_id': None,
                'city_record': self.city_id,
                'subdistrict_record': None}

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
        return is_komerce(api.api_url)

    def _fetch_biteship_services(self, api, origin, destination, weight, couriers):
        """Call ``POST /v1/rates/couriers`` and return the service rows.

        ``couriers`` is a comma-separated list of Biteship courier codes. One
        request answers **every** service of those couriers, so asking for a
        single courier (the Sales Order path) returns just that courier's
        services -- important because several couriers all name their regular
        service "Reguler", and picking across couriers would quote the wrong
        one. The Delivery Order "Get Biaya" passes the whole list to compare.
        """
        origin_area = api._biteship_area_id(
            city=origin.get('city_record'),
            subdistrict=origin.get('subdistrict_record'),
        )
        if not origin_area:
            raise UserError(
                'Origin (asal kirim) tidak bisa dipetakan ke area Biteship. '
                'Lengkapi kecamatan/kode pos asal pada konfigurasi API.')
        destination_area = api._biteship_area_id(
            city=destination.get('city_record'),
            subdistrict=destination.get('subdistrict_record'),
        )
        if not destination_area:
            raise UserError(api._biteship_missing_destination_message())

        payload = {
            'origin_area_id': origin_area,
            'destination_area_id': destination_area,
            'couriers': (couriers or '').strip() or BITESHIP_COURIER_CODES,
            'items': [{
                'name': 'Barang',
                'value': 0,
                'quantity': 1,
                'weight': max(int(weight or 0), 1),
            }],
        }
        url = biteship_base(api.api_url) + BITESHIP_RATES_PATH
        try:
            response = requests.post(
                url,
                headers=biteship_headers(api.api_key),
                json=payload,
                timeout=30,
            )
        except requests.exceptions.RequestException as exc:
            raise UserError('Gagal menghubungi Biteship: %s' % exc)
        if response.status_code in (401, 403):
            raise UserError(
                'Autentikasi Biteship gagal (HTTP %s). Periksa API Key pada '
                'konfigurasi API.' % response.status_code)
        try:
            parsed = response.json()
        except ValueError:
            raise UserError(
                'Biteship mengembalikan HTTP %s (bukan JSON). Body: %s'
                % (response.status_code, (response.text or '')[:200]))
        if not parsed.get('success'):
            message = parsed.get('error') or parsed.get('message') or ''
            if 'not found' in message.lower():
                return []
            raise UserError('Biteship error: %s' % (message or 'unknown error'))
        return parse_biteship_pricing(parsed.get('pricing'))

    def _ongkir_url(self, api, path):
        """Build the endpoint URL, tolerating both the default RajaOngkir
        layout (``https://pro.rajaongkir.com/api``) and full bases such as
        ``https://rajaongkir.komerce.id/api/v1``."""
        return ongkir_url(api.api_url, path)

    def _fetch_ongkir_services(self, api, courier, origin, destination, weight):
        """Query the shipping cost for one courier and return a normalized
        list of services. Handles Biteship, the classic RajaOngkir and the
        Komerce API layouts.

        ``origin``/``destination`` are dicts ``{'type', 'city_id',
        'subdistrict_id', 'city_record', 'subdistrict_record'}`` so the Komerce
        endpoint can follow the area type the route was priced with (see
        ``ongkir_utils.komerce_route``) and Biteship can resolve its own
        ``area_id``.
        """
        headers = {
            'content-type': 'application/x-www-form-urlencoded',
            'key': api.api_key,
        }

        if api._is_biteship():
            return self._fetch_biteship_services(
                api, origin, destination, weight, courier)

        if self._is_komerce(api):
            endpoint, origin_id, destination_id = komerce_route(origin, destination)
            if not origin_id or not destination_id:
                raise UserError(
                    'Origin/destination area is missing its area id. '
                    'Set the origin on the Biteship API config and the '
                    'destination on the Sale Order / customer.')
            payload = {
                'origin': origin_id,
                'destination': destination_id,
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
            "origin": origin.get('city_id') if origin.get('type') == 'city'
                      else origin.get('subdistrict_id'),
            "destination": destination.get('city_id') if destination.get('type') == 'city'
                           else destination.get('subdistrict_id'),
            "weight": weight,
            "courier": courier,
            "originType": origin.get('type'),
            "destinationType": destination.get('type'),
        }
        url = self._ongkir_url(api, '/cost')
        response = requests.post(url, headers=headers, data=data, timeout=25)
        try:
            parsed_response = response.json()
        except ValueError:
            raise UserError(
                'Provider returned HTTP %s (invalid JSON). Response body: %s'
                % (response.status_code, (response.text or '')[:200])
            )
        try:
            status = parsed_response['rajaongkir']['status']
            results = parsed_response['rajaongkir']['results'] or []
        except (KeyError, TypeError, ValueError):
            raise UserError('Provider returned an unexpected response format.')
        if status.get('code') != 200:
            raise UserError(
                'Provider error: %s'
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
            raise UserError('Please set Biteship API in Sale Order.')
        if api.status != 'enable':
            raise UserError('Biteship API is disabled. Enable it first under '
                            'Inventory > Configuration > Biteship > Api.')

        # Biteship returns every service of the requested couriers in one call,
        # so the "Courier" field only applies to the RajaOngkir layouts.
        if api._is_biteship():
            courier = self.courier or self.sale_id.origin_courier or 'jne'
        else:
            courier = self.courier or self.sale_id.origin_courier
            if not courier:
                raise UserError('Please choose a courier (default Courier field starts empty; '
                                'set it on this tab or on the Biteship API config).')

        weight = self._ongkir_weight_grams()
        origin = self._resolve_ongkir_origin()
        destination = self._resolve_ongkir_destination()

        try:
            services = self._fetch_ongkir_services(
                api, courier, origin, destination, weight
            )
        except requests.exceptions.RequestException as exc:
            raise UserError('Failed to reach the shipping API: %s' % exc)

        if not services:
            raise UserError('No rate for courier %s on this route/weight. '
                            'Try another courier or weight.'
                            % (dict(courier_code).get(courier) or courier))

        # Exactly one option: fill the Estimation group directly.
        if len(services) == 1:
            self.env['ongkir.list'].search([('picking_id', '=', self.id)]).unlink()
            entry = services[0]
            self.write({
                'courier': resolve_courier_code(entry.get('code'), entry.get('name')) or courier,
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
                'code': entry['code'],
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
            raise UserError('Please set Biteship API in Sale Order.')
        if api.status != 'enable':
            raise UserError('Biteship API is disabled. Enable it first under '
                            'Inventory > Configuration > Biteship > Api.')

        self.env['ongkir.list'].search([('picking_id', '=', self.id)]).unlink()

        weight = self._ongkir_weight_grams()
        origin = self._resolve_ongkir_origin()
        destination = self._resolve_ongkir_destination()

        # Biteship answers every courier in ONE request, so it must not be run
        # once per courier (that would burn 20 calls and its daily quota).
        if api._is_biteship():
            try:
                services = self._fetch_biteship_services(
                    api, origin, destination, weight, BITESHIP_COURIER_CODES)
            except (UserError, requests.exceptions.RequestException) as exc:
                raise UserError(
                    'Tidak ada tarif tersedia untuk rute/berat ini.\n%s' % exc)
            created = 0
            for entry in services:
                self.env['ongkir.list'].create({
                    'picking_id': self.id,
                    'code': entry['code'],
                    'name': entry['name'],
                    'service': entry['service'],
                    'value': entry['value'],
                    'etd': entry['etd'],
                    'note': entry['note'],
                })
                created += 1
            if not created:
                raise UserError('No rate found for this route/weight.')
            return self._open_ongkir_popup('realitation')

        courier_list = list(dict(courier_code).keys())

        errors = []
        created = 0
        for courier in courier_list:
            try:
                services = self._fetch_ongkir_services(
                    api, courier, origin, destination, weight
                )
            except (UserError, requests.exceptions.RequestException) as exc:
                errors.append('%s: %s' % (courier, exc))
                continue
            for entry in services:
                self.env['ongkir.list'].create({
                    'picking_id': self.id,
                    'code': entry['code'],
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
    code = fields.Char(string='Courier Code')
    name = fields.Char(string='Courier Name')
    service = fields.Char(string='Service Name')
    value = fields.Integer(string='Cost Delivery')
    etd = fields.Char(string='ETD')
    note = fields.Char(string='Note')

    def pilihLayanan(self):
        self.ensure_one()
        record = self.picking_id
        if not record:
            return
        if self.env.context.get('ongkir_mode') == 'estimation':
            code = resolve_courier_code(self.code, self.name)
            if not code:
                raise UserError(
                    'Courier "%s" is not in the courier list, so it '
                    'cannot be stored on the picking. Add it to the Courier '
                    'selection first.' % (self.name or '')
                )
            record.write({
                'courier': code,
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
