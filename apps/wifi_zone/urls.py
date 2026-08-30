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
    path("revendeur/vente/", views.revendeur_point_de_vente, name="revendeur_point_de_vente"),
    path("revendeur/tickets/", views.revendeur_generate_batch, name="revendeur_generate_batch"),
    path("revendeur/tickets/lot/<int:batch_pk>/imprimer/", views.revendeur_print, name="revendeur_print"),
    path("revendeur/admin/", views.admin_revendeur_list, name="admin_revendeur_list"),
    # PDF
    path("tickets/lot/<int:batch_pk>/pdf/", views.print_batch_pdf, name="print_batch_pdf"),
    path("tickets/pdf/", views.print_tickets_pdf, name="print_tickets_pdf"),
    # Tickets imprimés (listing + sync status)
    path("tickets/imprimes/", views.tickets_imprime_list, name="tickets_imprime_list"),
    # Suppression de tickets
    path("tickets/hotspot/<int:pk>/supprimer/", views.ticket_delete, name="ticket_delete"),
    path("tickets/lot/<int:batch_pk>/supprimer/", views.ticket_batch_delete, name="ticket_batch_delete"),
    # Re-synchronisation ticket
    path("tickets/hotspot/<int:pk>/resync/", views.ticket_resync, name="ticket_resync"),
    # Push manuel vers MikroTik
    path("tickets/hotspot/<int:pk>/push/", views.ticket_push, name="ticket_push"),
    path("tickets/lot/<int:batch_pk>/push/", views.ticket_batch_push, name="ticket_batch_push"),
    path("tickets/hotspot/push-all/", views.ticket_push_all_unsynced, name="ticket_push_all_unsynced"),
    path("tickets/hotspot/<int:pk>/sync-mac/", views.ticket_sync_mac, name="ticket_sync_mac"),
    # Dashboard WiFi Zones (admin uniquement)
    path("zones/", views.zones_dashboard, name="zones_dashboard"),
    path("zones/<int:revendeur_id>/", views.zone_detail_report, name="zone_detail_report"),
    path("zones/<int:revendeur_id>/export/", views.zone_detail_report_csv, name="zone_detail_report_csv"),
    # Rapports spécialisés (gardés pour compatibilité)
    path("zones/<int:revendeur_id>/rapport/", views.zone_daily_report, name="zone_daily_report"),
    path("zones/<int:revendeur_id>/rapport-mensuel/", views.zone_monthly_report, name="zone_monthly_report"),
    path("zones/<int:revendeur_id>/export-jour/", views.zone_daily_report_csv, name="zone_daily_report_csv"),
]
