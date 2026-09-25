# -*- coding: utf-8 -*-

from odoo import models, fields

class StateCity(models.Model):
    _name = 'res.country.city'
    _description = "City"

    province_rel = fields.Many2one(comodel_name='res.country.state',string='Province', required=True)
    province_id = fields.Integer(string="Province ID")
    city_id = fields.Integer(string="City ID")
    type = fields.Char(string="Type")
    name = fields.Char(string="Name", required=True)
    postal_code = fields.Char(string="Postal Code")
