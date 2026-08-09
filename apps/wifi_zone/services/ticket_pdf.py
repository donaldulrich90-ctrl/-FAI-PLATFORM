"""
Génération PDF de lots de tickets Wi-Fi Zone.
50 tickets par feuille A4 (5 colonnes × 10 lignes), strictement N&B/niveaux de gris.
Chaque ticket : code texte + durée + prix + logo FAEST.
Lignes de découpe en pointillés sur toutes les bordures.
"""
from __future__ import annotations

import io
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# ── Mise en page 50 tickets / A4 ─────────────────────────────────────────────
COLS = 5
ROWS = 10
MARGIN_X = 5 * mm
MARGIN_Y = 5 * mm

PAGE_W, PAGE_H = A4
AVAILABLE_W = PAGE_W - 2 * MARGIN_X
AVAILABLE_H = PAGE_H - 2 * MARGIN_Y

TICKET_W = AVAILABLE_W / COLS
TICKET_H = AVAILABLE_H / ROWS

# Couleurs N&B uniquement
COLOR_BLACK   = colors.black
COLOR_WHITE   = colors.white
COLOR_DARK    = colors.HexColor("#1a1a1a")
COLOR_GRAY    = colors.HexColor("#555555")
COLOR_LGRAY   = colors.HexColor("#999999")
COLOR_VLIGHT  = colors.HexColor("#eeeeee")

DURATION_LABELS = {
    "3h":  "3 Heures",
    "1d":  "24 Heures",
    "1w":  "7 Jours",
    "30j": "30 Jours",
}


def _load_logo() -> "ImageReader | None":
    """Charge le logo FAEST si disponible dans static/img/faest_logo.png."""
    try:
        from django.conf import settings
        logo_path = os.path.join(settings.BASE_DIR, "static", "img", "faest_logo.png")
        if os.path.exists(logo_path):
            return ImageReader(logo_path)
    except Exception:
        pass
    return None


def _draw_cut_lines(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    """Dessine la bordure de découpe en pointillés N&B."""
    c.setStrokeColor(COLOR_GRAY)
    c.setLineWidth(0.3)
    c.setDash(2, 2)
    c.rect(x, y, w, h, fill=0, stroke=1)
    c.setDash()


def _draw_ticket(
    c: canvas.Canvas,
    ticket,
    x: float,
    y: float,
    w: float,
    h: float,
    logo: "ImageReader | None",
) -> None:
    """Dessine un ticket dans le rectangle (x, y, w, h) en N&B strict."""
    pad = 1.5 * mm

    # Fond blanc
    c.setFillColor(COLOR_WHITE)
    c.rect(x, y, w, h, fill=1, stroke=0)

    # Bordure de découpe
    _draw_cut_lines(c, x, y, w, h)

    inner_x = x + pad
    inner_top = y + h - pad

    # ── Logo ou texte FAEST ───────────────────────────────────────────────────
    logo_h = 4 * mm
    if logo is not None:
        try:
            logo_w = logo_h * 3  # ratio 3:1 approximatif
            c.drawImage(
                logo, inner_x, inner_top - logo_h,
                width=logo_w, height=logo_h,
                mask="auto", preserveAspectRatio=True,
            )
        except Exception:
            logo = None  # fallback texte

    if logo is None:
        c.setFont("Helvetica-Bold", 5.5)
        c.setFillColor(COLOR_DARK)
        c.drawString(inner_x, inner_top - 4 * mm, "FAEST")

    # Prix (coin droit haut)
    prix_str = f"{int(ticket.price_xof):,} XOF".replace(",", " ")
    c.setFont("Helvetica-Bold", 5)
    c.setFillColor(COLOR_DARK)
    c.drawRightString(x + w - pad, inner_top - 4 * mm, prix_str)

    # Séparateur fin sous l'en-tête
    sep_y = inner_top - 5.5 * mm
    c.setStrokeColor(COLOR_LGRAY)
    c.setLineWidth(0.2)
    c.line(inner_x, sep_y, x + w - pad, sep_y)

    # ── Code ─────────────────────────────────────────────────────────────────
    code_y = sep_y - 6 * mm
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(COLOR_BLACK)
    c.drawCentredString(x + w / 2, code_y, ticket.code)

    # ── Durée ────────────────────────────────────────────────────────────────
    duration_label = DURATION_LABELS.get(ticket.duration, ticket.duration)
    c.setFont("Helvetica", 5)
    c.setFillColor(COLOR_GRAY)
    c.drawCentredString(x + w / 2, code_y - 4 * mm, duration_label)

    # ── Site (bas) ───────────────────────────────────────────────────────────
    site_label = (ticket.site.name if ticket.site else "")[:22]
    c.setFont("Helvetica", 4.5)
    c.setFillColor(COLOR_LGRAY)
    c.drawCentredString(x + w / 2, y + pad + 0.5 * mm, site_label)


def generate_tickets_pdf(tickets: list, title: str = "Tickets Wi-Fi Zone") -> bytes:
    """
    Génère un PDF N&B avec 50 tickets par page A4 (5×10).
    `tickets` : queryset ou liste de Ticket avec .code, .duration, .price_xof, .site.
    Retourne les bytes du PDF.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    logo = _load_logo()
    per_page = COLS * ROWS
    ticket_list = list(tickets)
    total = len(ticket_list)

    for page_idx in range(0, max(1, total), per_page):
        page_tickets = ticket_list[page_idx: page_idx + per_page]

        for slot, ticket in enumerate(page_tickets):
            col = slot % COLS
            row = slot // COLS

            x = MARGIN_X + col * TICKET_W
            y = PAGE_H - MARGIN_Y - (row + 1) * TICKET_H

            _draw_ticket(c, ticket, x, y, TICKET_W, TICKET_H, logo)

        c.showPage()

    c.save()
    buf.seek(0)
    return buf.read()
