# -*- coding: utf-8 -*-
"""Shared request helpers for the rate providers.

Both the Sales Order button (``sale.order.compute_ongkir``) and the Delivery
Order buttons (``stock.picking.compute_estimation_ongkir`` / ``getBiaya``) talk
to the same provider. The URL building and -- more importantly -- the provider
specific quirks live here instead of being duplicated in two models.

Two providers are supported, detected from the configured ``api_url``:

* **Biteship** (``api.biteship.com``) -- ``POST /v1/rates/couriers``. Rates come
  from the couriers themselves, so they match the official tariff (JNE REG
  Jaten->Jember 15 kg = Rp315.000 / 1-2 days).
* **RajaOngkir / Komerce** -- the classic ``/api/cost`` and Komerce's
  ``/calculate/...`` layouts.
"""

import requests

CITY_ENDPOINT = '/calculate/domestic-cost'
DISTRICT_ENDPOINT = '/calculate/district/domestic-cost'

BITESHIP_DEFAULT_URL = 'https://api.biteship.com'
BITESHIP_RATES_PATH = '/v1/rates/couriers'
BITESHIP_AREAS_PATH = '/v1/maps/areas'


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

def is_komerce(api_url):
    """Komerce (rajaongkir.komerce.id) exposes a different API layout and
    response format than the classic RajaOngkir (/api/cost)."""
    return bool(api_url) and 'komerce.id' in api_url


def is_biteship(api_url):
    """Biteship exposes its own rates/areas API with its own auth header."""
    return bool(api_url) and 'biteship.com' in api_url


# ---------------------------------------------------------------------------
# RajaOngkir / Komerce
# ---------------------------------------------------------------------------

def ongkir_url(api_url, path):
    """Build the endpoint URL, tolerating both the default RajaOngkir layout
    (``https://pro.rajaongkir.com/api``) and full bases such as
    ``https://rajaongkir.komerce.id/api/v1``."""
    base = (api_url or 'https://pro.rajaongkir.com').strip().rstrip('/')
    if not base.endswith('/api/v1') and not base.endswith('/api') \
            and not base.endswith('/cost'):
        base += '/api'
    return base + path


def komerce_route(origin, destination):
    """Return ``(endpoint, origin_id, destination_id)`` for the Komerce API.

    Komerce runs two rate endpoints over two *different* id spaces:

    * ``/calculate/domestic-cost``          -- kabupaten/kota (city) ids
    * ``/calculate/district/domestic-cost`` -- kecamatan (subdistrict) ids

    A city id sent to the district endpoint is accepted but prices the wrong
    area: Karanganyar (169) -> Jember (160) at 15 kg came back as
    ``CTC 525.000 / 11 day`` instead of the district rate for the very
    kecamatan the order had selected (``REG 765.000 / 3 day``). The endpoint
    therefore has to follow the area type the order was priced with.

    ``origin``/``destination`` are dicts ``{'type', 'city_id',
    'subdistrict_id'}``. District pricing is only used when *both* ends are
    districts; otherwise the district side is demoted to its parent city so a
    single city-level call can price the whole route. Demoting is the safe
    direction -- promoting a city to an arbitrary kecamatan would invent a
    route the user never chose.
    """
    if (origin.get('type') == 'subdistrict'
            and destination.get('type') == 'subdistrict'
            and origin.get('subdistrict_id')
            and destination.get('subdistrict_id')):
        return (DISTRICT_ENDPOINT,
                origin['subdistrict_id'],
                destination['subdistrict_id'])
    return (CITY_ENDPOINT,
            origin.get('city_id'),
            destination.get('city_id'))


# ---------------------------------------------------------------------------
# Biteship
# ---------------------------------------------------------------------------

def biteship_base(api_url):
    return (api_url or BITESHIP_DEFAULT_URL).strip().rstrip('/') or BITESHIP_DEFAULT_URL


def biteship_headers(api_key):
    """Auth header for Biteship: the raw key goes in ``Authorization``.

    Biteship does NOT use the ``Bearer`` scheme, and it rejects requests that
    arrive without a browser-like ``User-Agent``.
    """
    return {
        'Authorization': api_key or '',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'Odoo-raja_ongkir/1.0',
    }


def biteship_area_postal(area):
    """Postal code of a Biteship area.

    ``/v1/maps/areas`` has no ``postal_code`` field: the code only appears as
    the trailing token of ``name`` (``"Gempol, Pasuruan, Jawa Timur. 67155"``).
    """
    name = str(area.get('name') or '')
    token = name.rsplit(' ', 1)[-1].strip()
    return token if token.isdigit() else None


def biteship_area_district(area):
    """District ("kecamatan") name of a Biteship area."""
    value = str(area.get('administrative_division_level_3_name') or '').strip()
    if value:
        return value
    parts = [part.strip() for part in str(area.get('name') or '').split(',')]
    return parts[0] if parts else ''


def biteship_area_query(postal_code=None, district=None, city=None):
    """Build the ``/v1/maps/areas`` search input.

    The postal code is the most selective token, so it leads; the kecamatan is
    appended to disambiguate postal codes shared by several districts.
    """
    postal = str(postal_code or '').strip()
    district = str(district or '').strip()
    city = str(city or '').strip()
    if district and postal:
        return '%s %s' % (district, postal)
    if postal:
        return postal
    if district and city:
        return '%s %s' % (district, city)
    return district or city


def pick_biteship_area(areas, postal_code=None, district=None):
    """Pick the best area from a ``/v1/maps/areas`` answer, or ``None``.

    The endpoint is a *fuzzy* search: asking for a city returns several
    districts in arbitrary order, so taking ``areas[0]`` prices an arbitrary --
    often wrong -- zone. Candidates are scored instead:

    * an exact kecamatan match wins outright (it is what couriers zone on);
    * otherwise a postal code matching **exactly one** area is accepted;
    * an ambiguous postal hit, or a city-only hit, yields ``None`` so the caller
      reports an unusable address instead of quoting a wrong zone.
    """
    if not areas:
        return None
    wanted_postal = str(postal_code or '').strip()
    wanted_district = str(district or '').strip().lower()
    district_hits = []
    postal_hits = []
    for area in areas:
        if wanted_district and biteship_area_district(area).lower() == wanted_district:
            district_hits.append(area)
            continue
        if wanted_postal and biteship_area_postal(area) == wanted_postal:
            postal_hits.append(area)
    if district_hits:
        return district_hits[0]
    if len(postal_hits) == 1:
        return postal_hits[0]
    return None


def resolve_biteship_area(search_fn, postal_code=None, district=None, city=None):
    """Resolve an ``area_id`` through ``search_fn`` (query -> list of areas).

    Returns the picked area dict, or ``None`` when the address cannot be mapped
    with confidence.
    """
    query = biteship_area_query(postal_code, district, city)
    if not query:
        return None
    areas = search_fn(query)
    return pick_biteship_area(areas, postal_code, district)


def biteship_search_areas(api_key, api_url, query, limit=10, timeout=25):
    """``GET /v1/maps/areas``. Returns the areas list, or ``[]`` on failure."""
    url = biteship_base(api_url) + BITESHIP_AREAS_PATH
    params = {'countries': 'ID', 'type': 'single', 'input': query, 'limit': limit}
    try:
        response = requests.get(
            url, headers=biteship_headers(api_key), params=params, timeout=timeout)
    except requests.exceptions.RequestException:
        return []
    if response.status_code != 200:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    return payload.get('areas') or []


def parse_biteship_pricing(pricing):
    """Normalize a Biteship ``pricing`` array into this module's service rows.

    Biteship answers one row per courier *service* (JNE reg, JNE jtr, ...), so
    the caller can pick any of them -- unlike the classic RajaOngkir layout
    where a service has to be dug out of nested ``costs``.
    """
    services = []
    for row in pricing or []:
        if not isinstance(row, dict):
            continue
        try:
            value = float(row.get('price') or 0)
        except (TypeError, ValueError):
            value = 0.0
        services.append({
            'code': row.get('courier_code') or '',
            'name': row.get('courier_name') or '',
            'service': row.get('courier_service_name') or '',
            'description': row.get('courier_service_name') or '',
            'value': value,
            'etd': row.get('duration') or '',
            'note': row.get('duration') or '',
        })
    return services
