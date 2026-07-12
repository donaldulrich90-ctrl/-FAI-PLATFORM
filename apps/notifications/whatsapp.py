"""Service WhatsApp via CallMeBot (https://www.callmebot.com/blog/free-api-whatsapp-messages/)."""
from __future__ import annotations

import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"
_MAX_RETRIES = 3


# ── Message templates ─────────────────────────────────────────────────────────

def msg_bienvenue(nom: str, plan: str, vitesse: str, date_expiration: str) -> str:
    return (
        f"🎉 Bienvenue {nom} !\n"
        f"Connexion Internet FAEST activée.\n"
        f"Plan : {plan} ({vitesse}) jusqu'au {date_expiration}\n"
        f"Problème : +226 64 79 24 70\n"
        f"Merci 🙏 - FAEST EQUIPEMENTS"
    )


def msg_rappel_j7(nom: str, date_expiration: str, plan: str, prix: str) -> str:
    return (
        f"Bonjour {nom} 👋\n"
        f"Votre abonnement Internet FAEST expire dans 7 jours le {date_expiration}.\n"
        f"Plan : {plan} - {prix} XOF/mois\n"
        f"Pour renouveler : +226 64 79 24 70\n"
        f"Merci 🙏 - FAEST EQUIPEMENTS"
    )


def msg_rappel_j1(nom: str, date_expiration: str, prix: str) -> str:
    return (
        f"⚠️ URGENT - Bonjour {nom}\n"
        f"Votre Internet FAEST expire DEMAIN {date_expiration}.\n"
        f"Montant : {prix} XOF\n"
        f"📞 +226 64 79 24 70 / +226 70 76 81 28\n"
        f"💚 FAEST EQUIPEMENTS"
    )


def msg_rappel_j2(nom: str, date_expiration: str, plan: str, prix: str) -> str:
    return (
        f"⏰ Bonjour {nom}\n"
        f"Votre abonnement Internet FAEST expire dans 2 jours le {date_expiration}.\n"
        f"Plan : {plan} - {prix}/mois\n"
        f"Pour renouveler : +226 64 79 24 70\n"
        f"💚 FAEST EQUIPEMENTS"
    )


def msg_suspension(nom: str, date_expiration: str, prix: str) -> str:
    return (
        f"🔴 Bonjour {nom}\n"
        f"Votre abonnement FAEST a expiré le {date_expiration}.\n"
        f"Connexion suspendue.\n"
        f"Pour rétablir : {prix} XOF → +226 64 79 24 70\n"
        f"Merci 🙏 - FAEST"
    )


def msg_renouvellement(nom: str, montant: str, nouvelle_date: str) -> str:
    return (
        f"✅ Bonjour {nom}\n"
        f"Paiement de {montant} XOF reçu.\n"
        f"Abonnement renouvelé jusqu'au {nouvelle_date}.\n"
        f"Bonne navigation ! 🌐 - FAEST EQUIPEMENTS"
    )


def msg_ticket_reponse(ticket_numero: str) -> str:
    return (
        f"✅ Message reçu !\n"
        f"Ticket : {ticket_numero}\n"
        f"Nous traitons votre demande rapidement.\n"
        f"📞 Urgent : +226 64 79 24 70\n"
        f"- FAEST EQUIPEMENTS"
    )


def msg_alerte_frequence_admin(
    nom_antenne: str,
    site: str,
    snr: float | None,
    freq_avant: int,
    freq_apres: int,
    resultat: str,
    heure: str,
) -> str:
    snr_str = f"{snr:.1f} dB" if snr is not None else "N/A"
    return (
        f"📡 ALERTE FRÉQUENCE - {heure}\n"
        f"Antenne : {nom_antenne}\n"
        f"Site : {site}\n"
        f"Changement : {freq_avant} → {freq_apres} MHz\n"
        f"SNR avant : {snr_str}\n"
        f"Résultat : {resultat}\n"
        f"- Faso ISP Manager"
    )


def send_admin_alert(message: str) -> None:
    """Envoie un message WhatsApp au numéro admin configuré (WHATSAPP_ADMIN_NUMBER)."""
    admin_number = getattr(settings, "WHATSAPP_ADMIN_NUMBER", "").strip()
    if not admin_number:
        logger.debug("send_admin_alert: WHATSAPP_ADMIN_NUMBER non configuré — alerte ignorée.")
        return
    svc = WhatsAppService()
    ok, err = svc.send(admin_number, message)
    if not ok:
        logger.warning("send_admin_alert échouée : %s", err)


# ── Service ───────────────────────────────────────────────────────────────────

class WhatsAppService:
    def __init__(self) -> None:
        self.api_key: str = getattr(settings, "WHATSAPP_CALLMEBOT_APIKEY", "")
        self.dry_run: bool = bool(getattr(settings, "WHATSAPP_DRY_RUN", True))

    def send(self, phone: str, message: str, *, tenant_id: int | None = None) -> tuple[bool, str]:
        """Envoie un message WhatsApp. Retourne (succès, message_erreur)."""
        from .models import WhatsAppLog

        phone = phone.strip()
        if phone and not phone.startswith("+"):
            phone = f"+{phone}"

        if self.dry_run:
            logger.info("[WHATSAPP DRY-RUN] → %s : %.120s", phone, message)
            WhatsAppLog.objects.create(
                tenant_id=tenant_id,
                phone=phone,
                message=message[:1000],
                success=True,
                dry_run=True,
            )
            return True, ""

        if not self.api_key:
            err = "WHATSAPP_CALLMEBOT_APIKEY non configuré."
            logger.error(err)
            return False, err

        last_err = ""
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = httpx.get(
                    CALLMEBOT_URL,
                    params={"phone": phone, "text": message, "apikey": self.api_key},
                    timeout=15,
                )
                ok = resp.status_code == 200
                err = "" if ok else f"HTTP {resp.status_code}: {resp.text[:200]}"
                if ok:
                    WhatsAppLog.objects.create(
                        tenant_id=tenant_id,
                        phone=phone,
                        message=message[:1000],
                        success=True,
                        dry_run=False,
                    )
                    return True, ""
                last_err = err
                logger.warning("WhatsApp tentative %s/%s → %s", attempt, _MAX_RETRIES, err)
            except Exception as exc:
                last_err = str(exc)[:255]
                logger.error("WhatsApp erreur tentative %s: %s", attempt, last_err)

        WhatsAppLog.objects.create(
            tenant_id=tenant_id,
            phone=phone,
            message=message[:1000],
            success=False,
            error_message=last_err[:512],
            dry_run=False,
        )
        return False, last_err
