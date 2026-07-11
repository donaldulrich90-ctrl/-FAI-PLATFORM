from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("terrain/interventions/", views.intervention_list, name="intervention_list"),
    path(
        "terrain/interventions/<int:pk>/",
        views.intervention_update,
        name="intervention_update",
    ),
    path("rapports/revendeurs/", views.revendeur_report_list, name="revendeur_report_list"),
    path("rapports/revendeurs/export/excel/", views.revendeur_reports_export_excel, name="revendeur_reports_export_excel"),
    path("rapports/revendeurs/<int:pk>/", views.revendeur_report_detail, name="revendeur_report_detail"),
    path("rapports/revendeurs/<int:pk>/export/excel/", views.revendeur_report_export_excel, name="revendeur_report_export_excel"),
    path("rapports/caisse/export/csv/", views.caisse_export_csv, name="caisse_export_csv"),
    path("finance/", views.finance_dashboard, name="finance_dashboard"),
]
