from rest_framework import serializers

# Letters (any script), digits, whitespace and the punctuation real addresses
# use: "St. Louis, MO", "Coeur d'Alene, ID", "123 Main St #4, Winston-Salem, NC".
# Requires at least one letter or digit; rejects control characters and markup.
ADDRESS_PATTERN = r"^(?=.*[^\W_])[\w .,'#&()/-]+$"


def _address_field(label: str) -> serializers.RegexField:
    return serializers.RegexField(
        ADDRESS_PATTERN,
        min_length=2,
        max_length=200,
        error_messages={'invalid': f'Enter a valid US {label}, e.g. "Chicago, IL".'},
    )


class RouteRequestSerializer(serializers.Serializer):
    origin      = _address_field('origin')
    destination = _address_field('destination')

    def validate(self, attrs):
        if attrs['origin'].casefold() == attrs['destination'].casefold():
            raise serializers.ValidationError(
                {'destination': 'Destination must be different from origin.'}
            )
        return attrs


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


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['ok', 'degraded'])
    cache  = serializers.ChoiceField(choices=['ok', 'unreachable'])
