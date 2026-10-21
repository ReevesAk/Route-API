from django.test import SimpleTestCase
from rest_framework.test import APIClient

from routing.serializers import RouteRequestSerializer


def _validate(origin='New York, NY', destination='Los Angeles, CA'):
    s = RouteRequestSerializer(data={'origin': origin, 'destination': destination})
    return s.is_valid(), s


class RouteRequestSerializerTests(SimpleTestCase):

    def test_accepts_real_addresses(self):
        for addr in (
            'St. Louis, MO',
            "Coeur d'Alene, ID",
            'Winston-Salem, NC',
            '1600 Pennsylvania Ave NW, Washington, DC 20500',
            '123 Main St #4, Austin, TX',
            'Española, NM',
            '10001',
        ):
            with self.subTest(addr=addr):
                ok, s = _validate(origin=addr)
                self.assertTrue(ok, s.errors)

    def test_strips_surrounding_whitespace(self):
        ok, s = _validate(origin='  Chicago, IL  ')
        self.assertTrue(ok)
        self.assertEqual(s.validated_data['origin'], 'Chicago, IL')

    def test_rejects_blank(self):
        ok, s = _validate(origin='   ')
        self.assertFalse(ok)
        self.assertIn('origin', s.errors)

    def test_rejects_too_short(self):
        ok, s = _validate(origin='A')
        self.assertFalse(ok)
        self.assertIn('origin', s.errors)

    def test_rejects_too_long(self):
        ok, s = _validate(destination='A' * 201)
        self.assertFalse(ok)
        self.assertIn('destination', s.errors)

    def test_accepts_max_length(self):
        ok, _ = _validate(destination='A' * 200)
        self.assertTrue(ok)

    def test_rejects_punctuation_only(self):
        ok, s = _validate(origin='.,-#')
        self.assertFalse(ok)
        self.assertIn('origin', s.errors)

    def test_rejects_control_characters(self):
        ok, s = _validate(origin='Chicago\x00, IL')
        self.assertFalse(ok)

    def test_rejects_newline_inside_value(self):
        ok, _ = _validate(origin='Chicago\nIL')
        self.assertFalse(ok)

    def test_rejects_markup(self):
        ok, s = _validate(origin='<script>alert(1)</script>')
        self.assertFalse(ok)
        self.assertIn('valid US origin', str(s.errors['origin'][0]))

    def test_rejects_non_string(self):
        ok, s = _validate(origin={'city': 'Chicago'})
        self.assertFalse(ok)

    def test_rejects_same_origin_and_destination(self):
        ok, s = _validate(origin='Chicago, IL', destination='chicago, il')
        self.assertFalse(ok)
        self.assertIn('destination', s.errors)


class RouteRequestValidationViewTests(SimpleTestCase):

    def setUp(self):
        self.client = APIClient()

    def _post(self, **body):
        return self.client.post('/api/route/', body, format='json')

    def test_oversized_origin_returns_400(self):
        resp = self._post(origin='A' * 500, destination='Los Angeles, CA')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('origin', resp.data)

    def test_malformed_destination_returns_400(self):
        resp = self._post(origin='New York, NY', destination='<img src=x>')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('destination', resp.data)

    def test_identical_endpoints_return_400(self):
        resp = self._post(origin='Denver, CO', destination='Denver, CO')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('destination', resp.data)
