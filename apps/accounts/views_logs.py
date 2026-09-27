"""Journal d'activité — visible uniquement par les administrateurs."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.core.models import ActivityLog


@login_required
def activity_log_list(request: HttpRequest) -> HttpResponse:
    """Affiche les logs d'activité. Réservé aux admins."""
    if not (getattr(request.user, "is_admin_role", False) or request.user.is_superuser):
        raise PermissionDenied

    action_filter = request.GET.get("action", "")
    user_filter = request.GET.get("user", "").strip()
    date_filter = request.GET.get("date", "").strip()

    qs = ActivityLog.objects.select_related("user").all()

    if action_filter:
        qs = qs.filter(action=action_filter)
    if user_filter:
        from django.db.models import Q
        qs = qs.filter(
            Q(user__username__icontains=user_filter)
            | Q(user__first_name__icontains=user_filter)
            | Q(user__last_name__icontains=user_filter)
        )
    if date_filter:
        qs = qs.filter(created_at__date=date_filter)

    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))

    context = {
        "logs": page,
        "action_filter": action_filter,
        "user_filter": user_filter,
        "date_filter": date_filter,
        "action_choices": ActivityLog.Action.choices,
        "total_logs": ActivityLog.objects.count(),
    }
    return render(request, "accounts/activity_logs.html", context)
