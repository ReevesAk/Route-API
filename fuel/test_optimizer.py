from unittest.mock import patch

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


# ~1520-mile route straight north along the prime meridian (1° lat ≈ 69.1 mi)
LONG_COORDS = [[0.0, float(i)] for i in range(23)]

VEHICLE = dict(VEHICLE_RANGE_MILES=500, VEHICLE_MPG=10,
               REFUEL_LOWER_PERCENT=0.70, MAX_STATION_DETOUR_MILES=30)


@override_settings(**VEHICLE)
class OptimizerBehaviourTests(TestCase):

    def test_long_route_needs_multiple_stops(self):
        stations = [_make_station(float(lat), 0.05, 3.50, sid=str(lat)) for lat in range(23)]
        stops, total = plan_stops(LONG_COORDS, stations=stations)
        self.assertEqual(len(stops), 3)
        self.assertAlmostEqual(total, 1520.0, delta=2)

    def test_no_leg_exceeds_vehicle_range(self):
        stations = [_make_station(float(lat), 0.05, 3.50, sid=str(lat)) for lat in range(23)]
        stops, _ = plan_stops(LONG_COORDS, stations=stations)
        for stop in stops:
            self.assertLessEqual(stop['miles_from_last_stop'], 500)
            self.assertGreaterEqual(stop['miles_from_last_stop'], 350)

    def test_cheaper_station_before_refuel_zone_is_ignored(self):
        early_cheap = _make_station(lat=2.0, lon=0.05, price=2.00, sid='early')  # mile ~138
        in_zone     = _make_station(lat=6.0, lon=0.05, price=3.80, sid='zone')   # mile ~415
        stops, _ = plan_stops(STRAIGHT_COORDS, stations=[early_cheap, in_zone])
        self.assertEqual([s['price_per_gallon'] for s in stops], [3.80])

    def test_window_without_station_is_skipped(self):
        # No station in the first zone (miles 350-500): the search resumes from
        # mile 350, so the next zone is miles 700-850. 12°N (~829 mi) is in it,
        # 13°N (~898 mi) is not.
        stations = [_make_station(12.0, 0.05, 3.40, sid='a'), _make_station(13.0, 0.05, 3.30, sid='b')]
        stops, _ = plan_stops(LONG_COORDS, stations=stations)
        self.assertEqual(stops[0]['price_per_gallon'], 3.40)

    def test_no_stations_anywhere_returns_no_stops(self):
        stops, total = plan_stops(LONG_COORDS, stations=[])
        self.assertEqual(stops, [])
        self.assertGreater(total, 1500)

    def test_sparse_route_with_no_waypoint_in_zone_terminates(self):
        # A single 760-mile segment has no sampled point inside miles 350-500.
        stops, total = plan_stops([[0.0, 0.0], [0.0, 11.0]], stations=[_make_station(6.0, 0.05, 3.5)])
        self.assertEqual(stops, [])
        self.assertAlmostEqual(total, 760.0, delta=2)

    def test_station_just_inside_detour_is_used(self):
        station = _make_station(lat=6.0, lon=0.43, price=3.50)  # ~29.7 mi at the equator
        stops, _ = plan_stops(STRAIGHT_COORDS, stations=[station])
        self.assertEqual(len(stops), 1)

    def test_station_just_outside_detour_is_ignored(self):
        station = _make_station(lat=6.0, lon=0.45, price=3.50)  # ~31.1 mi
        stops, _ = plan_stops(STRAIGHT_COORDS, stations=[station])
        self.assertEqual(stops, [])

    def test_gallons_and_cost_follow_distance_and_mpg(self):
        station = _make_station(lat=6.0, lon=0.05, price=3.50)
        stop = plan_stops(STRAIGHT_COORDS, stations=[station])[0][0]
        self.assertAlmostEqual(stop['gallons'], stop['miles_from_last_stop'] / 10, delta=0.01)
        self.assertAlmostEqual(stop['cost'], stop['gallons'] * 3.50, delta=0.02)

    def test_address_joins_non_empty_parts(self):
        station = _make_station(lat=6.0, lon=0.05, price=3.50, city='', state='OH')
        stop = plan_stops(STRAIGHT_COORDS, stations=[station])[0][0]
        self.assertEqual(stop['address'], '1 Main St, OH')

    @override_settings(VEHICLE_RANGE_MILES=1000)
    def test_longer_range_needs_fewer_stops(self):
        stations = [_make_station(float(lat), 0.05, 3.50, sid=str(lat)) for lat in range(23)]
        stops, _ = plan_stops(LONG_COORDS, stations=stations)
        self.assertEqual(len(stops), 1)

    @patch('fuel.optimizer.load_stations')
    def test_loads_stations_when_none_given(self, mock_load):
        mock_load.return_value = [_make_station(lat=6.0, lon=0.05, price=3.50)]
        stops, _ = plan_stops(STRAIGHT_COORDS)
        mock_load.assert_called_once()
        self.assertEqual(len(stops), 1)


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
