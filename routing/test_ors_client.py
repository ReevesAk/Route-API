from unittest.mock import MagicMock, patch

import requests
from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase

from routing.ors_client import geocode, get_route


def _resp(payload, status_code=200):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(str(status_code))
    return resp


def _feature(lon, lat, country_a='USA', country='United States'):
    return {
        'geometry'  : {'type': 'Point', 'coordinates': [lon, lat]},
        'properties': {'country_a': country_a, 'country': country},
    }


ROUTE = {'type': 'FeatureCollection', 'features': [{'geometry': {'coordinates': []}}]}


class OfflineEnvironmentTests(SimpleTestCase):

    def test_tests_use_local_memory_cache(self):
        self.assertEqual(
            settings.CACHES['default']['BACKEND'],
            'django.core.cache.backends.locmem.LocMemCache',
        )


class GeocodeTests(SimpleTestCase):

    def setUp(self):
        cache.clear()

    @patch('routing.ors_client.requests.get')
    def test_returns_lat_lon(self, mock_get):
        mock_get.return_value = _resp({'features': [_feature(-87.63, 41.88)]})
        self.assertEqual(geocode('Chicago, IL'), (41.88, -87.63))

    @patch('routing.ors_client.requests.get')
    def test_sends_text_and_key(self, mock_get):
        mock_get.return_value = _resp({'features': [_feature(-87.63, 41.88)]})
        geocode('Chicago, IL')
        params = mock_get.call_args.kwargs['params']
        self.assertEqual(params['text'], 'Chicago, IL')
        self.assertEqual(params['api_key'], 'test-key')

    @patch('routing.ors_client.requests.get')
    def test_second_call_served_from_cache(self, mock_get):
        mock_get.return_value = _resp({'features': [_feature(-87.63, 41.88)]})
        geocode('Chicago, IL')
        result = geocode('  chicago, il ')
        self.assertEqual(result, (41.88, -87.63))
        self.assertEqual(mock_get.call_count, 1)

    @patch('routing.ors_client.requests.get')
    def test_no_features_raises_value_error(self, mock_get):
        mock_get.return_value = _resp({'features': []})
        with self.assertRaisesRegex(ValueError, 'Could not geocode'):
            geocode('Faketown, ZZ')

    @patch('routing.ors_client.requests.get')
    def test_non_us_location_raises_value_error(self, mock_get):
        mock_get.return_value = _resp({'features': [_feature(2.35, 48.86, 'FRA', 'France')]})
        with self.assertRaisesRegex(ValueError, 'France'):
            geocode('Paris')

    @patch('routing.ors_client.requests.get')
    def test_non_us_location_is_logged(self, mock_get):
        mock_get.return_value = _resp({'features': [_feature(2.35, 48.86, 'FRA', 'France')]})
        with self.assertLogs('routing.ors_client', level='WARNING') as logs, self.assertRaises(ValueError):
            geocode('Paris')
        self.assertEqual(logs.records[0].country, 'France')

    @patch('routing.ors_client.requests.get')
    def test_failed_lookup_is_not_cached(self, mock_get):
        mock_get.return_value = _resp({'features': []})
        with self.assertRaises(ValueError):
            geocode('Faketown, ZZ')
        with self.assertRaises(ValueError):
            geocode('Faketown, ZZ')
        self.assertEqual(mock_get.call_count, 2)

    @patch('routing.ors_client.requests.get')
    def test_http_error_propagates(self, mock_get):
        mock_get.return_value = _resp({}, status_code=503)
        with self.assertRaises(requests.exceptions.HTTPError):
            geocode('Chicago, IL')


class GetRouteTests(SimpleTestCase):

    def setUp(self):
        cache.clear()

    @patch('routing.ors_client.requests.post')
    def test_returns_geojson(self, mock_post):
        mock_post.return_value = _resp(ROUTE)
        self.assertEqual(get_route((40.71, -74.01), (34.05, -118.24)), ROUTE)

    @patch('routing.ors_client.requests.post')
    def test_sends_lon_lat_order(self, mock_post):
        mock_post.return_value = _resp(ROUTE)
        get_route((40.71, -74.01), (34.05, -118.24))
        body = mock_post.call_args.kwargs['json']
        self.assertEqual(body['coordinates'], [[-74.01, 40.71], [-118.24, 34.05]])
        self.assertEqual(mock_post.call_args.kwargs['headers']['Authorization'], 'test-key')

    @patch('routing.ors_client.requests.post')
    def test_second_call_served_from_cache(self, mock_post):
        mock_post.return_value = _resp(ROUTE)
        get_route((40.71, -74.01), (34.05, -118.24))
        get_route((40.71, -74.01), (34.05, -118.24))
        self.assertEqual(mock_post.call_count, 1)

    @patch('routing.ors_client.requests.post')
    def test_http_error_propagates(self, mock_post):
        mock_post.return_value = _resp({}, status_code=500)
        with self.assertRaises(requests.exceptions.HTTPError):
            get_route((40.71, -74.01), (34.05, -118.24))
