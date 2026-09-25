# -*- coding: utf-8 -*-

import requests
import json
from odoo import models, fields, api
from odoo.exceptions import UserError

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
    origin_courier = fields.Selection(string='Origin Courier', selection=courier_code)
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

    def _api_url(self, path):
        """Build the endpoint URL, tolerating both the default RajaOngkir
        layout (``https://pro.rajaongkir.com/api``) and full bases such as
        ``https://rajaongkir.komerce.id/api/v1``."""
        base = (self.api_url or 'https://pro.rajaongkir.com').strip().rstrip('/')
        if not base.endswith('/api/v1') and not base.endswith('/api'):
            base += '/api'
        return base + path

    def sync_province(self):
        if not self.status or not self.api_key:
            raise UserError('Please charge the API or activate the API.')
        try:
            url = self._api_url("/province")
            headers = {'content-type': 'application/json','key': self.api_key}
            data = {}
            response = requests.get(url, headers=headers,data=json.dumps(data)).json()
            if response['rajaongkir'] and 'results' in response['rajaongkir']:
                for results in response['rajaongkir']['results']:
                    print(results['province'])
                    province_obj = self.env['res.country.state']
                    country_obj = self.env['res.country']
                    get_province = province_obj.search(['|', ('province_id','=', results['province_id']), ('name','=', results['province'])])
                    get_country = country_obj.search([('name','=', 'Indonesia')], limit=1)
                    if get_province:
                        for province in get_province:
                            if not province.province_id:
                                province.write({
                                    'province_id': results['province_id'],
                                    'code': results['province_id'],
                                })
                    else:
                        province_obj.create({
                            'province_id': results['province_id'],
                            'code': results['province_id'],
                            'name': results['province'],
                            'country_id': get_country.id
                        })
            else:
                raise UserError('Province synchronization failed. Make sure the api key and api url are correct.')
        except requests.exceptions.Timeout as e:
            print("Timeout Error:", e)
        except requests.exceptions.HTTPError as e:
            print("Http Error:", e)
        except requests.exceptions.ConnectionError as e:
            print("Error Connecting:", e)
        except requests.exceptions.RequestException as e:
            print("OOps: Something Else", e)

    def sync_city(self):
        if not self.status or not self.api_key:
            raise UserError('Please charge the API or activate the API.')
        province_obj = self.env['res.country.state']
        city_obj = self.env['res.country.city']
        province_data = province_obj.search([('province_id', '!=', False)])
        if not province_data:
            self.sync_province()
        for province in province_data:
            if province.province_id:
                try:
                    url = self._api_url("/city?province=%s" % (province.province_id))
                    headers = {'content-type': 'application/json','key': self.api_key}
                    data = {}
                    response = requests.get(url, headers=headers,data=json.dumps(data)).json()
                    if response['rajaongkir'] and 'results' in response['rajaongkir']:
                        for results in response['rajaongkir']['results']:
                            print(results['city_name'])
                            get_city = city_obj.search(['|', ('city_id', '=', results['city_id']), ('name', '=', results['city_name'])])
                            if get_city:
                                for city in get_city:
                                    if not city.city_id:
                                        city.write({
                                            'city_id': results['city_id'],
                                            'province_id': results['province_id'],
                                            'province_rel': province.id,
                                            'type': results['type'],
                                            'postal_code': results['postal_code']
                                        })
                            else:
                                city_obj.create({
                                    'city_id': results['city_id'],
                                    'province_id': results['province_id'],
                                    'province_rel': province.id,
                                    'type': results['type'],
                                    'name': results['city_name'],
                                    'postal_code': results['postal_code'],
                                })
                    else:
                        raise UserError('City synchronization failed. Make sure api key and api url are correct.')
                except requests.exceptions.Timeout as e:
                    print("Timeout Error:", e)
                except requests.exceptions.HTTPError as e:
                    print("Http Error:", e)
                except requests.exceptions.ConnectionError as e:
                    print("Error Connecting:", e)
                except requests.exceptions.RequestException as err:
                    print("OOps: Something Else", e)

    def sync_subdistrict(self):
        if not self.status or not self.api_key:
            raise UserError('Please charge the API or activate the API.')

        city_obj = self.env['res.country.city']
        subdistrict_obj = self.env['res.city.subdistrict']
        city_data = city_obj.search([('city_id', '!=', False)])
        if not city_data:
            self.sync_city()
        for city in city_data:
            if city.city_id:
                try:
                    url = self._api_url("/subdistrict?city=%s" % (city.city_id))
                    headers = {'content-type': 'application/json','key': self.api_key}
                    data = {}
                    response = requests.get(url, headers=headers,data=json.dumps(data)).json()
                    if response['rajaongkir'] and 'results' in response['rajaongkir']:
                        for results in response['rajaongkir']['results']:
                            print(results['subdistrict_name'])
                            get_subdistrict = subdistrict_obj.search(['|', ('subdistrict_id','=', results['subdistrict_id']), ('name','=', results['subdistrict_name'])])
                            if get_subdistrict:
                                for subdistrict in get_subdistrict:
                                    if not subdistrict.subdistrict_id:
                                        subdistrict.write({
                                            'subdistrict_id': results['subdistrict_id'],
                                            'city_id': results['city_id'],
                                            'province_id': results['province_id'],
                                            'city_rel': city.id
                                        })
                            else:
                                subdistrict_obj.create({
                                    'subdistrict_id': results['subdistrict_id'],
                                    'city_id': results['city_id'],
                                    'province_id': results['province_id'],
                                    'city_rel': city.id,
                                    'name': results['subdistrict_name'],
                                })
                    else:
                        raise UserError('Subdistrict synchronization failed. Make sure the api key and api url are correct.')
                except requests.exceptions.Timeout as e:
                    print("Timeout Error:", e)
                except requests.exceptions.HTTPError as e:
                    print("Http Error:", e)
                except requests.exceptions.ConnectionError as e:
                    print("Error Connecting:", e)
                except requests.exceptions.RequestException as err:
                    print("OOps: Something Else", e)