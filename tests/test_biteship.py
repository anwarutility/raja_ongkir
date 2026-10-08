# -*- coding: utf-8 -*-

"""Biteship support in the raja_ongkir module.

The module keeps the same Sales Order button ("Compute Cost Delivery") and the
same Delivery Order tabs; only the provider behind them changes when
``api.list.api_url`` points at ``api.biteship.com``. All HTTP calls are mocked.
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

from odoo.addons.raja_ongkir.models.ongkir_utils import (
    biteship_area_query,
    is_biteship,
    parse_biteship_pricing,
    pick_biteship_area,
)

STOCK_REQUESTS = "odoo.addons.raja_ongkir.models.stock.requests"
UTILS_AREAS = "odoo.addons.raja_ongkir.models.ongkir_utils.biteship_search_areas"

BITESHIP_AREA_ORIGIN = "IDNP10IDNC163IDND1132IDZ57731"
BITESHIP_AREA_DEST = "IDNP11IDNC154IDND985IDZ68121"

BITESHIP_PRICING = [
    {"courier_name": "JNE", "courier_code": "jne",
     "courier_service_name": "Reguler", "courier_service_code": "reg",
     "duration": "1 - 2 days", "price": 315000},
    {"courier_name": "JNE", "courier_code": "jne",
     "courier_service_name": "JNE Trucking", "courier_service_code": "jtr",
     "duration": "5 - 6 days", "price": 82500},
]


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        if text is not None:
            self.text = text
        else:
            self.text = "{}"
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def biteship_ok(pricing=None):
    return {"success": True, "pricing": pricing if pricing is not None else BITESHIP_PRICING}


def area_row(area_id, district, city, postal):
    return {
        "id": area_id,
        "name": "%s, %s, Jawa. %s" % (district, city, postal),
        "administrative_division_level_3_name": district,
    }


class TestBiteshipHelpers(TransactionCase):
    """Provider detection, area search/pick and pricing parsing."""

    def test_provider_detection(self):
        self.assertTrue(is_biteship("https://api.biteship.com"))
        self.assertTrue(is_biteship("https://api.biteship.com/"))
        self.assertFalse(is_biteship("https://rajaongkir.komerce.id/api/v1"))
        self.assertFalse(is_biteship("https://pro.rajaongkir.com"))
        self.assertFalse(is_biteship(None))

    def test_area_query_puts_the_postal_code_first(self):
        self.assertEqual(biteship_area_query("68121", "Sumber Sari"), "Sumber Sari 68121")
        self.assertEqual(biteship_area_query("68121", None), "68121")
        self.assertEqual(biteship_area_query(None, "Gempol", "Pasuruan"), "Gempol Pasuruan")
        self.assertEqual(biteship_area_query(None, None, "Jember"), "Jember")
        self.assertEqual(biteship_area_query(None, None, None), "")

    def test_pick_area_prefers_the_exact_district(self):
        areas = [
            area_row("A", "Jelimpo", "Landak", "79357"),
            area_row("B", "Ngabang", "Landak", "79357"),
        ]
        self.assertEqual(
            pick_biteship_area(areas, "79357", "Ngabang")["id"], "B")

    def test_pick_area_accepts_a_unique_postal_code(self):
        areas = [area_row("A", "Gempol", "Pasuruan", "67155")]
        self.assertEqual(pick_biteship_area(areas, "67155", None)["id"], "A")

    def test_pick_area_rejects_an_ambiguous_postal_code(self):
        """One postal code can span several kecamatan: never guess."""
        areas = [
            area_row("A", "Jaten", "Karanganyar", "57731"),
            area_row("B", "Ngargoyoso", "Karanganyar", "57731"),
        ]
        self.assertIsNone(pick_biteship_area(areas, "57731", None))

    def test_pick_area_rejects_a_city_only_hit(self):
        areas = [area_row("A", "Jaten", "Karanganyar", "57731")]
        self.assertIsNone(pick_biteship_area(areas, None, None))

    def test_parse_pricing_maps_biteship_rows(self):
        parsed = parse_biteship_pricing(BITESHIP_PRICING)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["code"], "jne")
        self.assertEqual(parsed[0]["service"], "Reguler")
        self.assertEqual(parsed[0]["value"], 315000.0)
        self.assertEqual(parsed[0]["etd"], "1 - 2 days")

    def test_parse_pricing_skips_malformed_rows(self):
        self.assertEqual(parse_biteship_pricing(None), [])
        parsed = parse_biteship_pricing([None, "jne", {"courier_code": "jnt", "price": "x"}])
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["code"], "jnt")
        self.assertEqual(parsed[0]["value"], 0.0)


class TestBiteshipOnSalesOrder(TransactionCase):
    """The "Compute Cost Delivery" button must quote Biteship rates."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.indonesia = cls.env.ref("base.id_ID", raise_if_not_found=False) \
            or cls.env["res.country"].search([("code", "=", "ID")], limit=1)
        cls.state = cls.env["res.country.state"].create({
            "name": "Test Biteship State", "code": "TBS",
            "country_id": cls.indonesia.id,
        })
        cls.origin_city = cls.env["res.country.city"].create({
            "name": "Karanganyar", "province_rel": cls.state.id,
            "province_id": 10, "city_id": 169, "postal_code": "57731",
        })
        cls.origin_sub = cls.env["res.city.subdistrict"].create({
            "name": "Jaten", "city_rel": cls.origin_city.id,
            "province_id": 10, "city_id": 169, "subdistrict_id": 2355,
        })
        cls.dest_city = cls.env["res.country.city"].create({
            "name": "Jember", "province_rel": cls.state.id,
            "province_id": 9, "city_id": 160, "postal_code": "68121",
        })
        cls.dest_sub = cls.env["res.city.subdistrict"].create({
            "name": "Sumber Sari", "city_rel": cls.dest_city.id,
            "province_id": 9, "city_id": 160, "subdistrict_id": 2227,
        })
        cls.api = cls.env["api.list"].create({
            "name": "Test Biteship",
            "api_key": "biteship_test.KEY",
            "api_url": "https://api.biteship.com",
            "status": "enable",
            "origin_city_type_default": "subdistrict",
            "destination_city_type_default": "subdistrict",
            "origin_city_id": cls.origin_city.id,
            "origin_subdistrict_id": cls.origin_sub.id,
            "origin_courier": "jne",
            "service": "REG",
        })
        cls.partner = cls.env["res.partner"].create({
            "name": "Test Biteship Customer",
            "city_id": cls.dest_city.id,
            "subdistrict_id": cls.dest_sub.id,
        })
        cls.sale = cls.env["sale.order"].create({
            "partner_id": cls.partner.id,
            "raja_ongkir_api": cls.api.id,
            "city_id": cls.dest_city.id,
            "subdistrict_id": cls.dest_sub.id,
        })

    def setUp(self):
        super().setUp()
        # RajaOngkir's weight_total is a computed field when that module's
        # dependency chain recomputes it, so pin it per test.
        self.sale.weight_total = 15.0

    def _areas_responder(self, url, **kwargs):
        """Answer /v1/maps/areas: origin and destination each resolve cleanly."""
        params = kwargs.get("params") or {}
        query = str(params.get("input") or "")
        if "Jaten" in query or "57731" in query:
            return FakeResponse(json_data={"success": True, "areas": [
                area_row(BITESHIP_AREA_ORIGIN, "Jaten", "Karanganyar", "57731")]})
        return FakeResponse(json_data={"success": True, "areas": [
            area_row(BITESHIP_AREA_DEST, "Sumber Sari", "Jember", "68121")]})

    def test_button_calls_biteship_and_stores_the_rate(self):
        captured = {}

        def rates_responder(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            captured["headers"] = kwargs.get("headers")
            return FakeResponse(json_data=biteship_ok())

        with patch(STOCK_REQUESTS + ".get", side_effect=self._areas_responder), \
                patch(STOCK_REQUESTS + ".post", side_effect=rates_responder):
            result = self.sale.compute_ongkir()

        self.assertTrue(result)
        self.assertTrue(captured["url"].endswith("/v1/rates/couriers"))
        # The API key travels in Authorization, NOT in the body.
        self.assertEqual(captured["headers"]["Authorization"], "biteship_test.KEY")
        self.assertNotIn("key", captured["json"])
        self.assertEqual(captured["json"]["origin_area_id"], BITESHIP_AREA_ORIGIN)
        self.assertEqual(captured["json"]["destination_area_id"], BITESHIP_AREA_DEST)
        self.assertEqual(captured["json"]["items"][0]["weight"], 15000)
        # "REG" is the configured service, so the REG row wins over the cheaper
        # JTR row (which pick_service would otherwise fall back to).
        self.assertEqual(self.sale.service_name, "Reguler")
        self.assertEqual(self.sale.cost_delivery, 315000)
        self.assertEqual(self.sale.etd, "1 - 2 days")
        self.assertEqual(self.sale.courier_name, "JNE")

    def test_biteship_route_does_not_need_rajaongkir_ids(self):
        """Biteship prices by area_id; the RajaOngkir ids must not be sent."""
        captured = {}

        def rates_responder(url, **kwargs):
            captured["json"] = kwargs.get("json")
            return FakeResponse(json_data=biteship_ok())

        with patch(STOCK_REQUESTS + ".get", side_effect=self._areas_responder), \
                patch(STOCK_REQUESTS + ".post", side_effect=rates_responder):
            self.sale.compute_ongkir()
        payload = captured["json"]
        self.assertNotIn("origin", payload)
        self.assertNotIn("destination", payload)
        self.assertNotIn("courier", payload)

    def test_area_id_is_cached_on_the_master_record(self):
        self.assertFalse(self.origin_sub.biteship_area_id)
        self.assertFalse(self.dest_sub.biteship_area_id)
        with patch(STOCK_REQUESTS + ".get", side_effect=self._areas_responder), \
                patch(STOCK_REQUESTS + ".post",
                      return_value=FakeResponse(json_data=biteship_ok())):
            self.sale.compute_ongkir()
        self.assertEqual(self.origin_sub.biteship_area_id, BITESHIP_AREA_ORIGIN)
        self.assertEqual(self.dest_sub.biteship_area_id, BITESHIP_AREA_DEST)

    def test_second_run_reuses_the_cached_area_without_searching(self):
        with patch(STOCK_REQUESTS + ".get", side_effect=self._areas_responder), \
                patch(STOCK_REQUESTS + ".post",
                      return_value=FakeResponse(json_data=biteship_ok())):
            self.sale.compute_ongkir()
        # A second run must not hit /v1/maps/areas again.
        with patch(STOCK_REQUESTS + ".get",
                   side_effect=AssertionError("area search should be cached")), \
                patch(STOCK_REQUESTS + ".post",
                      return_value=FakeResponse(json_data=biteship_ok())):
            self.sale.compute_ongkir()
        self.assertEqual(self.sale.cost_delivery, 315000)

    def test_unmappable_destination_is_refused_not_guessed(self):
        def ambiguous_areas(url, **kwargs):
            params = kwargs.get("params") or {}
            query = str(params.get("input") or "")
            if "Jaten" in query or "57731" in query:
                return FakeResponse(json_data={"success": True, "areas": [
                    area_row(BITESHIP_AREA_ORIGIN, "Jaten", "Karanganyar", "57731")]})
            # Two kecamatan share the postal code and neither is the one the
            # customer picked, so the zone cannot be determined.
            return FakeResponse(json_data={"success": True, "areas": [
                area_row("X", "Sukorambi", "Jember", "68121"),
                area_row("Y", "Ajung", "Jember", "68121"),
            ]})

        with patch(STOCK_REQUESTS + ".get", side_effect=ambiguous_areas), \
                patch(STOCK_REQUESTS + ".post",
                      return_value=FakeResponse(json_data=biteship_ok())):
            with self.assertRaises(UserError) as caught:
                self.sale.compute_ongkir()
        self.assertIn("Biteship", str(caught.exception))
        self.assertEqual(self.sale.cost_delivery, 0)

    def test_auth_failure_surfaces_a_readable_error(self):
        with patch(STOCK_REQUESTS + ".get", side_effect=self._areas_responder), \
                patch(STOCK_REQUESTS + ".post",
                      return_value=FakeResponse(status_code=401, json_data={})):
            with self.assertRaises(UserError) as caught:
                self.sale.compute_ongkir()
        self.assertIn("Autentikasi Biteship", str(caught.exception))

    def test_api_error_message_is_surfaced(self):
        with patch(STOCK_REQUESTS + ".get", side_effect=self._areas_responder), \
                patch(STOCK_REQUESTS + ".post", return_value=FakeResponse(
                    json_data={"success": False, "error": "courier not supported"})):
            with self.assertRaises(UserError) as caught:
                self.sale.compute_ongkir()
        self.assertIn("courier not supported", str(caught.exception))

    def test_no_pricing_falls_back_to_a_clear_error(self):
        with patch(STOCK_REQUESTS + ".get", side_effect=self._areas_responder), \
                patch(STOCK_REQUESTS + ".post",
                      return_value=FakeResponse(json_data={"success": True, "pricing": []})):
            with self.assertRaises(UserError) as caught:
                self.sale.compute_ongkir()
        self.assertIn("No service returned", str(caught.exception))


class TestBiteshipOnDeliveryOrder(TransactionCase):
    """The Delivery Order buttons must use Biteship too, in one call."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.indonesia = cls.env.ref("base.id_ID", raise_if_not_found=False) \
            or cls.env["res.country"].search([("code", "=", "ID")], limit=1)
        cls.state = cls.env["res.country.state"].create({
            "name": "Test DO State", "code": "TDS",
            "country_id": cls.indonesia.id,
        })
        cls.origin_city = cls.env["res.country.city"].create({
            "name": "Karanganyar", "province_rel": cls.state.id,
            "province_id": 10, "city_id": 169, "postal_code": "57731",
            "biteship_area_id": BITESHIP_AREA_ORIGIN,
        })
        cls.origin_sub = cls.env["res.city.subdistrict"].create({
            "name": "Jaten", "city_rel": cls.origin_city.id,
            "province_id": 10, "city_id": 169, "subdistrict_id": 2355,
            "biteship_area_id": BITESHIP_AREA_ORIGIN,
        })
        cls.dest_city = cls.env["res.country.city"].create({
            "name": "Jember", "province_rel": cls.state.id,
            "province_id": 9, "city_id": 160, "postal_code": "68121",
        })
        cls.dest_sub = cls.env["res.city.subdistrict"].create({
            "name": "Sumber Sari", "city_rel": cls.dest_city.id,
            "province_id": 9, "city_id": 160, "subdistrict_id": 2227,
            "biteship_area_id": BITESHIP_AREA_DEST,
        })
        cls.api = cls.env["api.list"].create({
            "name": "Test Biteship DO",
            "api_key": "biteship_test.KEY",
            "api_url": "https://api.biteship.com",
            "status": "enable",
            "origin_city_type_default": "subdistrict",
            "destination_city_type_default": "subdistrict",
            "origin_city_id": cls.origin_city.id,
            "origin_subdistrict_id": cls.origin_sub.id,
            "origin_courier": "jne",
        })
        cls.partner = cls.env["res.partner"].create({
            "name": "Test DO Customer",
            "city_id": cls.dest_city.id,
            "subdistrict_id": cls.dest_sub.id,
        })
        cls.sale = cls.env["sale.order"].create({
            "partner_id": cls.partner.id,
            "raja_ongkir_api": cls.api.id,
            "city_id": cls.dest_city.id,
            "subdistrict_id": cls.dest_sub.id,
        })
        cls.picking = cls.env["stock.picking"].create({
            "picking_type_id": cls.env.ref("stock.picking_type_out").id,
            "partner_id": cls.partner.id,
            "sale_id": cls.sale.id,
            "weight_total": 15.0,
        })

    def test_estimate_uses_biteship_and_fills_the_estimation_group(self):
        captured = {}

        def rates_responder(url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            return FakeResponse(json_data=biteship_ok())

        with patch(STOCK_REQUESTS + ".post", side_effect=rates_responder):
            self.picking.compute_estimation_ongkir()
        self.assertTrue(captured["url"].endswith("/v1/rates/couriers"))
        self.assertEqual(captured["json"]["items"][0]["weight"], 15000)
        # Two Biteship services -> the popup lists them for the user to pick.
        rows = self.env["ongkir.list"].search([("picking_id", "=", self.picking.id)])
        self.assertEqual(len(rows), 2)
        self.assertEqual({r.service for r in rows}, {"Reguler", "JNE Trucking"})

    def test_getbiaya_makes_a_single_request_for_all_couriers(self):
        """Biteship answers every courier at once: 20 calls would burn quota."""
        calls = []

        def rates_responder(url, **kwargs):
            calls.append(kwargs.get("json"))
            return FakeResponse(json_data=biteship_ok())

        with patch(STOCK_REQUESTS + ".post", side_effect=rates_responder), \
                patch.object(type(self.picking), "_open_ongkir_popup",
                             return_value=True):
            self.picking.getBiaya()
        self.assertEqual(len(calls), 1)
        self.assertIn("jne", calls[0]["couriers"])
        self.assertIn("sicepat", calls[0]["couriers"])

    def test_sales_order_estimate_asks_only_for_the_configured_courier(self):
        """Several couriers name their regular service "Reguler", so the Sales
        Order must ask for one courier instead of picking across them."""
        captured = {}

        def rates_responder(url, **kwargs):
            captured["json"] = kwargs.get("json")
            return FakeResponse(json_data=biteship_ok())

        with patch(STOCK_REQUESTS + ".post", side_effect=rates_responder):
            self.picking.compute_estimation_ongkir()
        self.assertEqual(captured["json"]["couriers"], "jne")

    def test_estimation_stores_the_returned_courier_code(self):
        with patch(STOCK_REQUESTS + ".post",
                   return_value=FakeResponse(json_data=biteship_ok([
                       {"courier_name": "Jalur Nugraha Ekakurir (JNE)",
                        "courier_code": "jne", "courier_service_name": "Reguler",
                        "courier_service_code": "reg",
                        "duration": "1 - 2 days", "price": 315000}]))):
            self.picking.compute_estimation_ongkir()
        # Single service -> stored directly, with the code mapped back.
        self.assertEqual(self.picking.courier, "jne")
        self.assertEqual(self.picking.cost_delivery, 315000)
