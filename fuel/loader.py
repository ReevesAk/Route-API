import csv
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from .geocoder import city_to_coords


def _get(row: dict, *keys: str) -> str:
    for k in keys:
        v = row.get(k, '').strip()
        if v:
            return v
    return ''


@lru_cache(maxsize=1)
def load_stations() -> list[dict]:
    """
    Load and deduplicate fuel_prices.csv.
    Stations without lat/lon columns fall back to geocoder for city-level coords.
    Returns ~6600 unique station dicts.
    """
    path = Path(settings.BASE_DIR) / 'fuel_prices.csv'
    seen: set[str] = set()
    stations: list[dict] = []

    with open(path, encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [h.strip() for h in (reader.fieldnames or [])]
        for raw in reader:
            row = {k.strip(): v.strip() for k, v in raw.items()}

            sid = _get(row, 'OPIS Truckstop ID', 'OPIS_TRUCKSTOP_ID', 'ID')
            if not sid or sid in seen:
                continue
            seen.add(sid)

            city  = _get(row, 'City', 'CITY')
            state = _get(row, 'State', 'STATE')

            try:
                price = float(_get(row, 'Retail Price', 'RETAIL_PRICE', 'Price'))
            except ValueError:
                continue

            try:
                lat = float(_get(row, 'Latitude', 'LAT', 'lat'))
                lon = float(_get(row, 'Longitude', 'LON', 'lng', 'lon'))
            except ValueError:
                coords = city_to_coords(city, state) if city and state else None
                if coords is None:
                    continue
                lat, lon = coords

            stations.append({
                'id'     : sid,
                'name'   : _get(row, 'Truckstop Name', 'TRUCKSTOP_NAME', 'Name'),
                'address': _get(row, 'Address', 'ADDRESS'),
                'city'   : city,
                'state'  : state,
                'lat'    : lat,
                'lon'    : lon,
                'price'  : price,
            })

    return stations
