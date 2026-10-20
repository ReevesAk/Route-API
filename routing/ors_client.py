import logging

import requests
from django.core.cache import cache
from django.conf import settings

_BASE = 'https://api.openrouteservice.org'

logger = logging.getLogger(__name__)


def geocode(text: str) -> tuple[float, float]:
    """Return (lat, lon) for a US place-name string via ORS Geocoding API."""
    key = f'ors:geocode:{text.lower().strip()}'
    hit = cache.get(key)
    if hit is not None:
        return tuple(hit)

    logger.info('ORS geocode cache miss', extra={'query': text})
    resp = requests.get(
        f'{_BASE}/geocode/search',
        params={
            'api_key': settings.ORS_API_KEY,
            'text'   : text,
            'size'   : 1,
        },
        timeout=10,
    )
    resp.raise_for_status()
    features = resp.json().get('features', [])
    if not features:
        logger.warning('ORS geocode returned no results', extra={'query': text})
        raise ValueError(f'Could not geocode: {text!r}')

    props = features[0].get('properties', {})
    if props.get('country_a') != 'USA':
        country = props.get('country', 'unknown country')
        logger.warning('Geocoded location outside US', extra={'query': text, 'country': country})
        raise ValueError(
            f'{text!r} resolved to a location in {country}. '
            'Both origin and destination must be within the United States.'
        )

    lon, lat = features[0]['geometry']['coordinates']
    result = (float(lat), float(lon))
    cache.set(key, list(result))
    return result


def get_route(origin: tuple[float, float], dest: tuple[float, float]) -> dict:
    """
    Fetch a driving route from ORS Directions API.
    origin / dest are (lat, lon) tuples.
    Returns a GeoJSON FeatureCollection with LineString geometry.
    """
    key = f'ors:route:{origin[0]:.6f},{origin[1]:.6f}:{dest[0]:.6f},{dest[1]:.6f}'
    hit = cache.get(key)
    if hit is not None:
        return hit

    logger.info('ORS route cache miss', extra={'origin': origin, 'dest': dest})
    o_lat, o_lon = origin
    d_lat, d_lon = dest
    resp = requests.post(
        f'{_BASE}/v2/directions/driving-car/geojson',
        headers={
            'Authorization': settings.ORS_API_KEY,
            'Content-Type' : 'application/json',
        },
        json={'coordinates': [[o_lon, o_lat], [d_lon, d_lat]]},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    cache.set(key, result)
    return result
