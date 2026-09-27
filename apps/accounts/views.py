from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy

from apps.core.models import ActivityLog
from django.utils.http import url_has_allowed_host_and_scheme


@login_required
def home_redirect(request: HttpRequest) -> HttpResponse:
    """Après connexion : renvoie selon le rôle métier."""
    user = request.user
    if getattr(user, "is_revendeur", False):
        return redirect("wifi_zone:revendeur_dashboard")
    return redirect("monitoring:dashboard")


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        ActivityLog.log(self.request, ActivityLog.Action.LOGIN, f"Connexion: {self.request.user.username}")
        return response

    def get_success_url(self) -> str:
        nxt = self.request.GET.get("next") or self.request.POST.get("next")
        if nxt and url_has_allowed_host_and_scheme(
            url=nxt,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return nxt
        return str(reverse_lazy("accounts:home"))


class LogoutView(auth_views.LogoutView):
    next_page = reverse_lazy("accounts:login")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            ActivityLog.log(request, ActivityLog.Action.LOGOUT, f"Déconnexion: {request.user.username}")
        return super().dispatch(request, *args, **kwargs)
