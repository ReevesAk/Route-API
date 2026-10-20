import logging

from django.test.runner import DiscoverRunner
from django.test.utils import override_settings

TEST_CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'fuel-route-api-tests',
    }
}


class OfflineTestRunner(DiscoverRunner):
    """
    Run the suite without external services: always use an in-process cache,
    even if REDIS_URL is set in the developer's .env, and blank the ORS key so
    an unpatched network call can never authenticate against the real API.
    App log output is muted; tests that care use assertLogs, which installs
    its own handler.
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._offline = override_settings(CACHES=TEST_CACHES, ORS_API_KEY='test-key')
        self._offline.enable()
        for name in ('routing', 'fuel'):
            for handler in logging.getLogger(name).handlers:
                handler.setLevel(logging.CRITICAL + 1)

    def teardown_test_environment(self, **kwargs):
        self._offline.disable()
        super().teardown_test_environment(**kwargs)
