from django.urls import path

from . import views
from . import views_users

app_name = "accounts"

urlpatterns = [
    path("connexion/", views.LoginView.as_view(), name="login"),
    path("deconnexion/", views.LogoutView.as_view(), name="logout"),
    path("accueil/", views.home_redirect, name="home"),

    # ── Gestion des utilisateurs ──────────────────────────────
    path("utilisateurs/", views_users.user_list, name="user_list"),
    path("utilisateurs/creer/", views_users.user_create, name="user_create"),
    path("utilisateurs/<int:pk>/modifier/", views_users.user_edit, name="user_edit"),
    path("utilisateurs/<int:pk>/toggle/", views_users.user_toggle_active, name="user_toggle_active"),
    path("utilisateurs/<int:pk>/supprimer/", views_users.user_delete, name="user_delete"),
]
