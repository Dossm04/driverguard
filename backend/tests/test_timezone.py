"""«Сегодня» считается по поясу парка (Asia/Almaty, UTC+5), а не по UTC."""

from datetime import UTC, datetime, timedelta

from app.timeutil import local_date, local_midnight


def test_local_midnight_and_date():
    now = datetime(2026, 9, 3, 22, 30, tzinfo=UTC)  # 03:30 4 сентября по Астане
    assert local_date(now).isoformat() == "2026-09-04"
    midnight = local_midnight(now)
    assert midnight.isoformat().startswith("2026-09-04T00:00:00+05:00")
    assert midnight.astimezone(UTC) == datetime(2026, 9, 3, 19, 0, tzinfo=UTC)


def test_event_late_evening_utc_counts_as_today_in_almaty(client, seeded, headers):
    """Событие в 19:30 UTC «вчера» = 00:30 сегодня по Астане → в KPI «Сегодня» и в графике дня."""
    from datetime import datetime as dt

    now = dt.now(UTC)
    local_mid = local_midnight(now)
    if now - local_mid.astimezone(UTC) < timedelta(hours=1):
        ts = local_mid.astimezone(UTC) + timedelta(minutes=5)  # ночью Астаны — почти полночь
    else:
        ts = local_mid.astimezone(UTC) + timedelta(minutes=30)
    before = client.get(
        "/api/v1/dashboard/summary", params={"period": "today"}, headers=headers
    ).json()
    resp = client.post(
        "/api/v1/events",
        json=[
            {
                "uuid": "cafe0000-0000-4000-8000-000000000001",
                "device_serial": "DG-0001",
                "type": "smoking",
                "severity": "warning",
                "confidence": 0.8,
                "ts": ts.isoformat(),
                "gps_valid": False,
            }
        ],
        headers=headers,
    )
    assert resp.status_code == 200 and resp.json()["accepted"] == 1
    after = client.get(
        "/api/v1/dashboard/summary", params={"period": "today"}, headers=headers
    ).json()
    assert after["events"]["value"] == before["events"]["value"] + 1
    days = client.get("/api/v1/dashboard/events-by-day", headers=headers).json()
    assert days[-1]["date"] == local_date(now).isoformat()
