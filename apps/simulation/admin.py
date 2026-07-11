from django.contrib import admin

from .models import Simulation, SimulationElement, SimulationLink


@admin.register(Simulation)
class SimulationAdmin(admin.ModelAdmin):
    list_display = ["name", "tenant", "created_by", "updated_at"]
    list_filter = ["tenant"]
    search_fields = ["name"]


@admin.register(SimulationElement)
class SimulationElementAdmin(admin.ModelAdmin):
    list_display = ["simulation", "element_type", "label", "lat", "lng"]
    list_filter = ["element_type"]


@admin.register(SimulationLink)
class SimulationLinkAdmin(admin.ModelAdmin):
    list_display = ["simulation", "link_type", "element_a", "element_b"]
