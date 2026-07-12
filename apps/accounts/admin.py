from datetime import date, timedelta

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.conf import settings

from apps.tenants.admin_mixins import TenantScopedAdminMixin

from .models import User


# ── helpers partagés par les trois actions ────────────────────────────────────

def _comment(rev: User) -> str:
    return f"revendeur-{rev.pk}"


def _montant_str(rev: User) -> str:
    return str(int(rev.montant_abonnement_xof)) if rev.montant_abonnement_xof else "—"


def _do_ip_binding(rev: User, binding_type: str, performed_by, ip_address: str | None) -> tuple[bool, str]:
    """Lance ip_binding_upsert sur le MikroTik du revendeur. Retourne (ok, err)."""
    from apps.core.services.routeros_client import RouterOSClient, RouterOSError
    from apps.monitoring.audit import log_router_action

    dry_run = bool(getattr(settings, "ROUTER_CONTROL_DRY_RUN", False))
    cmd_desc = f"ip-binding mac={rev.mac_antenne} type={binding_type}"

    if dry_run:
        log_router_action(
            rev.mikrotik, "ip_binding", target=rev.mac_antenne,
            command_sent=f"[DRY-RUN] {cmd_desc}", success=True, dry_run=True,
            performed_by=performed_by, ip_address=ip_address,
        )
        return True, ""

    try:
        with RouterOSClient(rev.mikrotik) as client:
            ok, err = client.ip_binding_upsert(rev.mac_antenne, binding_type, _comment(rev))
    except RouterOSError as exc:
        ok, err = False, str(exc)[:200]
    except Exception as exc:
        ok, err = False, f"Erreur inattendue : {exc}"[:200]

    log_router_action(
        rev.mikrotik, "ip_binding", target=rev.mac_antenne,
        command_sent=cmd_desc, success=ok,
        error_message="" if ok else err, dry_run=False,
        performed_by=performed_by, ip_address=ip_address,
    )
    return ok, err


# ── actions admin ─────────────────────────────────────────────────────────────

@admin.action(description="✅ Activer — bypass hotspot + WhatsApp")
def activer_revendeur(modeladmin, request, queryset):
    from apps.notifications.whatsapp import WhatsAppService, msg_activation_revendeur

    qs = queryset.filter(
        role=User.Role.REVENDEUR,
        mac_antenne__gt="",
        mikrotik__isnull=False,
        date_expiration__isnull=False,
    ).select_related("mikrotik")

    if not qs.exists():
        modeladmin.message_user(
            request,
            "Aucun revendeur sélectionné avec MAC + MikroTik + date d'expiration configurés.",
            level=messages.WARNING,
        )
        return

    svc = WhatsAppService()
    ok_count = err_count = 0
    ip = request.META.get("REMOTE_ADDR")

    for rev in qs:
        ok, err = _do_ip_binding(rev, "bypassed", request.user, ip)
        if ok:
            rev.statut_revendeur = User.RevendeurStatut.ACTIF
            rev.save(update_fields=["statut_revendeur"])
            if rev.phone:
                exp_str = rev.date_expiration.strftime("%d/%m/%Y")
                svc.send(rev.phone, msg_activation_revendeur(
                    rev.get_full_name() or rev.username, exp_str, _montant_str(rev)
                ), tenant_id=rev.tenant_id)
            ok_count += 1
        else:
            modeladmin.message_user(request, f"{rev} : erreur RouterOS — {err}", level=messages.ERROR)
            err_count += 1

    if ok_count:
        modeladmin.message_user(request, f"{ok_count} revendeur(s) activé(s).")


@admin.action(description="🔴 Suspendre — blocage hotspot + WhatsApp")
def suspendre_revendeur(modeladmin, request, queryset):
    from apps.notifications.whatsapp import WhatsAppService, msg_suspension_revendeur

    qs = queryset.filter(
        role=User.Role.REVENDEUR,
        mac_antenne__gt="",
        mikrotik__isnull=False,
    ).select_related("mikrotik")

    if not qs.exists():
        modeladmin.message_user(
            request,
            "Aucun revendeur sélectionné avec MAC + MikroTik configurés.",
            level=messages.WARNING,
        )
        return

    svc = WhatsAppService()
    ok_count = 0
    ip = request.META.get("REMOTE_ADDR")

    for rev in qs:
        ok, err = _do_ip_binding(rev, "blocked", request.user, ip)
        if ok:
            rev.statut_revendeur = User.RevendeurStatut.SUSPENDU
            rev.save(update_fields=["statut_revendeur"])
            if rev.phone and rev.date_expiration:
                exp_str = rev.date_expiration.strftime("%d/%m/%Y")
                svc.send(rev.phone, msg_suspension_revendeur(
                    rev.get_full_name() or rev.username, exp_str, _montant_str(rev)
                ), tenant_id=rev.tenant_id)
            ok_count += 1
        else:
            modeladmin.message_user(request, f"{rev} : erreur RouterOS — {err}", level=messages.ERROR)

    if ok_count:
        modeladmin.message_user(request, f"{ok_count} revendeur(s) suspendu(s).")


@admin.action(description="🔄 Renouveler +30 jours — déblocage + WhatsApp")
def renouveler_revendeur(modeladmin, request, queryset):
    from apps.notifications.whatsapp import WhatsAppService, msg_renouvellement_revendeur

    qs = queryset.filter(
        role=User.Role.REVENDEUR,
        mac_antenne__gt="",
        mikrotik__isnull=False,
    ).select_related("mikrotik")

    if not qs.exists():
        modeladmin.message_user(
            request,
            "Aucun revendeur sélectionné avec MAC + MikroTik configurés.",
            level=messages.WARNING,
        )
        return

    svc = WhatsAppService()
    ok_count = 0
    nouvelle_date = date.today() + timedelta(days=30)
    ip = request.META.get("REMOTE_ADDR")

    for rev in qs:
        ok, err = _do_ip_binding(rev, "bypassed", request.user, ip)
        if ok:
            rev.date_expiration = nouvelle_date
            rev.statut_revendeur = User.RevendeurStatut.ACTIF
            rev.save(update_fields=["date_expiration", "statut_revendeur"])
            if rev.phone:
                svc.send(rev.phone, msg_renouvellement_revendeur(
                    rev.get_full_name() or rev.username,
                    nouvelle_date.strftime("%d/%m/%Y"),
                ), tenant_id=rev.tenant_id)
            ok_count += 1
        else:
            modeladmin.message_user(request, f"{rev} : erreur RouterOS — {err}", level=messages.ERROR)

    if ok_count:
        modeladmin.message_user(request, f"{ok_count} revendeur(s) renouvelé(s) jusqu'au {nouvelle_date.strftime('%d/%m/%Y')}.")


# ── UserAdmin ─────────────────────────────────────────────────────────────────

@admin.register(User)
class UserAdmin(TenantScopedAdminMixin, DjangoUserAdmin):
    actions = [activer_revendeur, suspendre_revendeur, renouveler_revendeur]

    list_display = (
        "username",
        "email",
        "tenant",
        "role",
        "ticket_prefix",
        "default_commission_percent",
        "statut_revendeur",
        "date_expiration",
        "is_staff",
        "is_active",
    )
    list_filter = ("role", "statut_revendeur", "is_staff", "is_active", "is_platform_operator", "tenant")
    list_select_related = ("tenant", "mikrotik")

    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "Faso ISP",
            {
                "fields": (
                    "tenant",
                    "is_platform_operator",
                    "role",
                    "phone",
                    "default_commission_percent",
                    "ticket_prefix",
                    "site",
                    "balance_xof",
                )
            },
        ),
        (
            "Abonnement revendeur",
            {
                "fields": (
                    "mac_antenne",
                    "mikrotik",
                    "date_expiration",
                    "statut_revendeur",
                    "montant_abonnement_xof",
                ),
                "classes": ("collapse",),
                "description": (
                    "Remplir uniquement pour les utilisateurs avec rôle Revendeur. "
                    "Utiliser les actions en liste pour Activer / Suspendre / Renouveler."
                ),
            },
        ),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "Faso ISP",
            {
                "fields": (
                    "tenant",
                    "is_platform_operator",
                    "role",
                    "phone",
                    "default_commission_percent",
                    "ticket_prefix",
                )
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            ro.append("is_platform_operator")
        return ro
