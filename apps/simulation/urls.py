from django.urls import path

from . import views

app_name = "simulation"

urlpatterns = [
    path("", views.simulation_list, name="simulation_list"),
    path("nouvelle/", views.simulation_create, name="simulation_create"),
    path("<int:pk>/", views.simulation_detail, name="simulation_detail"),
    path("<int:pk>/api/load/", views.simulation_api_load, name="simulation_api_load"),
    path("<int:pk>/api/save/", views.simulation_api_save, name="simulation_api_save"),
]
