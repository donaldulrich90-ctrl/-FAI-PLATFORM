from django.urls import path

from apps.tenants import views

app_name = "platform"

urlpatterns = [
    path("organisations/", views.tenant_list, name="tenant_list"),
    path("organisations/nouvelle/", views.tenant_create, name="tenant_create"),
    path("organisations/<int:pk>/modifier/", views.tenant_edit, name="tenant_edit"),
    path("organisations/<int:pk>/supprimer/", views.tenant_delete, name="tenant_delete"),
]
