from unittest.mock import patch

import requests
from django.test import TestCase
from rest_framework.test import APIClient

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

    @patch('routing.views.geocode', side_effect=requests.exceptions.HTTPError(
        '503 Server Error for url: https://api.openrouteservice.org/geocode/search?api_key=SECRET123'
    ))
    def test_upstream_error_is_logged_without_api_key(self, _gc):
        with self.assertLogs('routing.views', level='ERROR') as logs:
            self.client.post(
                self.url,
                {'origin': 'New York, NY', 'destination': 'Los Angeles, CA'},
                format='json',
            )
        record = logs.records[0]
        self.assertEqual(record.getMessage(), 'Routing service request failed')
        self.assertEqual(record.origin, 'New York, NY')
        self.assertNotIn('SECRET123', record.error)

    @patch('routing.views.geocode', side_effect=ValueError("Could not geocode: 'Faketown, ZZ'"))
    def test_rejected_request_is_logged_as_warning(self, _gc):
        with self.assertLogs('routing.views', level='WARNING') as logs:
            self.client.post(
                self.url,
                {'origin': 'Faketown, ZZ', 'destination': 'Los Angeles, CA'},
                format='json',
            )
        self.assertEqual(logs.records[0].levelname, 'WARNING')
        self.assertIn('Faketown', logs.records[0].error)


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
        with self.assertLogs('routing.views', level='ERROR') as logs:
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 503)
        self.assertIn('redis down', logs.output[0])

    def test_no_auth_required(self):
        resp = self.client.get(self.url)
        self.assertNotIn(resp.status_code, (401, 403))
