from django.urls import path

from . import views

app_name = "wifi_zone"

urlpatterns = [
    path("revendeur/", views.revendeur_dashboard, name="revendeur_dashboard"),
    path("tickets/lot/<int:batch_pk>/pdf/", views.print_batch_pdf, name="print_batch_pdf"),
    path("tickets/pdf/", views.print_tickets_pdf, name="print_tickets_pdf"),
]
