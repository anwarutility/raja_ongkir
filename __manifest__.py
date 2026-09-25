# -*- coding: utf-8 -*-
{
    'name': "Raja Ongkir",
    'summary': """
        Cek ongkos kirim.""",
    'description': """
        Module untuk mengecek biaya kirim pada suatu kabupaten/kota.
    """,
    'author': "Legian Wahyu P",
    'website': "",
    'category': 'Inventory',
    'version': '0.5',
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
