"""Attache request.tenant à partir de l'utilisateur connecté."""

from typing import Callable

from django.http import HttpRequest, HttpResponse


class TenantMiddleware:
    """Après authentification : request.tenant = user.tenant (ou None pour superuser sans org)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.tenant = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            request.tenant = getattr(user, "tenant", None)
        return self.get_response(request)
