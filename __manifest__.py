# -*- coding: utf-8 -*-
{
    'name': "Biteship",
    'summary': """
        Cek ongkos kirim.""",
    'description': """
        Cek biaya kirim dari Sales Order dan Delivery Order.

        Provider dipilih dari field "API Url" pada konfigurasi:
        Biteship (api.biteship.com), RajaOngkir (pro.rajaongkir.com),
        atau Komerce (rajaongkir.komerce.id).
    """,
    'author': "Legian Wahyu P",
    'website': "",
    'category': 'Inventory',
    'version': '16.0.1.1.0',
    'depends': ['base', 'stock', 'sale', 'sale_stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/api.xml',
        # 'views/stock.xml',
        'views/province.xml',
        'views/city.xml',
        'views/subdistrict.xml',
        'views/partner.xml',
        'views/sale_order.xml',
        'views/stock.xml',
        # 'views/cek.xml',
        # 'views/tracking.xml',
        # 'views/inc_tracking.xml',
    ],
    'installable': True,
    'auto_install': False,
    "application": False,
}
