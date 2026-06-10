import json
from functools import lru_cache
from pathlib import Path
from django.conf import settings


@lru_cache(maxsize=1)
def _load_index() -> dict:
    path = Path(settings.BASE_DIR) / 'city_coords.json'
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    index = {}
    for entry in data:
        key = (entry['city'].lower().strip(), entry['state_id'].upper().strip())
        index[key] = (float(entry['lat']), float(entry['lng']))
    return index


def city_to_coords(city: str, state: str) -> tuple[float, float] | None:
    """Return (lat, lon) for a US city/state, or None if not found."""
    return _load_index().get((city.lower().strip(), state.upper().strip()))
