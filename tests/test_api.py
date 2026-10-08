# -*- coding: utf-8 -*-

import json
from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase

REQUESTS = "odoo.addons.raja_ongkir.models.api.requests"


class FakeResponse:
    def __init__(self, status_code=200, text=None, json_data=None):
        self.status_code = status_code
        if json_data is not None:
            text = json.dumps(json_data)
        self.text = text or ""

    def json(self):
        return json.loads(self.text)


def rajaongkir(results, status=None):
    return {"rajaongkir": {
        "status": {"code": status or 200, "description": "OK"},
        "results": results,
    }}


class TestRajaOngkirApiClient(TransactionCase):
    """The reference-data client must explain failures instead of crashing."""

    def setUp(self):
        super().setUp()
        self.api = self.env["api.list"].create({
            "name": "Test Raja Ongkir",
            "api_key": "unit-test-key",
            "api_url": "https://rajaongkir.komerce.id/api/v1/",
            "status": "enable",
        })
        # Looked up by name exactly like Api._api_country() does, rather than
        # by xmlid: the Indonesia country record is not guaranteed to carry a
        # stable external id in every database.
        self.indonesia = self.env["res.country"].search(
            [("name", "=", "Indonesia")], limit=1)

    def _city_responder(self, payload, province):
        """Answer /city?province=N per province so each province sees its own
        cities, instead of the same list for all of them.

        The province is parsed out of the query string rather than substring
        matched: "province=1" is a substring of "province=10".
        """
        def responder(url, **kwargs):
            query = url.partition("?")[2]
            asked = dict(
                part.split("=", 1) for part in query.split("&") if "=" in part
            ).get("province")
            if asked == str(province.province_id):
                return FakeResponse(200, json_data=payload)
            return FakeResponse(200, json_data=rajaongkir([]))
        return responder

    # ------------------------------------------------------------------ urls

    def test_api_url_normalises_both_layouts(self):
        self.api.api_url = "https://pro.rajaongkir.com"
        self.assertEqual(self.api._api_url("/province"),
                         "https://pro.rajaongkir.com/api/province")
        self.api.api_url = "https://rajaongkir.komerce.id/api/v1/"
        self.assertEqual(self.api._api_url("/province"),
                         "https://rajaongkir.komerce.id/api/v1/province")

    def test_api_url_tolerates_trailing_slash(self):
        self.api.api_url = "https://pro.rajaongkir.com/api/v1///"
        self.assertEqual(self.api._api_url("/city?province=1"),
                         "https://pro.rajaongkir.com/api/v1/city?province=1")

    # ------------------------------------------------------- error reporting

    def test_plain_text_404_becomes_readable_user_error(self):
        """Komerce answers '404 page not found' -- not JSON."""
        with patch(REQUESTS + ".get",
                   return_value=FakeResponse(404, "404 page not found")):
            with self.assertRaises(UserError) as cm:
                self.api._api_get_json("/city?province=6")
        message = cm.exception.args[0]
        self.assertIn("komerce.id", message)
        self.assertIn("pro.rajaongkir.com", message)
        self.assertNotIn("JSONDecodeError", message)

    def test_html_body_becomes_readable_user_error(self):
        with patch(REQUESTS + ".get",
                   return_value=FakeResponse(502, "<html>Bad Gateway</html>")):
            with self.assertRaises(UserError) as cm:
                self.api._api_get_json("/city?province=6")
        self.assertIn("did not return JSON", cm.exception.args[0])
        self.assertIn("Bad Gateway", cm.exception.args[0])

    def test_timeout_becomes_user_error(self):
        with patch(REQUESTS + ".get",
                   side_effect=requests.exceptions.Timeout()):
            with self.assertRaises(UserError) as cm:
                self.api._api_get_json("/province")
        self.assertIn("did not answer", cm.exception.args[0])

    def test_connection_error_becomes_user_error(self):
        with patch(REQUESTS + ".get",
                   side_effect=requests.exceptions.ConnectionError()):
            with self.assertRaises(UserError) as cm:
                self.api._api_get_json("/province")
        self.assertIn("Could not connect", cm.exception.args[0])

    def test_empty_body_becomes_user_error(self):
        with patch(REQUESTS + ".get", return_value=FakeResponse(200, "")):
            with self.assertRaises(UserError) as cm:
                self.api._api_get_json("/province")
        self.assertIn("empty response", cm.exception.args[0])

    def test_missing_results_key_is_reported(self):
        with patch(REQUESTS + ".get", return_value=FakeResponse(
                200, json_data={"rajaongkir": {"status": {"code": 400}}})):
            with self.assertRaises(UserError) as cm:
                self.api._api_results("/province")
        self.assertIn("result list", cm.exception.args[0])

    def test_get_is_sent_without_a_request_body(self):
        """A GET carrying a JSON body confuses strict proxies."""
        with patch(REQUESTS + ".get",
                   return_value=FakeResponse(200, json_data=rajaongkir([]))) as get:
            self.api._api_results("/province")
        self.assertNotIn("data", get.call_args.kwargs)
        self.assertEqual(get.call_args.kwargs["timeout"], 30)

    # ----------------------------------------------------------------- sync

    def test_sync_city_on_unsupported_provider_does_not_crash(self):
        """The reported bug: RPC_ERROR + UnboundLocalError on 'Sync City'."""
        state = self.env["res.country.state"].create({
            "name": "Sync Test Province",
            "code": "99",
            "province_id": 99,
            "country_id": self.indonesia.id,
        })
        with patch(REQUESTS + ".get",
                   return_value=FakeResponse(404, "404 page not found")):
            with self.assertRaises(UserError) as cm:
                self.api.sync_city()
        # The point of the test: a readable UserError, not an
        # UnboundLocalError/JSONDecodeError traceback out of the except block.
        self.assertNotIsInstance(cm.exception, UnboundLocalError)
        self.assertIn("does not publish", cm.exception.args[0])
        self.assertIn("pro.rajaongkir.com", cm.exception.args[0])

    def test_sync_province_requires_enabled_api(self):
        self.api.status = "disable"
        with self.assertRaises(UserError):
            self.api.sync_province()
        with self.assertRaises(UserError):
            self.api.sync_city()

    def test_sync_province_creates_missing_states(self):
        payload = rajaongkir([
            {"province_id": 11, "province": "ZZ Sync Province"},
        ])
        with patch(REQUESTS + ".get",
                   return_value=FakeResponse(200, json_data=payload)):
            action = self.api.sync_province()
        state = self.env["res.country.state"].search(
            [("province_id", "=", 11)], limit=1)
        self.assertTrue(state)
        self.assertEqual(state.country_id, self.indonesia)
        self.assertEqual(action["params"]["type"], "success")

    def test_sync_province_does_not_hijack_a_foreign_state(self):
        """A same-named state of another country must keep its own identity."""
        foreign = self.env["res.country.state"].search(
            [("country_id", "!=", self.indonesia.id)], limit=1)
        payload = rajaongkir([
            {"province_id": 12, "province": foreign.name},
        ])
        with patch(REQUESTS + ".get",
                   return_value=FakeResponse(200, json_data=payload)):
            self.api.sync_province()
        foreign.invalidate_recordset()
        self.assertFalse(foreign.province_id,
                         "a foreign state was given an Indonesian province id")
        self.assertEqual(
            self.env["res.country.state"].search_count(
                [("province_id", "=", 12), ("country_id", "=", self.indonesia.id)]),
            1)

    def test_sync_city_imports_and_is_idempotent(self):
        province = self.env["res.country.state"].search(
            [("province_id", "!=", False)], limit=1)
        payload = rajaongkir([
            {"city_id": 900001, "city_name": "ZZ Sync City",
             "province_id": province.province_id, "type": "Kabupaten",
             "postal_code": "99991"},
        ])
        responder = self._city_responder(payload, province)
        with patch(REQUESTS + ".get", side_effect=responder):
            self.api.sync_city()
            first = self.env["res.country.city"].search(
                [("city_id", "=", 900001)], limit=1)
            self.assertTrue(first)
            self.assertEqual(first.province_rel, province)
            # Running twice must update, never duplicate.
            self.api.sync_city()
        self.assertEqual(
            self.env["res.country.city"].search_count([("city_id", "=", 900001)]), 1)

    def test_same_city_name_in_another_province_is_not_hijacked(self):
        """A bare name match used to relink another province's city."""
        provinces = self.env["res.country.state"].search(
            [("province_id", "!=", False)], limit=2)
        other, target = provinces[0], provinces[1]
        same_name = self.env["res.country.city"].create({
            "name": "ZZ Shared Name",
            "province_rel": target.id,
        })
        payload = rajaongkir([
            {"city_id": 900002, "city_name": "ZZ Shared Name",
             "province_id": other.province_id, "type": "Kabupaten",
             "postal_code": "99992"},
        ])
        responder = self._city_responder(payload, other)
        with patch(REQUESTS + ".get", side_effect=responder):
            self.api.sync_city()
        same_name.invalidate_recordset()
        self.assertFalse(same_name.city_id,
                         "the other province's city was overwritten")
        self.assertEqual(same_name.province_rel, target)
        created = self.env["res.country.city"].search(
            [("city_id", "=", 900002)], limit=1)
        self.assertEqual(created.province_rel, other)
        self.assertNotEqual(created, same_name)

    def test_partial_failure_warns_instead_of_rolling_back(self):
        province = self.env["res.country.state"].search(
            [("province_id", "!=", False)], limit=1)
        good = rajaongkir([
            {"city_id": 900003, "city_name": "ZZ Partial City",
             "province_id": province.province_id, "type": "Kabupaten",
             "postal_code": "99993"},
        ])
        failed_once = []

        def responder(url, **kwargs):
            query = url.partition("?")[2]
            asked = dict(
                part.split("=", 1) for part in query.split("&") if "=" in part
            ).get("province")
            if asked == str(province.province_id):
                return FakeResponse(200, json_data=good)
            if not failed_once:
                failed_once.append(url)
                return FakeResponse(500, "upstream exploded")
            return FakeResponse(200, json_data=rajaongkir([]))

        with patch(REQUESTS + ".get", side_effect=responder):
            action = self.api.sync_city()
        self.assertEqual(action["params"]["type"], "warning")
        self.assertTrue(failed_once, "no failure was simulated")
        self.assertIn("upstream exploded", action["params"]["message"])
        self.assertTrue(
            self.env["res.country.city"].search_count([("city_id", "=", 900003)]),
            "the city that did sync was rolled back")

    def test_unsupported_endpoint_stops_after_the_first_request(self):
        """A 404 must not be retried against every remaining province."""
        province = self.env["res.country.state"].search(
            [("province_id", "!=", False)], limit=1)
        with patch(REQUESTS + ".get",
                   return_value=FakeResponse(404, "404 page not found")) as get:
            with self.assertRaises(UserError):
                self.api.sync_city()
        self.assertEqual(
            get.call_count, 1,
            "the run kept asking provinces that cannot work either")
