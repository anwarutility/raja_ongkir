from odoo import fields, models, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def get_current_city(self):
        for rec in self:
            get_city = self.env['res.country.city'].search([('name', '=', rec.city)], limit=1)
            for city in get_city:
                rec.city_id = city.id
            if not get_city:
                rec.city_id = False

    city_id = fields.Many2one(comodel_name='res.country.city', string='City')
    subdistrict_id = fields.Many2one(comodel_name='res.city.subdistrict', string='Kecamatan')

