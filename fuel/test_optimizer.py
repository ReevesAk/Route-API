from django.test import TestCase, override_settings

from fuel.optimizer import plan_stops

# Compact route: ~800 miles straight north (lon fixed at 0)
# 1 degree latitude ≈ 69 miles
STRAIGHT_COORDS = [[0.0, float(i)] for i in range(12)]  # 0 → 11 °N, ~759 mi


def _make_station(lat, lon, price, sid='1', name='Test Stop', city='Testville', state='TX'):
    return {'id': sid, 'name': name, 'address': '1 Main St',
            'city': city, 'state': state, 'lat': lat, 'lon': lon, 'price': price}



# ---------------------------------------------------------------------------
# 8–12  OptimizerTests  (all offline, stations passed directly)
# ---------------------------------------------------------------------------

class OptimizerTests(TestCase):

    def test_empty_route_returns_no_stops(self):
        self.assertEqual(plan_stops([], stations=[_make_station(0.0, 0.0, 3.0)]), ([], 0.0))

    def test_single_point_route_returns_no_stops(self):
        self.assertEqual(plan_stops([[0.0, 0.0]], stations=[]), ([], 0.0))

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


class DetourLatitudeTests(TestCase):
    """
    A degree of longitude shrinks with latitude (~44 mi at 50°N vs ~53 mi at
    40°N), so the east-west search box must widen further north.
    """

    @override_settings(VEHICLE_RANGE_MILES=500, VEHICLE_MPG=10,
                       REFUEL_LOWER_PERCENT=0.70, MAX_STATION_DETOUR_MILES=30)
    def test_finds_station_due_east_within_detour_at_northern_latitude(self):
        route = [[0.0, float(lat)] for lat in range(44, 56)]   # 44 → 55 °N
        station = _make_station(lat=50.0, lon=0.63, price=3.25)  # ~28 mi east of route
        stops, _ = plan_stops(route, stations=[station])
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]['price_per_gallon'], 3.25)

    @override_settings(VEHICLE_RANGE_MILES=500, VEHICLE_MPG=10,
                       REFUEL_LOWER_PERCENT=0.70, MAX_STATION_DETOUR_MILES=30)
    def test_ignores_station_beyond_detour_at_northern_latitude(self):
        route = [[0.0, float(lat)] for lat in range(44, 56)]
        station = _make_station(lat=50.0, lon=0.75, price=3.25)  # ~33 mi east
        stops, _ = plan_stops(route, stations=[station])
        self.assertEqual(stops, [])
