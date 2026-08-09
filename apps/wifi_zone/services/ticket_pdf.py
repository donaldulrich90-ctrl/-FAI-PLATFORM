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
FOOTER_H = 10 * mm  # réservé pour la ligne récapitulative en bas de page

PAGE_W, PAGE_H = A4
AVAILABLE_W = PAGE_W - 2 * MARGIN_X
AVAILABLE_H = PAGE_H - 2 * MARGIN_Y - FOOTER_H

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


def _draw_page_footer(
    c: canvas.Canvas,
    page_tickets: list,
    page_first: int,
    page_last: int,
    total: int,
    unit_price: int,
) -> None:
    """Dessine la ligne récapitulative sous les tickets (dans FOOTER_H)."""
    page_count = len(page_tickets)
    page_total = sum(int(t.price_xof) for t in page_tickets)

    # Zone footer : de MARGIN_Y à MARGIN_Y + FOOTER_H
    footer_y = MARGIN_Y + FOOTER_H / 2 - 1.5 * mm

    c.setStrokeColor(COLOR_LGRAY)
    c.setLineWidth(0.3)
    c.line(MARGIN_X, MARGIN_Y + FOOTER_H - 1 * mm, PAGE_W - MARGIN_X, MARGIN_Y + FOOTER_H - 1 * mm)

    unit_str = f"{int(unit_price):,}".replace(",", " ")
    total_str = f"{page_total:,}".replace(",", " ")

    left_label = f"Tickets {page_first}–{page_last} sur {total} au total"
    right_label = f"{page_count} tickets × {unit_str} XOF = {total_str} XOF"

    c.setFont("Helvetica", 6)
    c.setFillColor(COLOR_GRAY)
    c.drawString(MARGIN_X, footer_y, left_label)

    c.setFont("Helvetica-Bold", 6.5)
    c.setFillColor(COLOR_DARK)
    c.drawRightString(PAGE_W - MARGIN_X, footer_y, right_label)


def _draw_ticket(
    c: canvas.Canvas,
    ticket,
    x: float,
    y: float,
    w: float,
    h: float,
    logo: "ImageReader | None",
    ticket_num: int,
    total: int,
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

    # ── Bas : site (centré) + numéro (droite) ────────────────────────────────
    bottom_y = y + pad + 0.5 * mm
    site_label = (ticket.site.name if ticket.site else "")[:18]
    c.setFont("Helvetica", 4.5)
    c.setFillColor(COLOR_LGRAY)
    c.drawString(inner_x, bottom_y, site_label)

    num_str = f"{ticket_num}/{total}"
    c.setFont("Helvetica-Bold", 4.5)
    c.setFillColor(COLOR_GRAY)
    c.drawRightString(x + w - pad, bottom_y, num_str)


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
            global_num = page_idx + slot + 1
            col = slot % COLS
            row = slot // COLS

            x = MARGIN_X + col * TICKET_W
            # tickets start above the footer zone
            y = MARGIN_Y + FOOTER_H + (ROWS - 1 - row) * TICKET_H

            _draw_ticket(c, ticket, x, y, TICKET_W, TICKET_H, logo, global_num, total)

        unit_price = int(page_tickets[0].price_xof) if page_tickets else 0
        _draw_page_footer(
            c, page_tickets,
            page_first=page_idx + 1,
            page_last=page_idx + len(page_tickets),
            total=total,
            unit_price=unit_price,
        )

        c.showPage()

    c.save()
    buf.seek(0)
    return buf.read()
