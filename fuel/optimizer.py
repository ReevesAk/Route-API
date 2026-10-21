import bisect
import math

from django.conf import settings

from .loader import load_stations


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    R = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _lon_pad(miles: float, max_abs_lat: float) -> float:
    """Degrees of longitude spanning `miles` at the latitude where a degree is narrowest."""
    lat = min(max_abs_lat, 89.0)
    return miles / (69.17 * math.cos(math.radians(lat)))


def _build_cumulative(coords: list) -> list[float]:
    cum = [0.0]
    for i in range(1, len(coords)):
        lon1, lat1 = coords[i - 1]
        lon2, lat2 = coords[i]
        cum.append(cum[-1] + _haversine(lat1, lon1, lat2, lon2))
    return cum


def plan_stops(route_coords: list, stations: list | None = None) -> tuple[list[dict], float]:
    """
    Walk route_coords ([lon, lat] pairs from ORS) in 500-mile windows.
    In each 70–100% refuel zone, pick the cheapest station within 30 miles of
    any sampled waypoint.

    Returns (stops, total_distance_miles).
    """
    max_range  = getattr(settings, 'VEHICLE_RANGE_MILES', 500)
    mpg        = getattr(settings, 'VEHICLE_MPG', 10)
    lower_pct  = getattr(settings, 'REFUEL_LOWER_PERCENT', 0.70)
    detour_mi  = getattr(settings, 'MAX_STATION_DETOUR_MILES', 30)

    if not route_coords:
        return [], 0.0

    if stations is None:
        stations = load_stations()

    # Lat-sorted index for O(log n) spatial pre-filtering per refuel zone.
    stations_sorted = sorted(stations, key=lambda s: s['lat'])
    station_lats    = [s['lat'] for s in stations_sorted]
    lat_pad = detour_mi / 69.0   # degrees lat ≈ miles / 69

    cumulative  = _build_cumulative(route_coords)
    total_miles = cumulative[-1]

    # Downsample to ~10-mile intervals for performance (~280 points NY→LA)
    sampled: list[tuple[float, float, float]] = []  # (cum_miles, lat, lon)
    last_sampled = -999.0
    for i, cum in enumerate(cumulative):
        if cum - last_sampled >= 10.0:
            lon, lat = route_coords[i]
            sampled.append((cum, lat, lon))
            last_sampled = cum

    stops: list[dict] = []
    last_stop_mile = 0.0

    for _ in range(50):  # safety cap
        if last_stop_mile + max_range >= total_miles:
            break

        refuel_min = last_stop_mile + max_range * lower_pct
        refuel_max = last_stop_mile + max_range

        zone_pts = [(c, la, lo) for c, la, lo in sampled if refuel_min <= c <= refuel_max]
        if not zone_pts:
            last_stop_mile = refuel_min
            continue

        # Bounding box of the refuel zone, expanded by detour radius
        lat_lo = min(la for _, la, _ in zone_pts) - lat_pad
        lat_hi = max(la for _, la, _ in zone_pts) + lat_pad
        lon_pad = _lon_pad(detour_mi, max(abs(lat_lo), abs(lat_hi)))
        lon_lo = min(lo for _, _, lo in zone_pts) - lon_pad
        lon_hi = max(lo for _, _, lo in zone_pts) + lon_pad
        lo_i = bisect.bisect_left(station_lats, lat_lo)
        hi_i = bisect.bisect_right(station_lats, lat_hi)
        candidates = [s for s in stations_sorted[lo_i:hi_i] if lon_lo <= s['lon'] <= lon_hi]

        best_station: dict | None = None
        best_price = float('inf')
        best_mile  = 0.0

        for (cum, wp_lat, wp_lon) in zone_pts:
            for st in candidates:
                if st['price'] >= best_price:
                    continue
                if _haversine(wp_lat, wp_lon, st['lat'], st['lon']) <= detour_mi:
                    best_station = st
                    best_price   = st['price']
                    best_mile    = cum

        if best_station is None:
            # No station in zone — advance window to avoid an infinite loop
            last_stop_mile = refuel_min
            continue

        miles_from_last = best_mile - last_stop_mile
        gallons = miles_from_last / mpg
        addr = ', '.join(filter(None, [
            best_station['address'], best_station['city'], best_station['state']
        ]))

        stops.append({
            'name'                : best_station['name'],
            'address'             : addr,
            'lat'                 : best_station['lat'],
            'lon'                 : best_station['lon'],
            'price_per_gallon'    : round(best_price, 3),
            'gallons'             : round(gallons, 2),
            'cost'                : round(gallons * best_price, 2),
            'miles_from_last_stop': round(miles_from_last, 1),
        })
        last_stop_mile = best_mile

    return stops, round(total_miles, 1)
