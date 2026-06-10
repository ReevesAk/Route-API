from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    origin      = serializers.CharField(max_length=255)
    destination = serializers.CharField(max_length=255)


class FuelStopSerializer(serializers.Serializer):
    name                 = serializers.CharField()
    address              = serializers.CharField()
    lat                  = serializers.FloatField()
    lon                  = serializers.FloatField()
    price_per_gallon     = serializers.FloatField()
    gallons              = serializers.FloatField()
    cost                 = serializers.FloatField()
    miles_from_last_stop = serializers.FloatField()


class RouteResponseSerializer(serializers.Serializer):
    fuel_stops           = FuelStopSerializer(many=True)
    total_fuel_cost      = serializers.FloatField()
    total_distance_miles = serializers.FloatField()
    route_geojson        = serializers.DictField()
    google_maps_url      = serializers.CharField()
