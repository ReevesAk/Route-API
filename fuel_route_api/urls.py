from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from .scalar import scalar_ui

urlpatterns = [
    path('admin/',      admin.site.urls),
    path('api/',        include('routing.urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/',   scalar_ui,                    name='docs'),
]
