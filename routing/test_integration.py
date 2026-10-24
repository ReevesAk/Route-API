"""
End-to-end tests for POST /api/route/.

Only the HTTP layer is mocked: requests go through the real serializer,
ORS client (with its cache), CSV loader and optimizer.
"""
import csv
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from fuel.loader import load_stations

# Straight north along 100°W from 30°N to 41°N (~759 miles).
ROUTE_COORDS = [[-100.0, float(lat)] for lat in range(30, 42)]

PLACES = {
    'San Angelo, TX': (-100.0, 30.0, 'USA', 'United States'),
    'North Platte, NE': (-100.0, 41.0, 'USA', 'United States'),
    'Toronto, ON': (-79.38, 43.65, 'CAN', 'Canada'),
}

STATIONS = [
    # ~414 mi from the start, in the 350-500 mile refuel zone
    {'id': '1', 'name': 'Cheap Diesel', 'lat': 36.0, 'lon': -99.95, 'price': '3.199'},
    {'id': '2', 'name': 'Pricey Diesel', 'lat': 36.2, 'lon': -99.95, 'price': '3.899'},
    # ~200 miles off the route: never a candidate
    {'id': '3', 'name': 'Far Away', 'lat': 36.0, 'lon': -97.0, 'price': '1.999'},
]

VEHICLE = dict(VEHICLE_RANGE_MILES=500, VEHICLE_MPG=10,
               REFUEL_LOWER_PERCENT=0.70, MAX_STATION_DETOUR_MILES=30)


def _ok(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _fake_geocode(url, params, timeout):
    lon, lat, country_a, country = PLACES[params['text']]
    return _ok({'features': [{
        'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
        'properties': {'country_a': country_a, 'country': country},
    }]})


def _fake_directions(url, headers, json, timeout):
    return _ok({'type': 'FeatureCollection', 'features': [{
        'type': 'Feature',
        'geometry': {'type': 'LineString', 'coordinates': ROUTE_COORDS},
        'properties': {},
    }]})


def _http_error(status_code, url):
    """A real requests HTTPError, carrying the URL in its message like production."""
    resp = requests.Response()
    resp.status_code = status_code
    resp.reason = 'Service Unavailable'
    resp.url = url
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        return exc
    raise AssertionError('expected raise_for_status to raise')


@override_settings(**VEHICLE)
class RouteEndToEndTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        cache.clear()
        load_stations.cache_clear()
        self.addCleanup(load_stations.cache_clear)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        self._write_stations(self.data_dir, STATIONS)
        base_dir = override_settings(BASE_DIR=tmp.name)
        base_dir.enable()
        self.addCleanup(base_dir.disable)

        get = patch('routing.ors_client.requests.get', side_effect=_fake_geocode)
        post = patch('routing.ors_client.requests.post', side_effect=_fake_directions)
        self.mock_get = get.start()
        self.mock_post = post.start()
        self.addCleanup(get.stop)
        self.addCleanup(post.stop)

    def _write_stations(self, directory, rows):
        with open(directory / 'fuel_prices.csv', 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['OPIS Truckstop ID', 'Truckstop Name', 'Address', 'City',
                             'State', 'Rack ID', 'Retail Price', 'Latitude', 'Longitude'])
            for r in rows:
                writer.writerow([r['id'], r['name'], '1 Hwy 83', 'Testville', 'KS',
                                 '1', r['price'], r['lat'], r['lon']])

    def _post(self, origin='San Angelo, TX', destination='North Platte, NE'):
        return self.client.post('/api/route/', {'origin': origin, 'destination': destination},
                                format='json')

    def test_plans_cheapest_stop_on_route(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([s['name'] for s in resp.data['fuel_stops']], ['Cheap Diesel'])
        stop = resp.data['fuel_stops'][0]
        self.assertEqual(stop['price_per_gallon'], 3.199)
        self.assertEqual(stop['address'], '1 Hwy 83, Testville, KS')
        self.assertAlmostEqual(resp.data['total_distance_miles'], 760.0, delta=2)
        self.assertAlmostEqual(resp.data['total_fuel_cost'], stop['cost'], places=2)
        self.assertEqual(resp.data['warnings'], [])

    def test_response_links_route_through_stop(self):
        data = self._post().data
        self.assertEqual(data['route_geojson']['features'][0]['geometry']['coordinates'], ROUTE_COORDS)
        self.assertIn('36.0,-99.95', data['google_maps_url'])
        self.assertIn('San%20Angelo', data['google_maps_url'])

    def test_calls_ors_with_geocoded_coordinates(self):
        self._post()
        self.assertEqual(self.mock_get.call_count, 2)
        body = self.mock_post.call_args.kwargs['json']
        self.assertEqual(body['coordinates'], [[-100.0, 30.0], [-100.0, 41.0]])

    def test_repeat_request_is_served_from_cache(self):
        first = self._post().data
        second = self._post().data
        self.assertEqual(self.mock_get.call_count, 2)
        self.assertEqual(self.mock_post.call_count, 1)
        self.assertEqual(first['fuel_stops'], second['fuel_stops'])

    def test_non_us_destination_returns_400(self):
        resp = self._post(destination='Toronto, ON')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Canada', resp.data['error'])
        self.mock_post.assert_not_called()

    def test_routing_failure_returns_502(self):
        self.mock_post.side_effect = requests.exceptions.ConnectionError('connection reset')
        resp = self._post()
        self.assertEqual(resp.status_code, 502)
        self.assertIn('connection reset', resp.data['error'])

    def test_geocoding_http_error_returns_502_without_api_key(self):
        url = 'https://api.openrouteservice.org/geocode/search?api_key=SECRET123&text=San+Angelo&size=1'
        self.mock_get.side_effect = None
        self.mock_get.return_value.raise_for_status.side_effect = _http_error(503, url)
        resp = self._post()
        self.assertEqual(resp.status_code, 502)
        self.assertIn('503 Server Error', resp.data['error'])
        self.assertNotIn('SECRET123', resp.data['error'])

    def test_failed_request_is_not_cached(self):
        self.mock_post.side_effect = requests.exceptions.ConnectionError('down')
        self.assertEqual(self._post().status_code, 502)
        self.mock_post.side_effect = _fake_directions
        self.assertEqual(self._post().status_code, 200)

    def test_no_reachable_station_returns_warning(self):
        self._write_stations(self.data_dir, STATIONS[2:])   # only the off-route station
        resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['fuel_stops'], [])
        self.assertEqual(len(resp.data['warnings']), 1)
        self.assertEqual(resp.data['warnings'][0]['to_mile'], 500.0)
