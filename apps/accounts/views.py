from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
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
