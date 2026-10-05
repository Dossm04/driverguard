"""Форматирование сообщений бота — без Telegram и backend (план ШАГ 12: «тесты форматирования»)."""

from dg_bot import format as fmt

EVENT = {
    "uuid": "3f2b7f1e-7d0a-4b5e-9c2a-1e6f9d8c7b6a",
    "type": "microsleep",
    "severity": "critical",
    "confidence": 0.92,
    "ts": "2026-09-03T09:32:00+00:00",
    "lat": 51.1,
    "lon": 71.4,
    "gps_valid": True,
    "speed_kmh": 84.4,
    "value": None,
    "clip_key": None,
    "status": "new",
    "driver_name": "Иванов А.С.",
    "vehicle_plate": "KZ 4521 AB",
    "driver_phone": "+77012441832",
}


def test_alert_text_microsleep_has_all_fields():
    text = fmt.alert_text(EVENT, "Asia/Almaty", "http://localhost:3000")
    assert "🔴 <b>Засыпание за рулём</b>" in text
    assert "Иванов А.С." in text and "<code>KZ 4521 AB</code>" in text
    assert "03.09 14:32" in text  # 09:32 UTC → Астана (UTC+5)
    assert "84 км/ч" in text
    assert 'href="https://maps.google.com/?q=51.10000,71.40000"' in text
    assert "Уверенность 92%" in text
    assert "http://localhost:3000/events" in text


def test_alert_text_escapes_html_and_handles_missing_data():
    e = {
        **EVENT,
        "driver_name": "<b>x</b>",
        "vehicle_plate": None,
        "speed_kmh": None,
        "gps_valid": False,
    }
    text = fmt.alert_text(e, "Asia/Almaty")
    assert "&lt;b&gt;x&lt;/b&gt;" in text and "<b>x</b>" not in text
    assert "скорость неизвестна" in text and "GPS-координат нет" in text
    assert "<code>" not in text


def test_event_titles_follow_panel_wording():
    assert (
        fmt.event_title({**EVENT, "type": "speeding", "value": 42})
        == "Превышение скорости +42 км/ч"
    )
    assert fmt.event_title({**EVENT, "type": "distraction", "value": 5}) == "Отвлечение >5 сек"
    assert fmt.event_title({**EVENT, "type": "unknown_type"}) == "unknown_type"


def test_sos_alert_shows_reason_from_context():
    sos = {**EVENT, "type": "sos", "context": {"reason": "Плохо себя чувствую"}}
    assert "🆘 Причина: Плохо себя чувствую" in fmt.alert_text(sos, "Asia/Almaty")
    assert "Причина: не указана" in fmt.alert_text({**EVENT, "type": "sos"}, "Asia/Almaty")


def test_should_alert_is_critical_and_type_from_panel():
    types = ["microsleep", "phone", "camera_sabotage", "sos"]
    assert fmt.should_alert(EVENT, types)
    assert not fmt.should_alert({**EVENT, "severity": "warning", "type": "phone"}, types)
    assert not fmt.should_alert({**EVENT, "type": "speeding"}, types)


def test_keyboard_rows_and_callback_parsing():
    rows = fmt.alert_keyboard(EVENT["uuid"], has_phone=True)
    assert rows[0] == [("📞 Позвонить", f"call:{EVENT['uuid']}")]
    assert [d for _, d in rows[1]] == [f"ok:{EVENT['uuid']}", f"fp:{EVENT['uuid']}"]
    assert len(fmt.alert_keyboard(EVENT["uuid"], has_phone=False)) == 1
    assert all(len(d.encode()) <= 64 for row in rows for _, d in row)  # лимит Telegram
    assert fmt.parse_callback(f"fp:{EVENT['uuid']}") == ("fp", EVENT["uuid"])
    assert fmt.parse_callback("nope") is None and fmt.parse_callback("zz:abcdefgh") is None
    assert fmt.parse_callback(None) is None


def test_status_text_matches_summary_figures():
    summary = {
        "vehicles": {"online": 5, "total": 6},
        "events": {"value": 14, "prev": 11, "delta": 3},
        "critical_24h": {"value": 3},
        "avg_score": {"value": 78, "target": 80},
        "uptime": {"value": 98.2},
    }
    devices = [
        {"serial": "DG-0001", "online": True, "vehicle_plate": "KZ 4521 AB"},
        {"serial": "DG-0006", "online": False, "vehicle_plate": "KZ 9012 EF"},
    ]
    text = fmt.status_text(summary, devices)
    assert "<b>5/6</b>" in text and "<b>14</b> (+3 к вчера)" in text
    assert "<b>3</b>" in text and "<b>78</b> (цель 80)" in text and "98.2%" in text
    assert "📵 Офлайн: DG-0006 · KZ 9012 EF" in text


def test_leaderboard_and_help_texts():
    lb = {
        "period_days": 7,
        "rows": [
            {"rank": 1, "name": "Ким С.В.", "score": 95, "zone": "ok", "depot": "Астана"},
            {"rank": 6, "name": "Иванов А.С.", "score": 55, "zone": "danger", "depot": "Астана"},
        ],
    }
    text = fmt.leaderboard_text(lb)
    assert "1. Ким С.В. — <b>95</b> 🟢 (Астана)" in text and "6. Иванов А.С. — <b>55</b> 🔴" in text
    assert "Пока нет данных" in fmt.leaderboard_text({"rows": []})
    unconfigured = fmt.help_text(123, configured=False)
    assert "<code>123</code>" in unconfigured and "не настроен" in unconfigured
    assert "не настроен" not in fmt.help_text(123, configured=True)


def test_review_footer():
    footer = fmt.review_footer("false_positive", "Айгерим <К>", "03.09 14:35")
    assert footer == "\n\n❌ Ложное срабатывание · Айгерим &lt;К&gt; · 03.09 14:35"
    assert fmt.review_footer("confirmed", "А", "t").startswith("\n\n✅ Подтверждено")
