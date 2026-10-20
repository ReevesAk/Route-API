import csv
import json
import io
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import requests
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from fuel.geocoder import city_to_coords, _load_index
from fuel.optimizer import plan_stops


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MOCK_GEOJSON = {
    'type': 'FeatureCollection',
    'features': [{
        'type'    : 'Feature',
        'geometry': {
            'type'       : 'LineString',
            'coordinates': [
                [-74.0060, 40.7128],   # NYC
                [-87.6298, 41.8781],   # Chicago (~790 mi)
                [-118.2437, 34.0522],  # LA (~2800 mi total)
            ],
        },
        'properties': {},
    }],
}

# Compact route: ~800 miles straight north (lon fixed at 0)
# 1 degree latitude ≈ 69 miles
STRAIGHT_COORDS = [[0.0, float(i)] for i in range(0, 12)]  # 0 → 11 °N, ~759 mi


def _make_station(lat, lon, price, sid='1', name='Test Stop', city='Testville', state='TX'):
    return {'id': sid, 'name': name, 'address': '1 Main St',
            'city': city, 'state': state, 'lat': lat, 'lon': lon, 'price': price}


# ---------------------------------------------------------------------------
# 1–3  GeocoderTests
# ---------------------------------------------------------------------------

class GeocoderTests(TestCase):

    def setUp(self):
        _load_index.cache_clear()

    def tearDown(self):
        _load_index.cache_clear()

    def _patch_index(self, data):
        return patch('fuel.geocoder._load_index', return_value=data)

    def test_city_found(self):
        index = {('chicago', 'IL'): (41.8781, -87.6298)}
        with self._patch_index(index):
            result = city_to_coords('Chicago', 'IL')
        self.assertEqual(result, (41.8781, -87.6298))

    def test_city_not_found(self):
        with self._patch_index({}):
            result = city_to_coords('Nowhere', 'XX')
        self.assertIsNone(result)

    def test_case_insensitive(self):
        index = {('new york', 'NY'): (40.7128, -74.0060)}
        with self._patch_index(index):
            result = city_to_coords('NEW YORK', 'ny')
        self.assertEqual(result, (40.7128, -74.0060))


# ---------------------------------------------------------------------------
# 4–7  LoaderTests
# ---------------------------------------------------------------------------

class LoaderTests(TestCase):

    def _csv(self, rows):
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue()

    def _row(self, sid='1', name='Flying J', city='Chicago', state='IL', price='3.459'):
        return {
            'OPIS Truckstop ID': sid, 'Truckstop Name': name,
            'Address': '100 Hwy 1', 'City': city, 'State': state,
            'Rack ID': '1', 'Retail Price': price,
        }

    @patch('fuel.geocoder._load_index', return_value={('chicago', 'IL'): (41.88, -87.63)})
    def test_loads_stations(self, _mock):
        from fuel.loader import load_stations
        load_stations.cache_clear()
        csv_text = self._csv([self._row()])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'fuel_prices.csv').write_text(csv_text)
            with override_settings(BASE_DIR=tmp):
                stations = load_stations()
        load_stations.cache_clear()
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0]['city'], 'Chicago')

    @patch('fuel.geocoder._load_index', return_value={('chicago', 'IL'): (41.88, -87.63)})
    def test_deduplicates_by_id(self, _mock):
        from fuel.loader import load_stations
        load_stations.cache_clear()
        rows = [self._row(sid='42'), self._row(sid='42', name='Duplicate')]
        csv_text = self._csv(rows)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'fuel_prices.csv').write_text(csv_text)
            with override_settings(BASE_DIR=tmp):
                stations = load_stations()
        load_stations.cache_clear()
        self.assertEqual(len(stations), 1)

    @patch('fuel.geocoder._load_index', return_value={('chicago', 'IL'): (41.88, -87.63)})
    def test_skips_invalid_price(self, _mock):
        from fuel.loader import load_stations
        load_stations.cache_clear()
        rows = [self._row(sid='1', price='3.459'), self._row(sid='2', price='N/A')]
        csv_text = self._csv(rows)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'fuel_prices.csv').write_text(csv_text)
            with override_settings(BASE_DIR=tmp):
                stations = load_stations()
        load_stations.cache_clear()
        self.assertEqual(len(stations), 1)

    @patch('fuel.geocoder._load_index', return_value={('chicago', 'IL'): (41.88, -87.63)})
    def test_uses_geocoder_for_missing_coords(self, _mock):
        from fuel.loader import load_stations
        load_stations.cache_clear()
        csv_text = self._csv([self._row()])  # no lat/lon columns
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'fuel_prices.csv').write_text(csv_text)
            with override_settings(BASE_DIR=tmp):
                stations = load_stations()
        load_stations.cache_clear()
        self.assertAlmostEqual(stations[0]['lat'], 41.88)
        self.assertAlmostEqual(stations[0]['lon'], -87.63)


# ---------------------------------------------------------------------------
# 8–12  OptimizerTests  (all offline, stations passed directly)
# ---------------------------------------------------------------------------

class OptimizerTests(TestCase):

    def test_short_route_no_stops_needed(self):
        # 3-point route totalling ~276 miles (well within 500-mile range)
        coords = [[0.0, 0.0], [0.0, 2.0], [0.0, 4.0]]
        stops, total = plan_stops(coords, stations=[
            _make_station(lat=2.0, lon=0.0, price=3.50),
        ])
        self.assertEqual(stops, [])

    @override_settings(VEHICLE_RANGE_MILES=500, VEHICLE_MPG=10,
                       REFUEL_LOWER_PERCENT=0.70, MAX_STATION_DETOUR_MILES=30)
    def test_one_stop_needed(self):
        # ~759-mile route needs 1 stop; station at 6°N ≈ mile 414, lon=0.1 ≈ 7 mi from route
        station = _make_station(lat=6.0, lon=0.1, price=3.50)
        stops, total = plan_stops(STRAIGHT_COORDS, stations=[station])
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]['price_per_gallon'], 3.50)

    @override_settings(VEHICLE_RANGE_MILES=500, VEHICLE_MPG=10,
                       REFUEL_LOWER_PERCENT=0.70, MAX_STATION_DETOUR_MILES=30)
    def test_picks_cheapest_station(self):
        cheap  = _make_station(lat=6.0, lon=0.1, price=3.10, sid='cheap')
        pricey = _make_station(lat=6.1, lon=0.1, price=3.90, sid='pricey')
        stops, _ = plan_stops(STRAIGHT_COORDS, stations=[pricey, cheap])
        self.assertEqual(stops[0]['price_per_gallon'], 3.10)

    @override_settings(VEHICLE_RANGE_MILES=500, VEHICLE_MPG=10,
                       REFUEL_LOWER_PERCENT=0.70, MAX_STATION_DETOUR_MILES=30)
    def test_stop_fields_present(self):
        station = _make_station(lat=6.0, lon=0.1, price=3.50)
        stops, _ = plan_stops(STRAIGHT_COORDS, stations=[station])
        required = {'name', 'address', 'lat', 'lon', 'price_per_gallon',
                    'gallons', 'cost', 'miles_from_last_stop'}
        self.assertTrue(required.issubset(stops[0].keys()))

    @override_settings(VEHICLE_RANGE_MILES=500, VEHICLE_MPG=10,
                       REFUEL_LOWER_PERCENT=0.70, MAX_STATION_DETOUR_MILES=30)
    def test_total_distance_positive(self):
        _, total = plan_stops(STRAIGHT_COORDS, stations=[])
        self.assertGreater(total, 0)


# ---------------------------------------------------------------------------
# 13–22  RouteViewTests
# ---------------------------------------------------------------------------

STOP = {
    'name': 'Flying J #1', 'address': '1 Main St, Chicago, IL',
    'lat': 41.88, 'lon': -87.63,
    'price_per_gallon': 3.459, 'gallons': 35.0, 'cost': 121.07,
    'miles_from_last_stop': 350.0,
}


class RouteViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url    = '/api/route/'

    # --- validation ---

    def test_missing_origin_returns_400(self):
        resp = self.client.post(self.url, {'destination': 'Los Angeles, CA'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('origin', resp.data)

    def test_missing_destination_returns_400(self):
        resp = self.client.post(self.url, {'origin': 'New York, NY'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('destination', resp.data)

    def test_empty_body_returns_400(self):
        resp = self.client.post(self.url, {}, format='json')
        self.assertEqual(resp.status_code, 400)

    # --- success path ---

    @patch('routing.views.plan_stops', return_value=([STOP], 2800.0))
    @patch('routing.views.get_route',  return_value=MOCK_GEOJSON)
    @patch('routing.views.geocode',    return_value=(40.71, -74.01))
    def test_success_returns_200(self, _gc, _gr, _ps):
        resp = self.client.post(
            self.url,
            {'origin': 'New York, NY', 'destination': 'Los Angeles, CA'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)

    @patch('routing.views.plan_stops', return_value=([STOP], 2800.0))
    @patch('routing.views.get_route',  return_value=MOCK_GEOJSON)
    @patch('routing.views.geocode',    return_value=(40.71, -74.01))
    def test_response_has_all_keys(self, _gc, _gr, _ps):
        resp = self.client.post(
            self.url,
            {'origin': 'New York, NY', 'destination': 'Los Angeles, CA'},
            format='json',
        )
        for key in ('fuel_stops', 'total_fuel_cost', 'total_distance_miles',
                    'route_geojson', 'google_maps_url'):
            self.assertIn(key, resp.data)

    @patch('routing.views.plan_stops', return_value=([STOP], 2800.0))
    @patch('routing.views.get_route',  return_value=MOCK_GEOJSON)
    @patch('routing.views.geocode',    return_value=(40.71, -74.01))
    def test_fuel_stop_fields(self, _gc, _gr, _ps):
        resp = self.client.post(
            self.url,
            {'origin': 'New York, NY', 'destination': 'Los Angeles, CA'},
            format='json',
        )
        stop = resp.data['fuel_stops'][0]
        for field in ('name', 'address', 'lat', 'lon', 'price_per_gallon',
                      'gallons', 'cost', 'miles_from_last_stop'):
            self.assertIn(field, stop)

    @patch('routing.views.plan_stops', return_value=([STOP], 2800.0))
    @patch('routing.views.get_route',  return_value=MOCK_GEOJSON)
    @patch('routing.views.geocode',    return_value=(40.71, -74.01))
    def test_total_cost_equals_sum_of_stops(self, _gc, _gr, _ps):
        resp = self.client.post(
            self.url,
            {'origin': 'New York, NY', 'destination': 'Los Angeles, CA'},
            format='json',
        )
        expected = round(sum(s['cost'] for s in [STOP]), 2)
        self.assertAlmostEqual(float(resp.data['total_fuel_cost']), expected, places=2)

    @patch('routing.views.plan_stops', return_value=([STOP], 2800.0))
    @patch('routing.views.get_route',  return_value=MOCK_GEOJSON)
    @patch('routing.views.geocode',    return_value=(40.71, -74.01))
    def test_google_maps_url_format(self, _gc, _gr, _ps):
        resp = self.client.post(
            self.url,
            {'origin': 'New York, NY', 'destination': 'Los Angeles, CA'},
            format='json',
        )
        self.assertTrue(resp.data['google_maps_url'].startswith('https://www.google.com/maps/dir/'))

    @patch('routing.views.plan_stops', return_value=([], 2800.0))
    @patch('routing.views.get_route',  return_value=MOCK_GEOJSON)
    @patch('routing.views.geocode',    return_value=(40.71, -74.01))
    def test_google_maps_url_contains_endpoints(self, _gc, _gr, _ps):
        resp = self.client.post(
            self.url,
            {'origin': 'New York, NY', 'destination': 'Los Angeles, CA'},
            format='json',
        )
        url = resp.data['google_maps_url']
        self.assertIn('New%20York', url)
        self.assertIn('Los%20Angeles', url)

    # --- error handling ---

    @patch('routing.views.geocode', side_effect=requests.exceptions.ConnectionError('timeout'))
    def test_ors_connection_error_returns_502(self, _gc):
        resp = self.client.post(
            self.url,
            {'origin': 'New York, NY', 'destination': 'Los Angeles, CA'},
            format='json',
        )
        self.assertEqual(resp.status_code, 502)
        self.assertIn('error', resp.data)

    @patch('routing.views.geocode', side_effect=requests.exceptions.HTTPError('503'))
    def test_ors_http_error_returns_502(self, _gc):
        resp = self.client.post(
            self.url,
            {'origin': 'New York, NY', 'destination': 'Los Angeles, CA'},
            format='json',
        )
        self.assertEqual(resp.status_code, 502)

    @patch('routing.views.geocode', side_effect=ValueError("Could not geocode: 'Faketown, ZZ'"))
    def test_geocode_value_error_returns_400(self, _gc):
        resp = self.client.post(
            self.url,
            {'origin': 'Faketown, ZZ', 'destination': 'Los Angeles, CA'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.data)

    @patch('routing.views.geocode', side_effect=requests.exceptions.HTTPError(
        '503 Server Error: Service Unavailable for url: '
        'https://api.openrouteservice.org/geocode/search?api_key=SECRET123&text=NYC&size=1'
    ))
    def test_502_body_does_not_leak_api_key(self, _gc):
        resp = self.client.post(
            self.url,
            {'origin': 'New York, NY', 'destination': 'Los Angeles, CA'},
            format='json',
        )
        self.assertEqual(resp.status_code, 502)
        self.assertNotIn('SECRET123', resp.data['error'])
        self.assertIn('api_key=[REDACTED]', resp.data['error'])


# ---------------------------------------------------------------------------
# HealthViewTests
# ---------------------------------------------------------------------------

class HealthViewTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.url    = '/api/health/'

    def test_returns_200_when_cache_reachable(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {'status': 'ok', 'cache': 'ok'})

    @patch('routing.views.cache.get', return_value=None)
    def test_returns_503_when_cache_read_misses(self, _get):
        # django-redis with IGNORE_EXCEPTIONS turns an outage into a silent miss
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.data['cache'], 'unreachable')

    @patch('routing.views.cache.set', side_effect=ConnectionError('redis down'))
    def test_returns_503_when_cache_raises(self, _set):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 503)

    def test_no_auth_required(self):
        resp = self.client.get(self.url)
        self.assertNotIn(resp.status_code, (401, 403))
