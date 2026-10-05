"""Чистые функции форматирования сообщений (тестируются без Telegram и backend)."""

import html
from datetime import datetime
from zoneinfo import ZoneInfo

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
    "sos": "SOS",
}
SEVERITY_ICON = {"critical": "🔴", "warning": "🟠", "info": "🔵"}
ZONE_ICON = {"ok": "🟢", "warn": "🟡", "danger": "🔴"}
REVIEW_ACTIONS = {"ok": "confirmed", "fp": "false_positive"}


def local_time(value: str | None, tz: str) -> str:
    if not value:
        return "—"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo(tz)).strftime("%d.%m %H:%M")


def map_link(lat: float | None, lon: float | None, gps_valid: bool = True) -> str | None:
    if lat is None or lon is None or not gps_valid:
        return None
    return f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"


def event_title(e: dict) -> str:
    """«Превышение скорости +42 км/ч», «Отвлечение >5 сек» — как в панели (CLAUDE.md, п. 4)."""
    label = EVENT_LABELS.get(e["type"], e["type"])
    value = e.get("value")
    if e["type"] == "speeding" and value is not None:
        return f"{label} +{round(value)} км/ч"
    if e["type"] == "distraction" and value is not None:
        return f"{label} >{round(value)} сек"
    return label


def should_alert(e: dict, critical_types: list[str]) -> bool:
    """BOT-1 + BOT-4: критическое событие одного из типов, выбранных в панели."""
    return e.get("severity") == "critical" and e.get("type") in critical_types


def alert_text(e: dict, tz: str, web_url: str | None = None) -> str:
    esc = html.escape
    icon = SEVERITY_ICON.get(e.get("severity", ""), "⚪")
    lines = [f"{icon} <b>{esc(event_title(e))}</b>"]
    who = esc(e.get("driver_name") or "Водитель не определён")
    if e.get("vehicle_plate"):
        who += f" · <code>{esc(e['vehicle_plate'])}</code>"
    lines.append(f"👤 {who}")
    speed = e.get("speed_kmh")
    speed_txt = f"{round(speed)} км/ч" if speed is not None else "скорость неизвестна"
    lines.append(f"🕒 {local_time(e.get('ts'), tz)} · {speed_txt}")
    if e.get("type") == "sos":  # BOT-2: причина из контекста PWA
        reason = (e.get("context") or {}).get("reason") or "не указана"
        lines.append(f"🆘 Причина: {esc(str(reason))}")
    link = map_link(e.get("lat"), e.get("lon"), e.get("gps_valid", True))
    lines.append(f'📍 <a href="{link}">Открыть на карте</a>' if link else "📍 GPS-координат нет")
    conf = e.get("confidence")
    if conf is not None:
        lines.append(f"Уверенность {round(float(conf) * 100)}%")
    if web_url:
        lines.append(f'<a href="{esc(web_url)}/events">Панель · События</a>')
    return "\n".join(lines)


def alert_keyboard(event_uuid: str, has_phone: bool) -> list[list[tuple[str, str]]]:
    """Ряды кнопок (текст, callback_data) — без зависимости от aiogram."""
    rows: list[list[tuple[str, str]]] = []
    if has_phone:
        rows.append([("📞 Позвонить", f"call:{event_uuid}")])
    rows.append([("✅ Подтвердить", f"ok:{event_uuid}"), ("❌ Ложное", f"fp:{event_uuid}")])
    return rows


def parse_callback(data: str | None) -> tuple[str, str] | None:
    if not data or ":" not in data:
        return None
    action, _, uuid = data.partition(":")
    if action not in ("call", "ok", "fp") or len(uuid) < 8:
        return None
    return action, uuid


def review_footer(status: str, actor: str, when: str) -> str:
    label = "✅ Подтверждено" if status == "confirmed" else "❌ Ложное срабатывание"
    return f"\n\n{label} · {html.escape(actor)} · {when}"


def status_text(summary: dict, devices: list[dict]) -> str:
    v, ev, sc, up = summary["vehicles"], summary["events"], summary["avg_score"], summary["uptime"]
    delta = f" ({ev['delta']:+d} к вчера)" if ev.get("delta") else ""
    lines = [
        "📊 <b>Сегодня</b>",
        f"🚚 Машин онлайн: <b>{v['online']}/{v['total']}</b>",
        f"⚠️ События: <b>{ev['value']}</b>{delta}",
        f"🔴 Критических за 24 ч: <b>{summary['critical_24h']['value']}</b>",
        f"🎯 Средний Score: <b>{sc['value']}</b> (цель {sc.get('target', 80)})",
        f"📡 Аптайм устройств: <b>{up['value']}%</b>",
    ]
    offline = [d for d in devices if not d.get("online")]
    if offline:
        names = ", ".join(
            html.escape(
                f"{d['serial']} · {d['vehicle_plate']}" if d.get("vehicle_plate") else d["serial"]
            )
            for d in offline
        )
        lines.append(f"📵 Офлайн: {names}")
    return "\n".join(lines)


def leaderboard_text(lb: dict) -> str:
    lines = [f"🏆 <b>Лидерборд · {lb.get('period_days', 7)} дней</b>"]
    for r in lb["rows"]:
        icon = ZONE_ICON.get(r.get("zone", ""), "")
        depot = f" ({html.escape(r['depot'])})" if r.get("depot") else ""
        lines.append(f"{r['rank']}. {html.escape(r['name'])} — <b>{r['score']}</b> {icon}{depot}")
    if len(lines) == 1:
        lines.append("Пока нет данных")
    return "\n".join(lines)


def help_text(chat_id: int | str, configured: bool) -> str:
    lines = [
        "🛡 <b>DriverGuard</b> — алерты координатору",
        "Критические события приходят сюда автоматически с кнопками "
        "«Позвонить», «Подтвердить», «Ложное».",
        "",
        "/status — машины онлайн и KPI дня",
        "/leaderboard — Score водителей за 7 дней",
        "",
        f"Chat ID этого чата: <code>{chat_id}</code>",
    ]
    if not configured:
        lines.append("⚠️ Бот не настроен: вставьте этот Chat ID в панели → Настройки → Уведомления.")
    return "\n".join(lines)
