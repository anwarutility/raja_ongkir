# -*- coding: utf-8 -*-

import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.raja_ongkir.models.stock import courier_code, resolve_courier_code
from odoo.addons.raja_ongkir.models.sale_order import pick_service
from odoo.addons.raja_ongkir.models.ongkir_utils import (
    CITY_ENDPOINT, DISTRICT_ENDPOINT, komerce_route, ongkir_url,
)

STOCK_REQUESTS = "odoo.addons.raja_ongkir.models.stock.requests"

# Komerce answers with the courier's legal name, which never matches the
# selection labels on stock.picking.courier.
KOMERCE_JNE = [
    {"name": "Jalur Nugraha Ekakurir (JNE)", "code": "jne",
     "service": "JTR", "description": "JNE Trucking",
     "cost": 190000, "etd": "11 day"},
    {"name": "Jalur Nugraha Ekakurir (JNE)", "code": "jne",
     "service": "REG", "description": "Layanan Reguler",
     "cost": 94000, "etd": "4 day"},
]


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        if text is not None:
            self.text = text
        else:
            self.text = json.dumps(json_data if json_data is not None else {})

    def json(self):
        return json.loads(self.text)


def komerce(rows):
    return {"meta": {"message": "Success", "code": 200, "status": "success"},
            "data": rows}


class TestResolveCourierCode(TransactionCase):
    """The rate row has to map back to a `courier` selection value."""

    def test_api_code_is_authoritative(self):
        self.assertEqual(resolve_courier_code("jnt", "J&T Express"), "jnt")

    def test_komerce_trade_name_resolves_via_the_api_code(self):
        self.assertEqual(
            resolve_courier_code("jne", "Jalur Nugraha Ekakurir (JNE)"), "jne")

    def test_exact_label_still_resolves(self):
        self.assertEqual(resolve_courier_code("jne", "JNE"), "jne")
        self.assertEqual(resolve_courier_code("jnt", "J&T Express"), "jnt")
        self.assertEqual(resolve_courier_code("lion", "Lion Parcel"), "lion")

    def test_label_inside_a_longer_name_resolves(self):
        self.assertEqual(resolve_courier_code(None, "SiCepat GOKIL"), "sicepat")

    def test_name_matching_ignores_case_and_spacing(self):
        self.assertEqual(resolve_courier_code(None, "  lion   parcel "), "lion")

    def test_unknown_courier_returns_none_instead_of_a_blank(self):
        self.assertIsNone(resolve_courier_code("zebra", "Zebra Express"))
        self.assertIsNone(resolve_courier_code(None, "Zebra Express"))

    def test_missing_code_and_name_returns_none(self):
        self.assertIsNone(resolve_courier_code(None, None))


class CourierFixtures(TransactionCase):
    """Shared fixtures: a kecamatan origin/destination pair and a Komerce API
    record, plus the Sale Order / Delivery Order that use them. Subclasses add
    the assertions; this class defines no test methods of its own."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.indonesia = cls.env.ref("base.id_ID", raise_if_not_found=False) \
            or cls.env["res.country"].search([("code", "=", "ID")], limit=1)

        cls.state = cls.env["res.country.state"].create({
            "name": "Test Central Java",
            "code": "TST",
            "country_id": cls.indonesia.id,
        })
        cls.origin_city = cls.env["res.country.city"].create({
            "name": "Karanganyar",
            "province_rel": cls.state.id,
            "province_id": 10,
            "city_id": 169,
        })
        cls.origin_subdistrict = cls.env["res.city.subdistrict"].create({
            "name": "Jaten",
            "city_rel": cls.origin_city.id,
            "province_id": 10,
            "city_id": 169,
            "subdistrict_id": 2355,
        })
        cls.dest_state = cls.env["res.country.state"].create({
            "name": "Test East Java",
            "code": "TJE",
            "country_id": cls.indonesia.id,
        })
        cls.dest_city = cls.env["res.country.city"].create({
            "name": "Pasuruan",
            "province_rel": cls.dest_state.id,
            "province_id": 9,
            "city_id": 108,
        })
        cls.dest_subdistrict = cls.env["res.city.subdistrict"].create({
            "name": "Panggungrejo",
            "city_rel": cls.dest_city.id,
            "province_id": 9,
            "city_id": 108,
            "subdistrict_id": 1482,
        })

        cls.api = cls.env["api.list"].create({
            "name": "Test Komerce",
            "api_key": "unit-test-key",
            "api_url": "https://rajaongkir.komerce.id/api/v1/",
            "status": "enable",
            "origin_city_type_default": "subdistrict",
            "destination_city_type_default": "subdistrict",
            "origin_city_id": cls.origin_city.id,
            "origin_subdistrict_id": cls.origin_subdistrict.id,
            "origin_courier": "jne",
        })

        cls.partner = cls.env["res.partner"].create({
            "name": "Test Receiver",
            "city_id": cls.dest_city.id,
            "subdistrict_id": cls.dest_subdistrict.id,
        })
        cls.sale = cls.env["sale.order"].create({
            "partner_id": cls.partner.id,
            "raja_ongkir_api": cls.api.id,
            "city_id": cls.dest_city.id,
            "subdistrict_id": cls.dest_subdistrict.id,
        })
        cls.picking = cls.env["stock.picking"].create({
            "picking_type_id": cls.env.ref("stock.picking_type_out").id,
            "partner_id": cls.partner.id,
            "sale_id": cls.sale.id,
            "weight_total": 2.0,
        })


class TestCourierOnPicking(CourierFixtures):
    """Picking a rate must store a valid courier, whatever the provider calls it."""

    def _estimate(self, rows=None):
        """Run the estimate and return the ongkir.list rows it produced."""
        payload = komerce(rows if rows is not None else KOMERCE_JNE)
        with patch(STOCK_REQUESTS + ".post",
                   return_value=FakeResponse(json_data=payload)):
            self.picking.compute_estimation_ongkir()
        return self.env["ongkir.list"].search([("picking_id", "=", self.picking.id)])

    def test_estimate_stores_the_api_code_on_each_row(self):
        rows = self._estimate()
        self.assertEqual(len(rows), 2)
        self.assertEqual({r.code for r in rows}, {"jne"})

    def test_choosing_a_service_stores_the_courier(self):
        """Regression: the courier used to be left empty because the code was
        resolved from the provider's trade name."""
        rows = self._estimate()
        reg = rows.filtered(lambda r: r.service == "REG")
        reg.with_context(ongkir_mode="estimation").pilihLayanan()
        self.assertEqual(self.picking.courier, "jne")
        self.assertEqual(self.picking.service_name, "REG")
        self.assertEqual(self.picking.cost_delivery, 94000)
        self.assertEqual(self.picking.etd, "4 day")
        self.assertEqual(self.picking.courier_name,
                         "Jalur Nugraha Ekakurir (JNE)")

    def test_legacy_row_without_a_code_still_resolves_by_name(self):
        self.picking.weight_total = 2.0
        legacy = self.env["ongkir.list"].create({
            "picking_id": self.picking.id,
            "name": "JNE",
            "service": "REG",
            "value": 12000,
            "etd": "2 day",
        })
        legacy.with_context(ongkir_mode="estimation").pilihLayanan()
        self.assertEqual(self.picking.courier, "jne")
        self.assertEqual(self.picking.cost_delivery, 12000)

    def test_unknown_courier_raises_a_readable_error(self):
        unknown = self.env["ongkir.list"].create({
            "picking_id": self.picking.id,
            "code": "zebra",
            "name": "Zebra Express",
            "service": "REG",
            "value": 12000,
        })
        with self.assertRaises(UserError) as caught:
            unknown.with_context(ongkir_mode="estimation").pilihLayanan()
        self.assertIn("Zebra Express", str(caught.exception))
        self.assertFalse(self.picking.courier)

    def test_realitation_mode_is_unaffected(self):
        rows = self._estimate()
        reg = rows.filtered(lambda r: r.service == "REG")
        reg.with_context(ongkir_mode="realitation").pilihLayanan()
        self.assertEqual(self.picking.realitation_cost_delivery, 94000)
        self.assertEqual(self.picking.realitation_service_name, "REG")
        self.assertEqual(self.picking.realitation_etd, "4 day")
        # Realisation cost must not touch the estimation courier.
        self.assertFalse(self.picking.courier)

    def test_single_service_estimate_stores_the_courier_directly(self):
        self.picking.courier = "jne"
        rows = self._estimate([KOMERCE_JNE[1]])
        self.assertEqual(len(rows), 0)
        self.assertEqual(self.picking.courier, "jne")
        self.assertEqual(self.picking.cost_delivery, 94000)

    def test_getbiaya_persists_the_code_too(self):
        """getBiaya loops over every courier, so the requested code has to be
        threaded into the rows it writes as well."""

        def responder(url, **kwargs):
            asked = dict(kwargs.get("data") or {}).get("courier")
            rows = [
                {"name": "Provider Trade Name %s" % asked, "code": asked,
                 "service": "REG", "description": "Reguler",
                 "cost": 10000, "etd": "2 day"}
            ]
            return FakeResponse(json_data=komerce(rows))

        with patch(STOCK_REQUESTS + ".post", side_effect=responder):
            with patch.object(type(self.picking), "_open_ongkir_popup",
                              return_value=True):
                self.picking.getBiaya()
        rows = self.env["ongkir.list"].search([("picking_id", "=", self.picking.id)])
        self.assertEqual(len(rows), 25)
        self.assertEqual({r.code for r in rows},
                         {code for code, _label in courier_code})
        self.assertEqual(
            {r.name for r in rows},
            {"Provider Trade Name %s" % code for code, _l in courier_code})


class TestPickService(TransactionCase):
    """The preferred service wins; a route without it must not fail the button.

    The Sales Order "Compute Cost Delivery" button used to hardcode service
    REG. Komerce answers CTC (JNE City Courier) on some routes, so the button
    raised "No service returned by Raja Ongkir for courier jne" and left the
    Sales Order without a cost.
    """

    def test_preferred_service_wins(self):
        rows = [
            {"service": "CTC", "cost": 10000},
            {"service": "REG", "cost": 94000},
        ]
        self.assertEqual(pick_service(rows, "REG")["service"], "REG")

    def test_falls_back_to_the_cheapest_service_when_reg_is_absent(self):
        rows = [
            {"service": "CTC", "cost": 525000},
            {"service": "JTR", "cost": 190000},
        ]
        self.assertEqual(pick_service(rows, "REG")["service"], "JTR")

    def test_service_match_ignores_case_and_spacing(self):
        rows = [{"service": " reg ", "cost": 1}]
        self.assertEqual(pick_service(rows, "REG")["service"], " reg ")

    def test_configured_service_is_honoured(self):
        rows = [
            {"service": "REG", "cost": 94000},
            {"service": "YES", "cost": 150000},
        ]
        self.assertEqual(pick_service(rows, "yes")["service"], "YES")

    def test_empty_answer_returns_none(self):
        self.assertIsNone(pick_service([], "REG"))


class TestComputeCostDeliveryOnSaleOrder(TransactionCase):
    """The button must call the RajaOngkir API and store the returned rate."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.indonesia = cls.env.ref("base.id_ID", raise_if_not_found=False) \
            or cls.env["res.country"].search([("code", "=", "ID")], limit=1)
        cls.state = cls.env["res.country.state"].create({
            "name": "Test Origin State", "code": "TOS",
            "country_id": cls.indonesia.id,
        })
        cls.origin_city = cls.env["res.country.city"].create({
            "name": "Test Origin City", "province_rel": cls.state.id,
            "province_id": 10, "city_id": 169,
        })
        cls.origin_subdistrict = cls.env["res.city.subdistrict"].create({
            "name": "Test Origin Subdistrict", "city_rel": cls.origin_city.id,
            "province_id": 10, "city_id": 169, "subdistrict_id": 2355,
        })
        cls.dest_city = cls.env["res.country.city"].create({
            "name": "Test Destination City", "province_rel": cls.state.id,
            "province_id": 10, "city_id": 160,
        })
        cls.dest_subdistrict = cls.env["res.city.subdistrict"].create({
            "name": "Test Destination Subdistrict",
            "city_rel": cls.dest_city.id,
            "province_id": 10, "city_id": 160, "subdistrict_id": 2227,
        })
        cls.api = cls.env["api.list"].create({
            "name": "Test Raja Ongkir SO",
            "api_key": "unit-test-key",
            "api_url": "https://rajaongkir.komerce.id/api/v1/",
            "status": "enable",
            "origin_city_type_default": "subdistrict",
            "destination_city_type_default": "subdistrict",
            "origin_city_id": cls.origin_city.id,
            "origin_subdistrict_id": cls.origin_subdistrict.id,
            "origin_courier": "jne",
        })
        cls.partner = cls.env["res.partner"].create({
            "name": "Test SO Receiver",
            "city_id": cls.dest_city.id,
            "subdistrict_id": cls.dest_subdistrict.id,
        })
        cls.sale = cls.env["sale.order"].create({
            "partner_id": cls.partner.id,
            "raja_ongkir_api": cls.api.id,
            "city_id": cls.dest_city.id,
            "subdistrict_id": cls.dest_subdistrict.id,
        })

    def _compute(self, rows):
        with patch("odoo.addons.raja_ongkir.models.sale_order.requests.post",
                   return_value=FakeResponse(json_data=komerce(rows))):
            self.sale.compute_ongkir()
        return self.sale

    def test_configured_service_is_stored(self):
        sale = self._compute(KOMERCE_JNE)
        self.assertEqual(sale.service_name, "REG")
        self.assertEqual(sale.cost_delivery, 94000)
        self.assertEqual(sale.etd, "4 day")
        self.assertEqual(sale.courier_name, "Jalur Nugraha Ekakurir (JNE)")

    def test_route_without_reg_falls_back_instead_of_raising(self):
        """Regression: this exact answer raised 'No service returned'."""
        rows = [{"name": "Jalur Nugraha Ekakurir (JNE)", "code": "jne",
                 "service": "CTC", "description": "JNE City Courier",
                 "cost": 525000, "etd": "11 day"}]
        sale = self._compute(rows)
        self.assertEqual(sale.service_name, "CTC")
        self.assertEqual(sale.cost_delivery, 525000)

    def test_configured_service_overrides_reg(self):
        self.sale.raja_ongkir_api.service = "JTR"
        rows = [
            {"name": "Jalur Nugraha Ekakurir (JNE)", "code": "jne",
             "service": "REG", "description": "Reguler",
             "cost": 94000, "etd": "4 day"},
            {"name": "Jalur Nugraha Ekakurir (JNE)", "code": "jne",
             "service": "JTR", "description": "JNE Trucking",
             "cost": 190000, "etd": "11 day"},
        ]
        sale = self._compute(rows)
        self.assertEqual(sale.service_name, "JTR")
        self.assertEqual(sale.cost_delivery, 190000)

    def test_no_rate_at_all_still_raises_a_readable_error(self):
        with patch("odoo.addons.raja_ongkir.models.sale_order.requests.post",
                   return_value=FakeResponse(json_data=komerce([]))):
            with self.assertRaises(UserError) as caught:
                self.sale.compute_ongkir()
        self.assertIn("No service returned", str(caught.exception))


class TestKomerceRoute(TransactionCase):
    """Komerce prices cities and kecamatan from different id spaces.

    Sending a *city* id to the *district* endpoint is accepted by Komerce but
    prices the wrong area: Karanganyar (169) -> Jember (160) at 15 kg answered
    "CTC 525.000 / 11 day" instead of the rate for the kecamatan the order had
    actually selected ("REG 765.000 / 3 day"). The endpoint therefore has to
    follow the area type, and a mixed route must fall back to city pricing.
    """

    def test_two_kecamatan_use_the_district_endpoint_with_kecamatan_ids(self):
        origin = {'type': 'subdistrict', 'city_id': 169, 'subdistrict_id': 2355}
        destination = {'type': 'subdistrict', 'city_id': 160, 'subdistrict_id': 2227}
        self.assertEqual(
            komerce_route(origin, destination),
            (DISTRICT_ENDPOINT, 2355, 2227))

    def test_two_cities_use_the_city_endpoint_with_city_ids(self):
        origin = {'type': 'city', 'city_id': 169, 'subdistrict_id': None}
        destination = {'type': 'city', 'city_id': 160, 'subdistrict_id': None}
        self.assertEqual(
            komerce_route(origin, destination),
            (CITY_ENDPOINT, 169, 160))

    def test_mixed_route_is_demoted_to_city_pricing(self):
        """The kecamatan end is demoted to its parent city, never the reverse:
        promoting a city to an arbitrary kecamatan would invent a route."""
        origin = {'type': 'subdistrict', 'city_id': 169, 'subdistrict_id': 2355}
        destination = {'type': 'city', 'city_id': 160, 'subdistrict_id': None}
        self.assertEqual(
            komerce_route(origin, destination),
            (CITY_ENDPOINT, 169, 160))

    def test_kecamatan_without_an_id_falls_back_to_city_pricing(self):
        origin = {'type': 'subdistrict', 'city_id': 169, 'subdistrict_id': None}
        destination = {'type': 'city', 'city_id': 160, 'subdistrict_id': None}
        self.assertEqual(
            komerce_route(origin, destination),
            (CITY_ENDPOINT, 169, 160))

    def test_url_building_keeps_the_komerce_v1_base(self):
        self.assertEqual(
            ongkir_url("https://rajaongkir.komerce.id/api/v1/", DISTRICT_ENDPOINT),
            "https://rajaongkir.komerce.id/api/v1" + DISTRICT_ENDPOINT)
        self.assertEqual(
            ongkir_url("https://pro.rajaongkir.com", "/cost"),
            "https://pro.rajaongkir.com/api/cost")


class TestOngkirRouteMatchesBetweenSalesAndDelivery(CourierFixtures):
    """The Sales Order button and the Delivery Order buttons must price the
    same route: the SO path used to send city ids to the district endpoint
    while the DO path sent kecamatan ids, so the two disagreed."""

    def _fetch(self, picking, courier="jne"):
        api = picking.sale_id.raja_ongkir_api
        origin = picking._resolve_ongkir_origin()
        destination = picking._resolve_ongkir_destination()
        captured = {}

        def responder(url, **kwargs):
            captured["url"] = url
            captured["data"] = dict(kwargs.get("data") or {})
            return FakeResponse(json_data=komerce([
                {"name": "JNE", "code": courier, "service": "REG",
                 "description": "Reguler", "cost": 51000, "etd": "3 day"},
            ]))

        with patch(STOCK_REQUESTS + ".post", side_effect=responder):
            picking._fetch_ongkir_services(api, courier, origin, destination, 15000)
        return captured

    def test_delivery_order_calls_the_district_endpoint_with_kecamatan_ids(self):
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.env.ref("stock.picking_type_out").id,
            "partner_id": self.partner.id,
            "sale_id": self.sale.id,
            "weight_total": 15.0,
        })
        captured = self._fetch(picking)
        self.assertTrue(captured["url"].endswith(DISTRICT_ENDPOINT), captured["url"])
        self.assertEqual(captured["data"]["origin"], 2355)
        self.assertEqual(captured["data"]["destination"], 1482)

    def test_sales_order_button_calls_the_same_endpoint_with_the_same_ids(self):
        captured = {}

        def responder(url, **kwargs):
            captured["url"] = url
            captured["data"] = dict(kwargs.get("data") or {})
            return FakeResponse(json_data=komerce([
                {"name": "JNE", "code": "jne", "service": "REG",
                 "description": "Reguler", "cost": 765000, "etd": "3 day"},
            ]))

        so = self.env["sale.order"].create({
            "partner_id": self.partner.id,
            "raja_ongkir_api": self.api.id,
            "city_id": self.dest_city.id,
            "subdistrict_id": self.dest_subdistrict.id,
        })
        so.weight_total = 15.0
        with patch("odoo.addons.raja_ongkir.models.sale_order.requests.post",
                   side_effect=responder):
            so.compute_ongkir()
        self.assertTrue(captured["url"].endswith(DISTRICT_ENDPOINT), captured["url"])
        self.assertEqual(captured["data"]["origin"], 2355)
        self.assertEqual(captured["data"]["destination"], 1482)
        # ...and the returned REG rate is what lands on the order.
        self.assertEqual(so.service_name, "REG")
        self.assertEqual(so.cost_delivery, 765000)
