import csv
import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from fuel.geocoder import _load_index, city_to_coords

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
