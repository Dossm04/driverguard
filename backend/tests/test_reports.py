from app import scoring

"""Отчёты (BE-14): сводка по seed, фильтр депо, CSV с BOM, PDF с кириллицей."""


def test_summary_matches_seed(client, seeded, headers):
    r = client.get("/api/v1/reports/summary?period=today", headers=headers).json()
    assert r["totals"]["events"] == 14 and r["totals"]["critical"] == 3
    assert r["totals"]["avg_score"] == 78 and r["totals"]["drivers"] == 6
    assert r["totals"]["avg_zone"] == scoring.zone(78)  # зона — от сервера, одна для всех страниц
    assert len(r["by_driver"]) == 6 and r["by_driver"][0]["events"] >= r["by_driver"][-1]["events"]
    assert [p["weeks_ago"] for p in r["score_trend"]] == list(range(7, -1, -1))
    assert r["score_trend"][-1]["avg_score"] == 78
    assert 1 <= len(r["risky_segments"]) <= 5
    assert sum(t["share_pct"] for t in r["by_type"]) in range(97, 104)

    week = client.get("/api/v1/reports/summary?period=7d", headers=headers).json()
    assert week["totals"]["km"] == 12480 and week["totals"]["trips"] > 0
    assert week["trips"][0]["driver_name"] and week["trips"][0]["vehicle_plate"]


def test_summary_depot_filter(client, seeded, headers):
    depots = client.get("/api/v1/depots", headers=headers).json()
    astana = next(d for d in depots if d["name"] == "Астана")
    r = client.get(
        f"/api/v1/reports/summary?period=7d&depot_id={astana['id']}", headers=headers
    ).json()
    assert r["depot"] == "Астана" and r["totals"]["drivers"] == 3
    assert all(d["depot"] == "Астана" for d in r["by_driver"])
    assert client.get("/api/v1/reports/summary?depot_id=999", headers=headers).status_code == 404


def test_csv_export(client, seeded, headers, viewer_headers):
    resp = client.get("/api/v1/reports/export.csv?period=7d", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "filename*=UTF-8''" in resp.headers["content-disposition"]
    text = resp.content.decode("utf-8")
    assert text.startswith("﻿")
    assert "Иванов А.С." in text and ";" in text and "динамика_score" in text


def test_pdf_export_has_cyrillic_font(client, seeded, headers):
    """«Готово, когда» ШАГ 11: PDF открывается с кириллицей (шрифт DejaVu встроен)."""
    resp = client.get("/api/v1/reports/export.pdf?period=30d", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")
    # Linux использует DejaVu, Windows - Arial. Проверяем встроенный Unicode-шрифт,
    # а не его конкретное семейство.
    from reportlab.pdfbase import pdfmetrics

    from app.report_pdf import FONT

    assert b"/FontFile2" in resp.content and b"/ToUnicode" in resp.content
    assert all(ord(ch) in pdfmetrics.getFont(FONT).face.charWidths for ch in "АстанаӘҚЯё")
    assert len(resp.content) > 5000


def test_csv_line_escapes_formulas():
    """CSV-инъекция: «=…/+…/@…» экранируем апострофом, числа — нет."""
    from app.routers.reports import _csv_line

    assert _csv_line(["=CMD()", -3, "+7 701", "@x", "a;b"]) == "'=CMD();-3;'+7 701;'@x;\"a;b\""
