"""PDF-отчёт по парку (BE-14, US-8): reportlab, кириллица через DejaVu Sans.

Шрифт берётся из системы (пакет fonts-dejavu) или из PDF_FONT_PATH; без шрифта
с кириллицей отчёт честно не строится (503), а не печатает квадраты.
"""

import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Polygon, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"
_FONT_DIRS = [
    Path(os.environ.get("PDF_FONT_PATH", "")),
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/dejavu"),
    Path("/usr/local/share/fonts"),
]
# Палитра печати — светлая тема дизайн-системы (CLAUDE.md)
ACCENT = colors.HexColor("#2563EB")
TXT = colors.HexColor("#0F172A")
MUT = colors.HexColor("#64748B")
LINE = colors.HexColor("#E4E9F2")
CARD = colors.HexColor("#F4F6FB")
OK = colors.HexColor("#16A34A")
WARN = colors.HexColor("#D97706")
DANGER = colors.HexColor("#DC2626")
ZONE_COLORS = {"ok": OK, "warn": WARN, "danger": DANGER}

PERIOD_LABELS = {"today": "Сегодня", "7d": "7 дней", "30d": "30 дней"}
EVENT_LABELS = {
    "microsleep": "Засыпание за рулём",
    "distraction": "Отвлечение",
    "phone": "Телефон за рулём",
    "smoking": "Курение",
    "seatbelt": "Ремень не пристёгнут",
    "speeding": "Превышение скорости",
    "fatigue": "Усталость (PERCLOS)",
    "head_nod": "Клевок головой",
    "camera_sabotage": "Саботаж камеры",
    "harsh_braking": "Резкое торможение",
    "yawn": "Возможный зевок",
    "rest_started": "Отдых начат",
    "rest_ended": "Отдых завершён",
    "camera_unavailable": "Лицо или глаза не видны",
    "sos": "SOS",
}


class FontNotFound(RuntimeError):
    pass


def register_fonts() -> None:
    """Регистрирует DejaVu Sans один раз; без него — FontNotFound."""
    if FONT in pdfmetrics.getRegisteredFontNames():
        return
    for directory in _FONT_DIRS:
        regular = directory / "DejaVuSans.ttf"
        bold = directory / "DejaVuSans-Bold.ttf"
        if regular.is_file():
            pdfmetrics.registerFont(TTFont(FONT, str(regular)))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold if bold.is_file() else regular)))
            return
    # Windows: системный Arial содержит кириллицу; путь не зависит от имени пользователя.
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    regular = windows_fonts / "arial.ttf"
    bold = windows_fonts / "arialbd.ttf"
    if regular.is_file():
        pdfmetrics.registerFont(TTFont(FONT, str(regular)))
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold if bold.is_file() else regular)))
        return
    raise FontNotFound(
        "Шрифт с кириллицей не найден: установите fonts-dejavu или задайте PDF_FONT_PATH"
    )


def _logo() -> Drawing:
    """Векторный логотип: щит + «DriverGuard / Fleet Safety» (в web/public растра нет)."""
    d = Drawing(160, 34)
    shield = Polygon([4, 30, 30, 30, 30, 14, 17, 3, 4, 14], fillColor=ACCENT, strokeColor=None)
    d.add(shield)
    d.add(
        Polygon([12, 22, 22, 22, 22, 15, 17, 10, 12, 15], fillColor=colors.white, strokeColor=None)
    )
    d.add(String(38, 18, "DriverGuard", fontName=FONT_BOLD, fontSize=14, fillColor=TXT))
    d.add(String(38, 5, "Fleet Safety", fontName=FONT, fontSize=8.5, fillColor=MUT))
    return d


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "h1": ParagraphStyle("h1", fontName=FONT_BOLD, fontSize=16, leading=20, textColor=TXT),
        "h2": ParagraphStyle(
            "h2", fontName=FONT_BOLD, fontSize=11.5, leading=15, textColor=TXT, spaceBefore=8
        ),
        "muted": ParagraphStyle("muted", fontName=FONT, fontSize=9, leading=12, textColor=MUT),
        "cell": ParagraphStyle("cell", fontName=FONT, fontSize=9, leading=11.5, textColor=TXT),
        "kpi_value": ParagraphStyle(
            "kpi_value", fontName=FONT_BOLD, fontSize=18, leading=22, textColor=TXT
        ),
        "kpi_title": ParagraphStyle(
            "kpi_title", fontName=FONT, fontSize=8.5, leading=11, textColor=MUT, alignment=TA_LEFT
        ),
    }


def _table(rows: list[list], widths: list[float], zebra: bool = True) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), FONT),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if zebra:
        for i in range(2, len(rows), 2):
            style.append(("BACKGROUND", (0, i), (-1, i), CARD))
    t.setStyle(TableStyle(style))
    return t


def _fmt_dt(value: str | datetime | None) -> str:
    if not value:
        return "—"
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt.strftime("%d.%m %H:%M")


def build_pdf(report: dict) -> bytes:
    """Собирает PDF из словаря /reports/summary (тот же контракт, что и у панели)."""
    register_fonts()
    st = _styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="DriverGuard — отчёт по парку",
        author="DriverGuard",
    )
    width = A4[0] - 32 * mm
    totals = report["totals"]
    depot = report.get("depot") or "все депо"
    story: list = [
        _logo(),
        Spacer(1, 4),
        Paragraph("Отчёт по парку", st["h1"]),
        Paragraph(
            f"Период: {PERIOD_LABELS.get(report['period'], report['period'])} · "
            f"Депо: {escape(depot)} · "
            f"Сформирован {_fmt_dt(report['generated_at'])} UTC",
            st["muted"],
        ),
        Spacer(1, 8),
    ]

    # KPI-плитки
    kpis = [
        ("События", str(totals["events"])),
        ("Критические", str(totals["critical"])),
        ("Пробег, км", f"{totals['km']:,}".replace(",", " ")),
        ("Средний Score", str(totals["avg_score"])),
        ("Рейсов", str(totals["trips"])),
    ]
    kpi_row = [
        [Paragraph(v, st["kpi_value"]), Paragraph(title, st["kpi_title"])] for title, v in kpis
    ]
    kpi_table = Table(
        [[Table([[cell[0]], [cell[1]]], colWidths=[width / 5 - 8]) for cell in kpi_row]],
        colWidths=[width / 5] * 5,
    )
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story += [kpi_table, Spacer(1, 6)]

    # События по типам
    story.append(Paragraph("События по типам", st["h2"]))
    rows = [["Тип", "Событий", "Доля"]] + [
        [EVENT_LABELS.get(t["type"], t["type"]), str(t["count"]), f"{t['share_pct']}%"]
        for t in report["by_type"]
    ]
    if len(rows) == 1:
        rows.append(["—", "0", "0%"])
    story.append(_table(rows, [width * 0.6, width * 0.2, width * 0.2]))

    # Водители
    story.append(Paragraph("Водители", st["h2"]))
    drv_rows = [["Водитель", "Депо", "Событий", "Критич.", "Score", "Км"]]
    for d in report["by_driver"]:
        drv_rows.append(
            [
                d["name"],
                d["depot"] or "—",
                str(d["events"]),
                str(d["critical"]),
                str(d["score"]),
                str(d["km"]),
            ]
        )
    drv_table = _table(
        drv_rows,
        [width * 0.3, width * 0.2, width * 0.125, width * 0.125, width * 0.125, width * 0.125],
    )
    for i, d in enumerate(report["by_driver"], start=1):
        drv_table.setStyle(
            TableStyle(
                [
                    ("TEXTCOLOR", (4, i), (4, i), ZONE_COLORS.get(d["zone"], TXT)),
                    ("FONTNAME", (4, i), (4, i), FONT_BOLD),
                ]
            )
        )
    story.append(drv_table)

    # Рискованные участки
    story.append(Paragraph("Рискованные участки трассы (кластеры событий)", st["h2"]))
    seg_rows = [["№", "Координаты", "Событий", "Критич.", "Основной тип"]]
    for i, seg in enumerate(report["risky_segments"], start=1):
        seg_rows.append(
            [
                str(i),
                f"{seg['lat']:.3f}, {seg['lon']:.3f}",
                str(seg["events"]),
                str(seg["critical"]),
                EVENT_LABELS.get(seg["top_type"], seg["top_type"]),
            ]
        )
    if len(seg_rows) == 1:
        seg_rows.append(["—", "нет событий с координатами", "", "", ""])
    story.append(
        _table(seg_rows, [width * 0.08, width * 0.3, width * 0.17, width * 0.15, width * 0.3])
    )

    # Рейсы
    story.append(Paragraph(f"Рейсы (последние {min(len(report['trips']), 30)})", st["h2"]))
    trip_rows = [["№", "Водитель", "Машина", "Начало (UTC)", "Завершение (UTC)", "Км", "Событий"]]
    for t in report["trips"][:30]:
        trip_rows.append(
            [
                str(t["id"]),
                t["driver_name"],
                t["vehicle_plate"],
                _fmt_dt(t["started_at"]),
                _fmt_dt(t["ended_at"]),
                str(t["km"]),
                str(t["events"]),
            ]
        )
    if len(trip_rows) == 1:
        trip_rows.append(["—", "рейсов за период нет", "", "", "", "", ""])
    story.append(
        _table(
            trip_rows,
            [
                width * 0.07,
                width * 0.23,
                width * 0.17,
                width * 0.15,
                width * 0.15,
                width * 0.1,
                width * 0.13,
            ],
        )
    )
    story += [
        Spacer(1, 10),
        Paragraph(
            "Score = clamp(40..100, 100 − Σ(вес × модификатор скорости) × 7/дней × 0.8 "
            "+ бонус серии ≤10). "
            "Учитываются только подтверждённые и неоспоренные события.",
            st["muted"],
        ),
    ]
    doc.build(story)
    return buf.getvalue()
