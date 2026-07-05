"""
Génération PDF de lots de tickets Wi-Fi Zone.
Chaque ticket : code texte + QR code + durée + prix + site.
"""
from __future__ import annotations

import io
import qrcode
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


TICKET_W = 9 * cm
TICKET_H = 5 * cm
COLS = 2
ROWS = 5
MARGIN_X = 0.75 * cm
MARGIN_Y = 0.75 * cm
GAP_X = 0.5 * cm
GAP_Y = 0.4 * cm

DURATION_LABELS = {
    "3h": "3 Heures",
    "1d": "24 Heures",
    "1w": "7 Jours",
    "30j": "30 Jours",
}


def _qr_image(data: str, size_px: int = 120) -> ImageReader:
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def generate_tickets_pdf(tickets: list, title: str = "Tickets Wi-Fi Zone") -> bytes:
    """
    Génère un PDF avec tous les tickets.
    `tickets` : queryset ou liste de Ticket avec .code, .duration, .price_xof, .site.
    Retourne les bytes du PDF.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4

    per_page = COLS * ROWS
    ticket_list = list(tickets)
    total = len(ticket_list)

    for page_idx in range(0, max(1, total), per_page):
        page_tickets = ticket_list[page_idx: page_idx + per_page]

        # En-tête de page
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(colors.HexColor("#10b981"))
        c.drawCentredString(page_w / 2, page_h - 0.5 * cm, title)

        for slot, ticket in enumerate(page_tickets):
            col = slot % COLS
            row = slot // COLS

            x = MARGIN_X + col * (TICKET_W + GAP_X)
            y = page_h - 1.2 * cm - (row + 1) * TICKET_H - row * GAP_Y

            # Fond du ticket
            c.setFillColor(colors.HexColor("#0f172a"))
            c.roundRect(x, y, TICKET_W, TICKET_H, 6, fill=1, stroke=0)

            # Bordure
            c.setStrokeColor(colors.HexColor("#1e293b"))
            c.setLineWidth(1)
            c.roundRect(x, y, TICKET_W, TICKET_H, 6, fill=0, stroke=1)

            # QR code (côté gauche)
            qr_size = 3.2 * cm
            qr_x = x + 0.25 * cm
            qr_y = y + (TICKET_H - qr_size) / 2
            try:
                qr = _qr_image(ticket.code)
                c.drawImage(qr, qr_x, qr_y, width=qr_size, height=qr_size, mask="auto")
            except Exception:
                pass

            text_x = qr_x + qr_size + 0.3 * cm
            text_right = x + TICKET_W - 0.2 * cm

            # Durée
            duration_label = DURATION_LABELS.get(ticket.duration, ticket.duration)
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(colors.HexColor("#10b981"))
            c.drawString(text_x, y + TICKET_H - 0.7 * cm, duration_label)

            # Prix
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.HexColor("#94a3b8"))
            prix_str = f"{int(ticket.price_xof):,} XOF".replace(",", " ")
            c.drawRightString(text_right, y + TICKET_H - 0.7 * cm, prix_str)

            # Code
            c.setFont("Helvetica-Bold", 13)
            c.setFillColor(colors.white)
            c.drawString(text_x, y + TICKET_H / 2 - 0.1 * cm, ticket.code)

            # Site
            site_label = ticket.site.name if ticket.site else ""
            c.setFont("Helvetica", 7)
            c.setFillColor(colors.HexColor("#64748b"))
            c.drawString(text_x, y + 0.4 * cm, site_label[:30])

            # Ligne de séparation tirets (perfo)
            c.setDash(2, 3)
            c.setStrokeColor(colors.HexColor("#334155"))
            c.setLineWidth(0.5)
            if col < COLS - 1:
                mid_x = x + TICKET_W + GAP_X / 2
                c.line(mid_x, y, mid_x, y + TICKET_H)
            c.setDash()

        c.showPage()

    c.save()
    buf.seek(0)
    return buf.read()
