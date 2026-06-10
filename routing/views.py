import urllib.parse
import requests
from concurrent.futures import ThreadPoolExecutor
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema

from .ors_client import geocode, get_route
from .serializers import RouteRequestSerializer, RouteResponseSerializer
from fuel.optimizer import plan_stops


def _maps_url(origin: str, dest: str, stops: list) -> str:
    parts = [origin] + [f"{s['lat']},{s['lon']}" for s in stops] + [dest]
    path  = '/'.join(urllib.parse.quote(p, safe=',') for p in parts)
    return f'https://www.google.com/maps/dir/{path}'


class RouteView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        request=RouteRequestSerializer,
        responses={200: RouteResponseSerializer},
        summary='Plan cheapest fuel stops for a US road trip',
        description=(
            'Geocodes origin/destination via ORS, fetches the driving route, '
            'then walks the route in 500-mile windows to find the cheapest '
            'diesel stop within 30 miles. Returns stops, total cost, route '
            'GeoJSON, and a Google Maps URL.'
        ),
    )
    def post(self, request):
        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        origin = serializer.validated_data['origin']
        dest   = serializer.validated_data['destination']

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                f_origin = pool.submit(geocode, origin)
                f_dest   = pool.submit(geocode, dest)
            origin_coords = f_origin.result()
            dest_coords   = f_dest.result()
            route_geojson = get_route(origin_coords, dest_coords)
        except requests.exceptions.RequestException as exc:
            return Response(
                {'error': f'Routing service unavailable: {exc}'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        coords = route_geojson['features'][0]['geometry']['coordinates']
        stops, total_miles = plan_stops(coords)

        data = {
            'fuel_stops'          : stops,
            'total_fuel_cost'     : round(sum(s['cost'] for s in stops), 2),
            'total_distance_miles': total_miles,
            'route_geojson'       : route_geojson,
            'google_maps_url'     : _maps_url(origin, dest, stops),
        }
        return Response(RouteResponseSerializer(data).data)
