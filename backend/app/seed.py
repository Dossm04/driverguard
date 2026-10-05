"""Seed демо-данных, откалиброванный под эталон Figma (правило 3 CLAUDE.md).

Гарантирует на свежей БД:
- машин на линии 5/6 (DG-0005 офлайн 3 ч), аптайм устройств 98.2%;
- событий сегодня 14 (вчера 11), критических за 24 ч ровно 3 («герои» Figma),
  новых событий 3 (бейджи), доля speeding за 7 дней 27%;
- недельные Score: 55/65/70/90/93/95 → средний 78 (прошлая неделя 80, дельта −2);
- 30-дневные Score красной тройки: Иванов 41, Петров 53, Сейткали 56;
- пробег парка за неделю 12 480 км (прошлая 11 977 → +4.2%).

Все составы событий подобраны вручную под формулу скоринга и проверяются
асзертами в конце (`_self_check`) — при рассинхроне seed падает, а не молчит.
Запуск: `python -m app.seed`.
"""

import os
import secrets
import uuid as uuid_mod
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app import scoring
from app.db import SessionLocal
from app.geo import route_point
from app.models import (
    Checklist,
    Depot,
    Device,
    Driver,
    DriverTraining,
    Event,
    Heartbeat,
    Setting,
    Training,
    Trip,
    User,
    Vehicle,
)
from app.scoring import ScoredEvent
from app.security import hash_secret
from app.timeutil import local_date, local_midnight

NAMESPACE = uuid_mod.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# ── Каталог «кусочков» событий: код → (тип, severity, скорость, value, confidence) ──
PIECES: dict[str, tuple[str, str, float, float | None, float]] = {
    "MS84": ("microsleep", "critical", 84, 2.1, 0.96),  # вес 15×1.5 = 22.5
    "MS80": ("microsleep", "critical", 80, 1.8, 0.94),  # 22.5
    "MS50": ("microsleep", "critical", 50, 1.7, 0.92),  # 15
    "PH70": ("phone", "critical", 70, None, 0.93),  # 10×1.5 = 15
    "PH30": ("phone", "critical", 30, None, 0.90),  # 10
    "PH3": ("phone", "critical", 3, None, 0.88),  # 10×0.3 = 3
    "SPD42": ("speeding", "critical", 132, 42, 0.99),  # 3+2 = 5 (≥+40 → critical)
    "SPD35": ("speeding", "warning", 125, 35, 0.98),  # 3+1 = 4
    "SPD25": ("speeding", "warning", 112, 25, 0.97),  # 3
    "D8C": ("distraction", "critical", 78, 8, 0.90),  # 4 (герой Figma, см. decisions)
    "D8": ("distraction", "warning", 70, 9, 0.89),  # 4
    "SB": ("seatbelt", "warning", 45, None, 0.85),  # 6
    "HN": ("head_nod", "warning", 65, 2.4, 0.87),  # 5
    "SM": ("smoking", "warning", 60, None, 0.86),  # 4
    "F": ("fatigue", "warning", 60, 0.24, 0.90),  # 2
}

DRIVER_NAMES = [
    "Иванов А.С.",
    "Петров Д.В.",
    "Сейткали М.",
    "Абилов Е.Т.",
    "Сапаров Д.Н.",
    "Ким С.В.",
]
PLATES = ["KZ 4521 AB", "KZ 2290 EF", "KZ 7834 CD", "KZ 6712 KM", "KZ 3348 OR", "KZ 9051 TA"]
MODELS = ["КамАЗ-5490", "MAN TGS 18.400", "Volvo FH 460", "КамАЗ-54901", "MAN TGX", "Volvo FM"]
PHONES = [
    "+77012441832",
    "+77058834007",
    "+77025176621",
    "+77071295584",
    "+77019367213",
    "+77774029158",
]
DEPOT_OF = [0, 0, 1, 0, 1, 1]  # 0=Астана, 1=Караганда

# План недели (дни 0..6): (кусочек, день). Суммы весов: 56 / 44 / 38 / 19 / 20 / 19
# → Score 55 / 65 / 70 / 90(+5) / 93(+9) / 95(+10), средний 78.
WEEK_PLAN: list[list[tuple[str, int]]] = [
    [("MS84", 0), ("MS80", 2), ("SPD35", 0), ("SPD25", 0), ("F", 0), ("F", 0)],
    [("D8C", 0), ("SM", 0), ("PH70", 3), ("PH30", 2), ("SB", 1), ("HN", 1)],
    [("SPD42", 0), ("MS50", 2), ("PH30", 4), ("SPD35", 0), ("D8", 1)],
    [("PH3", 5), ("SB", 0), ("HN", 1), ("SPD25", 0), ("F", 1)],
    [("SPD35", 0), ("SPD25", 1), ("HN", 1), ("SB", 1), ("F", 6)],
    [("SPD25", 0), ("F", 0), ("SM", 1), ("HN", 1), ("SPD25", 6), ("F", 1)],
]
HERO_INDEX = {0: 0, 1: 0, 2: 0}  # у водителей 0..2 первый кусочек недели — «герой» Figma
# Времена героев по Figma: Иванов 08:42, Петров 11:55, Сейткали 10:17
HERO_TIMES = [(8, 42), (11, 55), (10, 17)]
HERO_FALLBACK_H = [3, 1, 2]  # ранний запуск seed: сохраняем тот же порядок «свежести»

# План прошлой недели (дни 8..13). Суммы: 52 / 40 / 34 / 16 / 19 / 19 → средний 80.
PREV_PLAN: list[list[tuple[str, int]]] = [
    [("MS80", 8), ("MS80", 9), ("HN", 10), ("F", 11)],
    [("PH70", 8), ("PH30", 9), ("SB", 10), ("HN", 11), ("SPD35", 12)],
    [("MS50", 9), ("PH30", 10), ("SPD35", 11), ("HN", 12)],
    [("SB", 8), ("HN", 9), ("SPD25", 10), ("F", 11)],
    [("PH3", 9), ("SB", 10), ("HN", 11), ("SPD25", 12), ("F", 13)],  # PH3 на дне 9 — серия 9
    [("SM", 8), ("SB", 9), ("HN", 10), ("SPD35", 11)],
]

# Хвост 30-дневного окна (дни 15..28). Доводит P30 тройки до 316 / 252 / 236
# → 30-дневные Score 41 / 53 / 56 (красная зона Figma).
EXTRA_PLAN: list[list[tuple[str, int]]] = [
    [("MS80", d) for d in (15, 16, 17, 19, 20, 22, 24, 26)]
    + [("PH30", 18), ("PH30", 21), ("SB", 23), ("F", 25)],
    [("PH70", d) for d in (15, 16, 17, 18, 20, 22, 24, 26)]
    + [("PH30", 19), ("PH30", 21), ("PH30", 23), ("PH30", 25), ("SPD35", 27), ("SPD35", 28)],
    [("MS80", d) for d in (15, 16, 18, 20, 22, 24)]
    + [("PH30", 17), ("PH30", 19), ("SPD35", 21), ("HN", 23)],
    [],
    [],
    [],  # якорь серии Кима (день 14) добавляется отдельно
]

# Ложные срабатывания: не влияют на Score и счётчики, нужны для фильтров и review-историй.
FALSE_PLAN: list[list[tuple[str, int]]] = [
    [("SM", 3), ("HN", 16)],
    [("SB", 4), ("F", 17)],
    [("SM", 5), ("HN", 15)],
    [("MS50", 6), ("SB", 18), ("F", 20)],
    [("HN", 3), ("SM", 19)],
    [("SB", 5), ("F", 21), ("HN", 22)],
]

# Рейсы за 30 дней: (число рейсов, км) по неделям [0..6, 7..13, 14..20, 21..27].
# Неделя 0: парк ровно 12 480 км; неделя 1: 11 977 км (+4.2%). Красная тройка: 12/9/7 рейсов.
TRIP_PLAN: list[list[tuple[int, float]]] = [
    [(3, 1980), (3, 1900), (3, 1850), (3, 1830)],  # Иванов, 12
    [(2, 1860), (2, 1800), (3, 1700), (2, 1750)],  # Петров, 9
    [(2, 1710), (2, 1650), (2, 1600), (1, 800)],  # Сейткали, 7
    [(5, 2410), (5, 2300), (4, 2350), (4, 2280)],  # Абилов, 18
    [(4, 2200), (4, 2107), (4, 2150), (4, 2100)],  # Сапаров, 16
    [(4, 2320), (4, 2220), (4, 2250), (3, 2150)],  # Ким, 15
]

WEEK_SCORES = [55, 65, 70, 90, 93, 95]  # средний 78
PREV_SCORES = [58, 68, 73, 92, 94, 95]  # средний 80 → дельта −2
MONTH_SCORES_RED = {0: 41, 1: 53, 2: 56}
STREAKS = [0, 0, 0, 5, 9, 14]

HEARTBEAT_STEP_MIN = 10
HEARTBEAT_EXPECTED_PER_DEVICE = 7 * 24 * 60 // HEARTBEAT_STEP_MIN  # 1008 за 7 дней
UPTIME_TARGET = 98.2
OFFLINE_DEVICE_IDX = 4  # DG-0005 (Сапаров) — «нет связи 3 ч»


def _event_uuid(tag: str) -> uuid_mod.UUID:
    return uuid_mod.uuid5(NAMESPACE, f"driverguard-seed-{tag}")


def _hero_timestamps(today: datetime, now: datetime) -> list[datetime]:
    """Времена трёх героев. Канонические значения Figma используются только если ВСЕ
    уже в прошлом — иначе все три уходят в согласованный fallback, чтобы порядок
    «Иванов < Сейткали < Петров» сохранялся при любом времени запуска seed."""
    canonical = [today.replace(hour=h, minute=m) for h, m in HERO_TIMES]
    if all(ts < now for ts in canonical):
        return canonical
    fallback = [now - timedelta(hours=h) for h in HERO_FALLBACK_H]
    if any(ts < today for ts in fallback):
        # первые часы суток UTC — герои строго между полуночью и now
        fallback = [today + (now - today) * (4 - h) / 5 for h in HERO_FALLBACK_H]
    return fallback


def _build_events(now: datetime) -> list[dict]:
    """Все события seed'а как список словарей для bulk-insert."""
    today = local_midnight(now)  # день парка (Asia/Almaty): 08:42 «героев» — местное время
    events: list[dict] = []
    day0_warn_slot = 0
    day1_slot = 0

    def add(driver_idx: int, piece: str, ts: datetime, status: str, tag: str) -> None:
        type_, severity, speed, value, conf = PIECES[piece]
        lat, lon = route_point(((len(events) * 37) % 97) / 97)
        events.append(
            {
                "uuid": _event_uuid(tag),
                "driver_id": driver_idx + 1,
                "device_id": driver_idx + 1,
                "trip_id": None,
                "type": type_,
                "severity": severity,
                "confidence": conf,
                "ts": ts,
                "lat": lat,
                "lon": lon,
                "gps_valid": True,
                "speed_kmh": speed,
                "value": value,
                "context": None,
                "status": status,
                "is_demo": True,
                "created_at": now,
            }
        )

    def day_ts(day: int, slot: int) -> datetime:
        """Детерминированное время внутри дня `day` дней назад."""
        base = today - timedelta(days=day)
        if day == 0:
            # предупреждения сегодня — равномерно в уже прошедшей части дня
            nonlocal day0_warn_slot
            day0_warn_slot += 1
            frac = day0_warn_slot / 12
            return today + (now - today) * min(frac, 0.95)
        if day == 1:
            nonlocal day1_slot
            day1_slot += 1
            return base + timedelta(hours=6, minutes=day1_slot * 70)
        return base + timedelta(hours=10, minutes=(slot % 12) * 37)

    hero_ts = _hero_timestamps(today, now)
    for d_idx, plan in enumerate(WEEK_PLAN):
        for p_idx, (piece, day) in enumerate(plan):
            tag = f"wk-{d_idx}-{p_idx}"
            if d_idx in HERO_INDEX and p_idx == HERO_INDEX[d_idx]:
                add(d_idx, piece, hero_ts[d_idx], "new", tag)
            else:
                add(d_idx, piece, day_ts(day, p_idx), "confirmed", tag)

    for d_idx, plan in enumerate(PREV_PLAN):
        for p_idx, (piece, day) in enumerate(plan):
            add(d_idx, piece, day_ts(day, p_idx), "confirmed", f"pw-{d_idx}-{p_idx}")

    for d_idx, plan in enumerate(EXTRA_PLAN):
        for p_idx, (piece, day) in enumerate(plan):
            add(d_idx, piece, day_ts(day, p_idx), "confirmed", f"ex-{d_idx}-{p_idx}")

    # Якорь серии Кима: critical ровно на границе 14 дней (внутри 30-дневного окна)
    add(5, "PH3", now - timedelta(days=14, hours=2), "confirmed", "anchor-kim")

    for d_idx, plan in enumerate(FALSE_PLAN):
        for p_idx, (piece, day) in enumerate(plan):
            add(d_idx, piece, day_ts(day, p_idx), "false_positive", f"fp-{d_idx}-{p_idx}")

    return events


def _self_check(events: list[dict], now: datetime) -> None:
    """Сверка с эталоном Figma до записи в БД. Ошибки не прячем (правило 8)."""
    today = local_midnight(now)  # день парка (Asia/Almaty): 08:42 «героев» — местное время

    def scored(driver_idx: int, since: datetime, until: datetime) -> list[ScoredEvent]:
        return [
            ScoredEvent(e["type"], e["ts"], e["speed_kmh"], e["value"], e["status"], e["severity"])
            for e in events
            if e["driver_id"] == driver_idx + 1 and since < e["ts"] <= until
        ]

    week_scores, prev_scores, month_scores = [], [], []
    for i in range(6):
        crit_dates = [
            local_date(e["ts"])
            for e in events
            if e["driver_id"] == i + 1
            and e["severity"] == "critical"
            and e["status"] in scoring.SCORED_STATUSES
        ]
        streak = scoring.streak_days(crit_dates, local_date(now))
        expected_streak = STREAKS[i]
        assert streak == expected_streak or (i == 5 and streak >= 14), (
            f"streak водителя {i}: {streak} ≠ {expected_streak}"
        )
        week_scores.append(scoring.score(scored(i, now - timedelta(days=7), now), 7, streak))
        prev_scores.append(
            scoring.score(scored(i, now - timedelta(days=14), now - timedelta(days=7)), 7, streak)
        )
        month_scores.append(scoring.score(scored(i, now - timedelta(days=30), now), 30, streak))

    assert week_scores == WEEK_SCORES, f"недельные Score {week_scores} ≠ {WEEK_SCORES}"
    assert round(sum(week_scores) / 6) == 78, "средний недельный Score ≠ 78"
    assert prev_scores == PREV_SCORES, f"Score прошлой недели {prev_scores} ≠ {PREV_SCORES}"
    for i, target in MONTH_SCORES_RED.items():
        assert month_scores[i] == target, f"30-дневный Score {i}: {month_scores[i]} ≠ {target}"
    for i in (3, 4, 5):
        assert month_scores[i] >= 60, f"водитель {i} не должен быть в красной зоне"

    active = [e for e in events if e["status"] != "false_positive"]
    n_today = sum(1 for e in active if e["ts"] >= today)
    n_yesterday = sum(1 for e in active if today - timedelta(days=1) <= e["ts"] < today)
    assert n_today == 14, f"событий сегодня {n_today} ≠ 14"
    assert n_yesterday == 11, f"событий вчера {n_yesterday} ≠ 11"

    crit24 = [
        e for e in active if e["severity"] == "critical" and e["ts"] >= now - timedelta(hours=24)
    ]
    assert len(crit24) == 3, f"критических за 24 ч {len(crit24)} ≠ 3"
    assert sum(1 for e in events if e["status"] == "new") == 3, "новых событий должно быть 3"

    week_active = [e for e in active if e["ts"] > now - timedelta(days=7)]
    share = round(100 * sum(1 for e in week_active if e["type"] == "speeding") / len(week_active))
    assert share == 27, f"доля speeding за 7 дней {share}% ≠ 27%"

    km_week = sum(plan[0][1] for plan in TRIP_PLAN)
    km_prev = sum(plan[1][1] for plan in TRIP_PLAN)
    assert km_week == 12480, f"пробег недели {km_week} ≠ 12480"
    assert round((km_week / km_prev - 1) * 100, 1) == 4.2, "дельта пробега ≠ +4.2%"


def run(db: Session) -> None:
    now = datetime.now(UTC)
    today = local_midnight(now)  # день парка (Asia/Almaty): 08:42 «героев» — местное время

    # Полная очистка: seed всегда приводит БД к эталонному состоянию
    tables = (
        "retrain_queue, audit_log, heartbeats, driver_trainings, trainings, checklists, "
        "events, breaks, trips, devices, vehicles, drivers, settings, users, depots"
    )
    db.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    # Пароль admin и PIN демо-водителей — из окружения (ADMIN_PASSWORD, DRIVER_PIN); значения
    # по умолчанию только для локальной разработки, на публичном стенде их меняет make demo/runbook
    admin = User(
        role="admin",
        email="admin@driverguard.kz",
        password_hash=hash_secret(os.environ.get("ADMIN_PASSWORD") or "admin123"),
        name="Айгерим Косанова",
        created_at=now,
    )
    db.add(admin)
    db.add_all([Depot(name="Астана"), Depot(name="Караганда")])
    db.flush()

    for i in range(6):
        db.add(
            User(
                role="driver",
                phone=PHONES[i],
                pin_hash=hash_secret(os.environ.get("DRIVER_PIN") or "1234"),
                name=DRIVER_NAMES[i],
                created_at=now,
            )
        )
    db.flush()
    # Служебная учётка Telegram-бота (ШАГ 12): review по кнопкам идёт от её имени
    db.add(
        User(
            role="coordinator",
            email="bot@driverguard.kz",
            password_hash=hash_secret(os.environ.get("BOT_PASSWORD", "bot12345")),
            name="Telegram-бот",
            created_at=now,
        )
    )
    db.flush()
    for i in range(6):
        db.add(
            Driver(
                user_id=i + 2,
                name=DRIVER_NAMES[i],
                depot_id=DEPOT_OF[i] + 1,
                phone=PHONES[i],
                consent_signed_at=now - timedelta(days=40),
                created_at=now - timedelta(days=400),  # стаж > года: серии лидерборда как в Figma
            )
        )
    db.flush()
    for i in range(6):
        db.add(
            Vehicle(
                plate=PLATES[i],
                model=MODELS[i],
                depot_id=DEPOT_OF[i] + 1,
                driver_id=i + 1,
                profile="trassa",
            )
        )
    db.flush()
    # Секреты устройств: DG-0001 — из DG_SECRET (его использует симулятор device-sim), остальные
    # случайные (никто их не использует); DG_SEED_KNOWN_SECRETS=1 — «device-secret-N» для тестов
    known = os.environ.get("DG_SEED_KNOWN_SECRETS") == "1"
    for i in range(6):
        offline = i == OFFLINE_DEVICE_IDX
        if i == 0:
            secret = os.environ.get("DG_SECRET") or "device-secret-1"
        elif known:
            secret = f"device-secret-{i + 1}"
        else:
            secret = secrets.token_urlsafe(24)
        db.add(
            Device(
                serial=f"DG-{i + 1:04d}",
                secret_hash=hash_secret(secret),
                vehicle_id=i + 1,
                fw_version="0.3.1",
                model_version="v1",
                last_seen=now - (timedelta(hours=3) if offline else timedelta(minutes=1 + i % 4)),
                status="active",
            )
        )
    db.flush()

    # Рейсы: детерминированное распределение по дням недель
    for d_idx, weeks in enumerate(TRIP_PLAN):
        for w_idx, (n_trips, week_km) in enumerate(weeks):
            for t_idx in range(n_trips):
                # Дни 1..6 недели: границы скользящих окон (7/14/30 дней) не режут рейсы
                day = w_idx * 7 + 1 + (t_idx * 2) % 6
                started = today - timedelta(days=day) + timedelta(hours=5, minutes=30 * t_idx)
                ended = min(started + timedelta(hours=9), now - timedelta(minutes=1))
                db.add(
                    Trip(
                        driver_id=d_idx + 1,
                        vehicle_id=d_idx + 1,
                        device_id=d_idx + 1,
                        started_at=started,
                        ended_at=ended,
                        distance_km=round(week_km / n_trips, 1),
                        status="finished",
                    )
                )
    db.flush()

    # События (с самопроверкой калибровки до записи)
    events = _build_events(now)
    _self_check(events, now)
    db.execute(insert(Event), events)
    # Все проверенные события считаем отревьюенными координатором
    db.execute(
        text(
            "UPDATE events SET reviewed_by = :uid, reviewed_at = :ts "
            "WHERE status IN ('confirmed', 'false_positive')"
        ),
        {"uid": admin.id, "ts": now},
    )

    # Heartbeats за 7 дней: аптайм ровно 98.2%
    total_expected = HEARTBEAT_EXPECTED_PER_DEVICE * 6
    target_actual = round(total_expected * UPTIME_TARGET / 100)  # 5939
    beats: list[dict] = []
    for dev in range(6):
        for k in range(HEARTBEAT_EXPECTED_PER_DEVICE):
            ts = now - timedelta(minutes=k * HEARTBEAT_STEP_MIN + 2)
            if dev == OFFLINE_DEVICE_IDX and k < 18:  # офлайн 3 часа
                continue
            beats.append(
                {
                    "device_id": dev + 1,
                    "ts": ts,
                    "temp_c": 52.0 + dev + (k % 7),
                    "fps": 13.5 + (k % 4) * 0.5,
                    "disk_free": 41.0 - (k % 9),
                    "gps_fix": True,
                    "net": "lte",
                }
            )
    drop_more = len(beats) - target_actual
    assert drop_more >= 0, "офлайн-окно больше, чем требует аптайм 98.2%"
    if drop_more:
        # выбрасываем исторические heartbeat'ы равномерно (не свежее 1 часа)
        candidates = [i for i, b in enumerate(beats) if b["ts"] < now - timedelta(hours=1)]
        step = len(candidates) // drop_more
        to_drop = {candidates[i * step] for i in range(drop_more)}
        beats = [b for i, b in enumerate(beats) if i not in to_drop]
    uptime = round(100 * len(beats) / total_expected, 1)
    assert uptime == UPTIME_TARGET, f"аптайм {uptime} ≠ {UPTIME_TARGET}"
    db.execute(insert(Heartbeat), beats)

    # Настройки (SYS-4, BE-15)
    db.add_all(
        [
            Setting(
                key="scoring",
                value={
                    "weights": scoring.DEFAULT_WEIGHTS,
                    "modifiers": {
                        "fast_kmh": scoring.FAST_KMH,
                        "fast_mult": scoring.FAST_MULT,
                        "slow_kmh": scoring.SLOW_KMH,
                        "slow_mult": scoring.SLOW_MULT,
                    },
                },
                version=1,
                updated_by=admin.id,
                updated_at=now,
            ),
            Setting(
                key="thresholds",
                value={
                    "MICROSLEEP_MS": 1500,
                    "PERCLOS_WARN": 0.20,
                    "YAWN_MS": 1200,
                    "NOD_MS": 2000,
                    "NOFACE_MS": 3000,
                    "speed_limit_highway": 90,
                    "speed_limit_city": 60,
                },
                version=1,
                updated_by=admin.id,
                updated_at=now,
            ),
            Setting(
                key="notifications",
                value={
                    "telegram_chat_id": "",
                    "critical_types": ["microsleep", "phone", "camera_sabotage", "sos"],
                },
                version=1,
                updated_by=admin.id,
                updated_at=now,
            ),
            Setting(  # сроки хранения — ТЗ 6.2.3
                key="retention",
                value={"events_months": 12, "clips_days": 90, "photos_days": 180, "audit_years": 3},
                version=1,
                updated_by=admin.id,
                updated_at=now,
            ),
        ]
    )

    # Микрообучения
    db.add_all(
        [
            Training(title="Управление усталостью", duration_s=30),
            Training(title="Техника перерывов в рейсе", duration_s=30),
            Training(title="Телефон и дорога", duration_s=30),
        ]
    )
    db.flush()
    db.add(
        DriverTraining(
            driver_id=1, training_id=1, assigned_by=admin.id, status="assigned", assigned_at=now
        )
    )

    _seed_checklists(db, now)

    db.commit()
    print(
        f"Seed готов: 6 водителей, {len(events)} событий, 4 чек-листа, "
        f"{sum(n for w in TRIP_PLAN for n, _ in w)} рейсов, {len(beats)} heartbeat'ов. "
        f"Калибровка Figma подтверждена самопроверкой."
    )


def _seed_checklists(db: Session, now: datetime) -> None:
    """4 осмотра (план ШАГ 10): 2 «допущен», «требует внимания» — трещина лобового (TC-11),
    «не допущен» — левая фара не горит (П-7). Фото — плейсхолдеры (ключ None), вердикт
    считается той же функцией, что и на живом POST."""
    from app.ai_checklist import BodyDamage, ItemCheck, compute_verdict, mock_verdict
    from app.checklist_items import (
        ANSWERABLE_IDS,
        PHOTO_SLOTS,
        questionnaire_verdict,
        worst_verdict,
    )

    def answers(odometer: str, **overrides: str) -> dict:
        result = {i: "да" for i in ANSWERABLE_IDS}
        result["Е7"] = "н-п"  # без прицепа
        result["А5"] = odometer
        result.update(overrides)
        return result

    def ai(**items: ItemCheck):
        verdict = mock_verdict()
        for key, value in items.items():
            setattr(verdict, key, value)
        return verdict

    cracked = ai(
        лобовое=ItemCheck(
            статус="fail", confidence=0.89, комментарий="трещина 12 см в зоне пассажира"
        ),
        кузов=ItemCheck(
            статус="warn", confidence=0.84, комментарий="царапина на правом борту (была ранее)"
        ),
    )
    cracked.повреждения_кузова = [BodyDamage(описание="царапина ~20 см", зона="правый борт")]
    dead_lamp = ai(
        фары=ItemCheck(статус="fail", confidence=0.91, комментарий="левая фара не горит")
    )

    plan = [
        (1, 2.1, ai(), answers("184320")),
        (4, 3.4, cracked, answers("96210")),  # водитель ответил «да» — расхождение с ИИ
        (5, 13.0, dead_lamp, answers("142870", Г3="нет")),
        (2, 2.6, ai(), answers("211045")),
    ]
    for driver_id, hours_ago, verdict, ans in plan:
        verdict.вердикт = compute_verdict(verdict)
        q_verdict, _ = questionnaire_verdict(ans)
        db.add(
            Checklist(
                driver_id=driver_id,
                vehicle_id=driver_id,
                photos=[{"slot": s, "key": None, "content_type": None} for s, _ in PHOTO_SLOTS],
                ai_verdict={
                    **verdict.model_dump(),
                    "meta": {"provider": "demo", "model": None, "latency_ms": 0, "attempts": 1},
                },
                answers=ans,
                verdict=worst_verdict(verdict.вердикт, q_verdict),
                status="pending",
                created_at=now - timedelta(hours=hours_ago),
            )
        )


def main() -> None:
    with SessionLocal() as db:
        run(db)


if __name__ == "__main__":
    main()
