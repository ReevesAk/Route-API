import io
import json
import logging
import sys

from django.core.management import call_command
from django.test import SimpleTestCase

from fuel_route_api.log_format import JsonFormatter


def _record(msg='hello', level=logging.INFO, extra=None, exc_info=None):
    record = logging.getLogger('routing.views').makeRecord(
        'routing.views', level, __file__, 1, msg, (), exc_info, extra=extra,
    )
    return record


class JsonFormatterTests(SimpleTestCase):

    def test_core_fields(self):
        out = json.loads(JsonFormatter().format(_record()))
        self.assertEqual(out['level'], 'INFO')
        self.assertEqual(out['logger'], 'routing.views')
        self.assertEqual(out['msg'], 'hello')
        self.assertIn('ts', out)

    def test_extra_fields_merged(self):
        out = json.loads(JsonFormatter().format(_record(extra={'origin': 'NYC', 'dest': 'LA'})))
        self.assertEqual(out['origin'], 'NYC')
        self.assertEqual(out['dest'], 'LA')

    def test_non_serialisable_extra_is_stringified(self):
        out = json.loads(JsonFormatter().format(_record(extra={'coords': (1.0, 2.0), 'obj': object()})))
        self.assertEqual(out['coords'], [1.0, 2.0])
        self.assertIsInstance(out['obj'], str)

    def test_exception_included(self):
        try:
            raise RuntimeError('boom')
        except RuntimeError:
            out = json.loads(JsonFormatter().format(_record(exc_info=sys.exc_info())))
        self.assertIn('RuntimeError: boom', out['exc'])

    def test_single_line(self):
        self.assertNotIn('\n', JsonFormatter().format(_record(msg='a\nb')))


class OpenApiSchemaTests(SimpleTestCase):

    def test_schema_generates_without_warnings(self):
        out = io.StringIO()
        call_command('spectacular', '--fail-on-warn', '--format', 'openapi-json', stdout=out, stderr=io.StringIO())
        schema = json.loads(out.getvalue())
        self.assertIn('/api/route/', schema['paths'])
        self.assertIn('/api/health/', schema['paths'])

    def test_health_responses_documented(self):
        out = io.StringIO()
        call_command('spectacular', '--format', 'openapi-json', stdout=out, stderr=io.StringIO())
        responses = json.loads(out.getvalue())['paths']['/api/health/']['get']['responses']
        self.assertEqual(set(responses), {'200', '503'})
