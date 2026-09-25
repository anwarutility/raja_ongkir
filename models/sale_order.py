from odoo import fields, models, api
from odoo.exceptions import UserError
import json
import requests
import math

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

    raja_ongkir_api = fields.Many2one(comodel_name='api.list', string='Raja Ongkir Api', ondelete='cascade')
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

    def compute_ongkir(self):
        if not self.raja_ongkir_api :
            raise UserError('Please charge the API or activate the API.')

        api_key = self.raja_ongkir_api.api_key
        api_url = self.raja_ongkir_api.api_url + "/api/cost"
        weight = self.weight_total * 1000
        courier = self.origin_courier
        if self.origin_city_type == 'city':
            if not self.raja_ongkir_api.origin_city_id:
                raise UserError('Please Set Origin City.')
            origin = self.raja_ongkir_api.origin_city_id.city_id
        elif self.origin_city_type == 'subdistrict':
            if not self.raja_ongkir_api.origin_subdistrict_id:
                raise UserError('Please Set Origin Subdistrict.')
            origin = self.raja_ongkir_api.origin_subdistrict_id.subdistrict_id

        if self.destination_city_type == 'city':
            if not self.city_id:
                raise UserError('Please Set Destination City.')
            destination = self.city_id.city_id
        elif self.destination_city_type == 'subdistrict':
            if not self.subdistrict_id:
                raise UserError('Please Set Destination Subdistrict.')
            destination = self.subdistrict_id.subdistrict_id
        try:
            headers = {
                'content-type': 'application/x-www-form-urlencoded',
                'key': api_key
            }
            data = "origin=%(origin)s&destination=%(destination)s&weight=%(weight)s&courier=%(courier)s&originType=%(originType)s&destinationType=%(destinationType)s" % {
                "origin": origin,
                "destination": destination,
                "weight": weight,
                "courier": courier,
                "originType": self.origin_city_type,
                "destinationType": self.destination_city_type
            }
            response = requests.post(api_url, headers=headers, data=data)
            compute_service_cost = {}
            parsed_response = response.json()
            if parsed_response['rajaongkir']['status']['code'] == 400:
                raise UserError(parsed_response['rajaongkir']['status']['description'])
            if parsed_response['rajaongkir']['status']['code'] == 200:
                for results in parsed_response['rajaongkir']['results']:
                    for costs in results['costs']:
                        for cost in costs['cost']:
                            if not compute_service_cost:
                                compute_service_cost['code'] = results['code']
                                compute_service_cost['name'] = results['name']
                                compute_service_cost['service'] = costs['service']
                                compute_service_cost['description'] = costs['description']
                                compute_service_cost['value'] = cost['value']
                                compute_service_cost['etd'] = cost['etd']
                                compute_service_cost['note'] = cost['note']
                            if compute_service_cost['value'] < cost['value']:
                                compute_service_cost['code'] = results['code']
                                compute_service_cost['name'] = results['name']
                                compute_service_cost['service'] = costs['service']
                                compute_service_cost['description'] = costs['description']
                                compute_service_cost['value'] = cost['value']
                                compute_service_cost['etd'] = cost['etd']
                                compute_service_cost['note'] = cost['note']
            self.courier_name = compute_service_cost['name']
            self.service_name = compute_service_cost['service']
            self.cost_delivery = compute_service_cost['value']
            self.etd = compute_service_cost['etd']
            print(json.dumps(parsed_response, indent=2))
        except json.decoder.JSONDecodeError as e:
            print("Failed to parse response as JSON:", e)
        return True

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