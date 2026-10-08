# -*- coding: utf-8 -*-

from odoo import fields, models


class CitySubdistrict (models.Model):
    _name = 'res.city.subdistrict'
    _description = 'Subdistrict'

    city_rel = fields.Many2one(comodel_name='res.country.city', string='City', required=True)
    province_id = fields.Integer(string="Province ID")
    city_id = fields.Integer(string="City ID")
    subdistrict_id = fields.Integer(string="Subdistrict ID")
    name = fields.Char(string="Name", required=True)
    biteship_area_id = fields.Char(
        string="Biteship Area ID",
        help="Biteship area_id for this kecamatan, resolved on demand when the "
             "API record points at Biteship (api.biteship.com). Biteship prices "
             "routes by area_id, not by RajaOngkir subdistrict ids.")
