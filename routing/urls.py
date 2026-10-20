from django.urls import path

from .views import HealthView, RouteView

urlpatterns = [
    path('health/', HealthView.as_view(), name='health'),
    path('route/',  RouteView.as_view(),  name='route'),
]
