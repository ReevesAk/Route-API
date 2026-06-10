# Fuel Route API

A Django REST API that plans the **cheapest diesel fuel stops** for a US road trip. Given an origin and destination, it fetches a real driving route, then walks the route in 500-mile windows to find the lowest-priced truck stop within 30 miles at each refueling point.

---

## How It Works

```
POST /api/route/
  { "origin": "New York, NY", "destination": "Los Angeles, CA" }
```

1. Both addresses are **geocoded in parallel** via OpenRouteService.
2. A **single ORS Directions API call** returns the full driving route as GeoJSON.
3. The route coordinates are handed to the **local fuel optimizer**, which:
   - Samples waypoints every ~10 miles along the route
   - Divides the trip into 500-mile range windows
   - Within each window's 70–100% refuel zone, finds the cheapest diesel station within 30 miles using a lat-sorted spatial index
4. The response includes each stop's name, address, price per gallon, gallons to fill, cost, and a Google Maps URL for the full trip.

All geocoding and routing results are **cached in Redis** (24-hour TTL), so repeat requests for the same route respond in ~100ms instead of ~3s.

---

## Setup

### Prerequisites

- Python 3.12+
- Redis (for response caching)

```bash
brew install redis
brew services start redis
```

### Install

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Environment variables

Copy the example below into a `.env` file at the project root:

```
SECRET_KEY=your-django-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

ORS_API_KEY=your-openrouteservice-api-key

REDIS_URL=redis://127.0.0.1:6379/1
```

Get a free ORS API key at [openrouteservice.org](https://openrouteservice.org).

### Data files

Place the following files in the project root (next to `manage.py`):

| File | Description |
|------|-------------|
| `fuel_prices.csv` | OPIS fuel station data (columns: `OPIS Truckstop ID`, `Truckstop Name`, `Address`, `City`, `State`, `Rack ID`, `Retail Price`) |
| `city_coords.json` | City → lat/lon lookup used to geocode stations that lack coordinate columns |

`city_coords.json` can be generated from the GeoNames US postal dataset:

```bash
python scripts/build_city_coords.py   # or see fuel/geocoder.py for the format
```

### Run

```bash
python manage.py migrate
python manage.py runserver
```

---

## API

### `POST /api/route/`

**Request**

```json
{
  "origin": "New York, NY",
  "destination": "Los Angeles, CA"
}
```

Both fields must resolve to US locations. Non-US addresses return a 400 error.

**Response (200)**

```json
{
  "fuel_stops": [
    {
      "name": "SHEETZ #639",
      "address": "I-80 Exit 223, Youngstown, OH",
      "lat": 41.077,
      "lon": -80.680,
      "price_per_gallon": 3.059,
      "gallons": 37.47,
      "cost": 114.63,
      "miles_from_last_stop": 374.7
    }
  ],
  "total_fuel_cost": 762.75,
  "total_distance_miles": 2797.3,
  "route_geojson": { "type": "FeatureCollection", "..." },
  "google_maps_url": "https://www.google.com/maps/dir/..."
}
```

**Error responses**

| Status | Cause |
|--------|-------|
| 400 | Missing/invalid fields, or address outside the US |
| 502 | ORS geocoding or routing service unreachable |

### Interactive docs

With the server running, open [http://localhost:8000/api/docs/](http://localhost:8000/api/docs/) for the Scalar UI, or [http://localhost:8000/api/schema/](http://localhost:8000/api/schema/) for the raw OpenAPI schema.

---

## Architecture

```
routing/
  views.py        — RouteView: parallel geocode → route → plan_stops → response
  ors_client.py   — ORS geocoding + directions, with Redis-backed cache
  serializers.py  — Request/response validation and shaping

fuel/
  loader.py       — Reads fuel_prices.csv once, caches result in-process
  geocoder.py     — city_coords.json lookup for stations without lat/lon columns
  optimizer.py    — plan_stops(): sliding-window fuel cost optimizer
```

### Optimizer algorithm

The optimizer walks the route in 500-mile windows (truck tank range). In each window's **refuel zone** (miles 350–500 of that window), it:

1. Collects the route waypoints in that zone
2. Computes a bounding box around those waypoints, expanded by the 30-mile detour radius
3. Uses a **binary search on a lat-sorted station list** to extract only the ~50–200 candidate stations in that box, instead of scanning all 6,600+
4. Runs haversine checks only on the candidates to find the cheapest reachable station

This reduces the inner loop from O(waypoints × 6,600) to O(waypoints × ~100), making `plan_stops` complete in ~15ms.

### Caching strategy

Two layers:

| Layer | Scope | What's cached |
|-------|-------|---------------|
| Redis (`django-redis`) | Shared, survives restarts | ORS geocoding results, full route GeoJSON — 24h TTL |
| `lru_cache` in `fuel/loader.py` | In-process | Parsed fuel station list — lives for the process lifetime |

If Redis is unavailable the cache block in `settings.py` falls back to Django's `LocMemCache`, so the app degrades gracefully without crashing.

---

## Assignment Requirements — How Each Is Met

| Requirement | Implementation |
|-------------|----------------|
| Accept origin + destination | `RouteRequestSerializer` validates both fields on every request |
| Fetch a driving route | Single `POST /v2/directions/driving-car/geojson` call to ORS per unique route |
| Find cheapest fuel stops | `plan_stops()` in `fuel/optimizer.py` — sliding 500-mile window, cheapest station within 30 miles |
| Use provided CSV data | `fuel/loader.py` reads `fuel_prices.csv`, deduplicates by OPIS ID, resolves city-level coords from `city_coords.json` |
| Return total fuel cost | Summed from `gallons × price` across all stops |
| Return route GeoJSON | Passed through directly from ORS response |
| US-only validation | `ors_client.geocode()` checks `country_a == 'USA'` in the ORS response; non-US addresses return a descriptive 400 |
| Single routing API call | One `get_route()` call per request; subsequent calls for the same pair are served from Redis |
| Proximity-based selection | Haversine distance check, max 30-mile detour (`MAX_STATION_DETOUR_MILES` setting) |
| Performance | Parallel geocoding + Redis cache reduces repeat-request latency from ~3.5s to ~100ms |

---

## Configuration

Vehicle assumptions are set in `settings.py` and can be overridden via environment variables:

| Setting | Default | Meaning |
|---------|---------|---------|
| `VEHICLE_RANGE_MILES` | 500 | Full-tank range in miles |
| `VEHICLE_MPG` | 10 | Fuel efficiency (mpg) |
| `REFUEL_LOWER_PERCENT` | 0.70 | Start looking for fuel at 70% of range |
| `MAX_STATION_DETOUR_MILES` | 30 | Max acceptable detour to a station |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `Django` | Web framework |
| `djangorestframework` | API views, serializers, validation |
| `drf-spectacular` | OpenAPI schema generation |
| `django-redis` | Redis cache backend |
| `requests` | ORS HTTP calls |
| `python-decouple` | `.env` config loading |
