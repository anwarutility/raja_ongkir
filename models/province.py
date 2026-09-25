# -*- coding: utf-8 -*-

from odoo import models, fields

class CountryState(models.Model):
    _inherit = 'res.country.state'

    province_id = fields.Integer(string="Province ID")