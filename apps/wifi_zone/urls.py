from django.urls import path

from . import views

app_name = "wifi_zone"

urlpatterns = [
    # Clients connectés (hotspot actifs)
    path("clients/", views.clients_list, name="clients_list"),
    path("clients/api/", views.clients_api, name="clients_api"),
    path("clients/disconnect/", views.client_disconnect, name="client_disconnect"),
    path("clients/<str:username>/", views.client_detail, name="client_detail"),
    # Abonnés domicile
    path("abonnes/", views.abonne_list, name="abonne_list"),
    path("abonnes/<int:pk>/", views.abonne_detail, name="abonne_detail"),
    path("abonnes/<int:pk>/action/", views.abonne_action, name="abonne_action"),
    # Tickets plainte
    path("tickets/", views.ticket_plainte_list, name="ticket_plainte_list"),
    path("tickets/<int:pk>/update/", views.ticket_plainte_update, name="ticket_plainte_update"),
    path("tickets/<int:pk>/reply/", views.ticket_plainte_reply, name="ticket_plainte_reply"),
    # Webhook WhatsApp
    path("webhook/whatsapp/", views.whatsapp_webhook, name="whatsapp_webhook"),
    # Revendeur
    path("revendeur/", views.revendeur_dashboard, name="revendeur_dashboard"),
    path("revendeur/tickets/", views.revendeur_generate_batch, name="revendeur_generate_batch"),
    path("revendeur/tickets/lot/<int:batch_pk>/imprimer/", views.revendeur_print, name="revendeur_print"),
    path("revendeur/admin/", views.admin_revendeur_list, name="admin_revendeur_list"),
    # PDF
    path("tickets/lot/<int:batch_pk>/pdf/", views.print_batch_pdf, name="print_batch_pdf"),
    path("tickets/pdf/", views.print_tickets_pdf, name="print_tickets_pdf"),
]
