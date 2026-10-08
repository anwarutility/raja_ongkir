# -*- coding: utf-8 -*-

import json
import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .ongkir_utils import (
    biteship_search_areas,
    is_biteship,
    resolve_biteship_area,
)

_logger = logging.getLogger(__name__)

API_TIMEOUT = 30

# Reference data (province / city / subdistrict) is published only by the
# official RajaOngkir API. Komerce's compatible endpoint serves
# ``/calculate/...`` only and answers every other GET with the plain-text body
# ``404 page not found``. Calling ``.json()`` on that used to reach the user as
# a raw JSONDecodeError traceback, because ``404`` parses as a number and
# ``page not found`` is then reported as "Extra data".
HOSTS_WITHOUT_REFERENCE_DATA = ('komerce.id',)


class UnsupportedEndpoint(UserError):
    """The provider does not expose reference-data endpoints at all.

    Distinct from a per-item failure: retrying the remaining provinces or
    cities would only issue more requests that cannot succeed (a Komerce
    ``sync_subdistrict`` run would fire 474 doomed calls).
    """

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

class Api(models.Model):
    _name = 'api.list'

    name = fields.Char(string='Name')
    api_key = fields.Char(string="API Key")
    api_url = fields.Char(string="API Url", default="https://pro.rajaongkir.com")
    status = fields.Selection([('enable', 'Enable'), ('disable', 'Disable')], string='Status', default='disable', copy=False)
    origin_city_type_default = fields.Selection(string='Origin City Type', selection=[('city', 'Kabupaten/Kota'), ('subdistrict', 'Kecamatan'), ], default='city')
    origin_city_id = fields.Many2one(comodel_name='res.country.city', string='Origin City', ondelete='cascade')
    origin_subdistrict_id = fields.Many2one(comodel_name='res.city.subdistrict', string='Origin Subdistrict', ondelete='cascade')
    origin_courier = fields.Selection(string='Origin Courier', selection=courier_code, default='jne')
    service = fields.Char(
        string='Service', default='REG',
        help="Preferred shipping service used by the Sales Order "
             "\"Compute Cost Delivery\" button (e.g. REG, YES, CTC). When the "
             "provider does not offer this service on the route, the cheapest "
             "available service is used instead.")
    destination_city_type_default = fields.Selection(string='Destination City Type', selection=[('city', 'Kabupaten/Kota'), ('subdistrict', 'Kecamatan'), ], default='city')
    partner_delivery_cost_id = fields.Many2one(comodel_name='res.partner', string='Partner Delivery Cost')
    product_delivery_cost_id = fields.Many2one(comodel_name='product.product', string='Product Delivery Cost')
    account_delivery_cost_id = fields.Many2one(comodel_name='account.account', string='Account Delivery Cost')

    @api.onchange('origin_city_id')
    def _provinsi_onchange(self):
        res = {}
        res['domain'] = {'origin_subdistrict_id': [('city_id', '=', self.origin_city_id.city_id)]}
        return res

    def btn_status(self):
        if self.status == "enable":
            self.status = "disable"
        else:
            self.status = "enable"

    # ------------------------------------------------------------------
    # Biteship support
    # ------------------------------------------------------------------

    def _is_biteship(self):
        """True when this record points at api.biteship.com."""
        return is_biteship(self.api_url)

    def _biteship_search(self, query):
        return biteship_search_areas(self.api_key, self.api_url, query)

    def _biteship_area_id(self, city=None, subdistrict=None):
        """Resolve (and cache) the Biteship ``area_id`` of a city or kecamatan.

        Biteship prices routes by its own ``area_id`` and does not accept the
        RajaOngkir ``city_id`` / ``subdistrict_id`` this database stores, so the
        area has to be looked up. The result is cached on the master record, so
        only the first quotation of a given kecamatan pays for the extra call.

        Returns ``None`` when Biteship has no confident match, so the caller can
        report an unusable address instead of quoting a wrong zone.
        """
        self.ensure_one()
        record = subdistrict or city
        if not record:
            return None
        if record.biteship_area_id:
            return record.biteship_area_id
        area = resolve_biteship_area(
            self._biteship_search,
            postal_code=(record.postal_code
                         if 'postal_code' in record._fields else None),
            district=record.name,
            city=(record.city_rel.name if subdistrict else None),
        )
        if not area:
            return None
        record.write({'biteship_area_id': area['id']})
        return area['id']

    def _biteship_missing_destination_message(self):
        return (
            'Alamat tujuan tidak bisa dipetakan ke area Biteship secara tepat. '
            'Biteship mencari alamat secara kabur, jadi tanpa kecamatan atau '
            'kode pos yang cocok zona ongkir bisa salah. Lengkapi kecamatan '
            '(Destination Subdistrict) atau kode pos pada customer / kota '
            'tujuan, lalu coba lagi.'
        )

    def _api_url(self, path):
        """Build the endpoint URL, tolerating both the default RajaOngkir
        layout (``https://pro.rajaongkir.com/api``) and full bases such as
        ``https://rajaongkir.komerce.id/api/v1``."""
        base = (self.api_url or 'https://pro.rajaongkir.com').strip().rstrip('/')
        if not base.endswith('/api/v1') and not base.endswith('/api'):
            base += '/api'
        return base + path

    def _api_check_ready(self):
        if self.status != 'enable' or not self.api_key:
            raise UserError(_('Please charge the API or activate the API.'))

    def _api_unsupported_message(self, url, response):
        snippet = (response.text or '').strip()[:120] or '<empty>'
        if any(host in url for host in HOSTS_WITHOUT_REFERENCE_DATA):
            return _(
                '%(url)s does not publish province/city/subdistrict lists '
                '(HTTP %(code)s: %(body)s).\n'
                'Syncing these needs an official RajaOngkir API key from '
                'https://pro.rajaongkir.com. A Komerce account can only '
                'calculate rates, so add the cities manually or point this '
                'record at pro.rajaongkir.com.'
            ) % {'url': url, 'code': response.status_code, 'body': snippet}
        return _(
            '%(url)s answered HTTP %(code)s, so this API cannot sync '
            'province/city/subdistrict data (response: %(body)s). Check the '
            'API Url and key.'
        ) % {'url': url, 'code': response.status_code, 'body': snippet}

    def _api_get_json(self, path):
        """GET ``path`` and return the decoded JSON body.

        Transport and decoding problems become a ``UserError`` naming the URL
        and what to fix, instead of escaping as a server traceback. No request
        body is sent: these are plain GET endpoints and passing ``data=`` on a
        GET only confuses strict proxies.
        """
        self.ensure_one()
        url = self._api_url(path)
        headers = {'content-type': 'application/json', 'key': self.api_key}
        try:
            response = requests.get(url, headers=headers, timeout=API_TIMEOUT)
        except requests.exceptions.Timeout:
            raise UserError(_(
                'RajaOngkir did not answer within %s seconds (%s). Check your '
                'internet connection and try again.') % (API_TIMEOUT, url))
        except requests.exceptions.ConnectionError:
            raise UserError(_(
                'Could not connect to %s. Check the API Url and your network.') % url)
        except requests.exceptions.RequestException as error:
            raise UserError(_('Request to %s failed: %s') % (url, error))
        body = (response.text or '').strip()
        if response.status_code in (404, 405):
            raise UnsupportedEndpoint(
                self._api_unsupported_message(url, response))
        if not body:
            raise UserError(_('%s returned an empty response (HTTP %s).') % (
                url, response.status_code))
        try:
            return json.loads(body)
        except ValueError:
            raise UserError(_(
                '%s did not return JSON (HTTP %s). Response: %s') % (
                    url, response.status_code, body[:200]))

    def _api_results(self, path):
        """Return the ``rajaongkir.results`` list published by ``path``."""
        self.ensure_one()
        url = self._api_url(path)
        payload = self._api_get_json(path)
        if not isinstance(payload, dict):
            raise UserError(_('Unexpected answer from %s: %s') % (
                url, str(payload)[:200]))
        section = payload.get('rajaongkir')
        if not isinstance(section, dict) or 'results' not in section:
            raise UserError(_(
                '%s did not return a RajaOngkir result list. The key may be '
                'invalid or the account not activated yet.') % url)
        results = section.get('results')
        if results is None:
            return []
        if not isinstance(results, list):
            raise UserError(_('Unexpected "results" from %s: %s') % (
                url, str(results)[:200]))
        return results

    def _api_notify(self, label, created, updated, failures):
        """Report the outcome of a sync run.

        Partial failures are reported as a warning rather than raised, because
        raising would roll back the provinces/cities that did sync.
        """
        title = _('Biteship - %(label)s') % {'label': label}
        if failures:
            head = _(
                '%(label)s sync finished with %(failed)s failed request(s): '
                '%(created)s created, %(updated)s updated.'
            ) % {
                'label': label, 'failed': len(failures),
                'created': created, 'updated': updated,
            }
            detail = '\n'.join(failures[:8])
            if len(failures) > 8:
                detail += '\n' + _('... and %s more, see the Odoo log.') % (
                    len(failures) - 8)
            _logger.error('%s sync: %s | failures: %s', label, head, failures)
            params = {
                'title': title,
                'message': head + '\n\n' + detail,
                'type': 'warning',
                'sticky': True,
            }
        else:
            params = {
                'title': title,
                'message': _(
                    '%(label)s sync finished: %(created)s created, '
                    '%(updated)s updated.') % {
                        'label': label, 'created': created, 'updated': updated,
                    },
                'type': 'success',
                'sticky': False,
            }
            _logger.info('%s sync finished: %s created, %s updated', label,
                         created, updated)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': params,
        }

    def _api_country(self):
        country = self.env['res.country'].search([('name', '=', 'Indonesia')], limit=1)
        if not country:
            raise UserError(_(
                'Country "Indonesia" is missing from the database, so '
                'provinces cannot be created. Add it first, then sync again.'))
        return country

    def sync_province(self):
        self._api_check_ready()
        results = self._api_results("/province")
        province_obj = self.env['res.country.state']
        country = self._api_country()
        created = updated = 0
        for item in results:
            if not isinstance(item, dict) or not item.get('province_id'):
                _logger.warning('Skipping malformed province entry: %s', item)
                continue
            # Scoped to Indonesia: a bare name match can hijack an identically
            # named state from another country and attach a RajaOngkir id to it.
            existing = province_obj.search([
                '|', ('province_id', '=', item['province_id']),
                '&', ('name', '=', item['province']),
                ('country_id', '=', country.id),
            ], limit=1)
            values = {
                'province_id': item['province_id'],
                'code': item['province_id'],
            }
            if existing:
                if not existing.province_id:
                    existing.write(values)
                    updated += 1
            else:
                values.update({
                    'name': item['province'],
                    'country_id': country.id,
                })
                province_obj.create(values)
                created += 1
        return self._api_notify(_('Province'), created, updated, [])

    def sync_city(self):
        self._api_check_ready()
        province_obj = self.env['res.country.state']
        city_obj = self.env['res.country.city']
        provinces = province_obj.search([('province_id', '!=', False)])
        if not provinces:
            self.sync_province()
            provinces = province_obj.search([('province_id', '!=', False)])
            if not provinces:
                raise UserError(_(
                    'No province with a RajaOngkir id yet. Sync Province '
                    'first and make sure the API supports it.'))
        created = updated = 0
        failures = []
        for province in provinces:
            try:
                results = self._api_results("/city?province=%s" % province.province_id)
            except UnsupportedEndpoint:
                # The provider has no city list at all: stop now instead of
                # asking every remaining province the same question.
                raise
            except UserError as error:
                # One province failing must not discard the others, so the
                # problem is collected and reported once at the end.
                failures.append('%s: %s' % (province.name, error.args[0]))
                continue
            for item in results:
                if not isinstance(item, dict) or not item.get('city_id'):
                    _logger.warning('Skipping malformed city entry: %s', item)
                    continue
                # Matched on the RajaOngkir id, or on the name *within this
                # province*: a bare name match can hijack a same-named city
                # from another province and relink it to the wrong one.
                existing = city_obj.search([
                    '|',
                    ('city_id', '=', item['city_id']),
                    '&', ('name', '=', item['city_name']),
                    ('province_rel', '=', province.id),
                ], limit=1)
                values = {
                    'city_id': item['city_id'],
                    'province_id': item['province_id'],
                    'province_rel': province.id,
                    'type': item.get('type'),
                    'postal_code': item.get('postal_code'),
                }
                if existing:
                    if not existing.city_id:
                        existing.write(values)
                        updated += 1
                else:
                    values['name'] = item['city_name']
                    city_obj.create(values)
                    created += 1
        if failures and not (created or updated):
            raise UserError(_(
                'City sync failed for all %(count)s province(s). First error: %(error)s'
            ) % {'count': len(failures), 'error': failures[0]})
        return self._api_notify(_('City'), created, updated, failures)

    def sync_subdistrict(self):
        self._api_check_ready()
        city_obj = self.env['res.country.city']
        subdistrict_obj = self.env['res.city.subdistrict']
        cities = city_obj.search([('city_id', '!=', False)])
        if not cities:
            self.sync_city()
            cities = city_obj.search([('city_id', '!=', False)])
            if not cities:
                raise UserError(_(
                    'No city with a RajaOngkir id yet. Sync City first and '
                    'make sure the API supports it.'))
        created = updated = 0
        failures = []
        for city in cities:
            try:
                results = self._api_results("/subdistrict?city=%s" % city.city_id)
            except UnsupportedEndpoint:
                raise
            except UserError as error:
                failures.append('%s: %s' % (city.name, error.args[0]))
                continue
            for item in results:
                if not isinstance(item, dict) or not item.get('subdistrict_id'):
                    _logger.warning('Skipping malformed subdistrict entry: %s', item)
                    continue
                existing = subdistrict_obj.search([
                    '|', ('subdistrict_id', '=', item['subdistrict_id']),
                    '&', ('name', '=', item['subdistrict_name']),
                    ('city_rel', '=', city.id),
                ], limit=1)
                values = {
                    'subdistrict_id': item['subdistrict_id'],
                    'city_id': item['city_id'],
                    'province_id': item.get('province_id'),
                    'city_rel': city.id,
                }
                if existing:
                    if not existing.subdistrict_id:
                        existing.write(values)
                        updated += 1
                else:
                    values['name'] = item['subdistrict_name']
                    subdistrict_obj.create(values)
                    created += 1
        if failures and not (created or updated):
            raise UserError(_(
                'Subdistrict sync failed for all %(count)s city/cities. First error: %(error)s'
            ) % {'count': len(failures), 'error': failures[0]})
        return self._api_notify(_('Subdistrict'), created, updated, failures)
