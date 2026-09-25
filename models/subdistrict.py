from odoo import fields, models, api


class CitySubdistrict (models.Model):
    _name = 'res.city.subdistrict'
    _description = 'Subdistrict'

    city_rel = fields.Many2one(comodel_name='res.country.city', string='City', required=True)
    province_id = fields.Integer(string="Province ID")
    city_id = fields.Integer(string="City ID")
    subdistrict_id = fields.Integer(string="Subdistrict ID")
    name = fields.Char(string="Name", required=True)
    


