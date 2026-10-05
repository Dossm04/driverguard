"""Классы детектора нарушений (ML-1) и их соответствие событиям устройства (DEV-8…DEV-10)."""

from __future__ import annotations

CLASSES = ["phone", "cigarette", "seatbelt_on", "seatbelt_off"]

# Синонимы из чужих датасетов (Roboflow, COCO и т. п.) → наши классы; сравнение без регистра
ALIASES: dict[str, set[str]] = {
    "phone": {"phone", "cell phone", "cellphone", "cell_phone", "mobile", "mobile phone", "mobile_phone",
              "smartphone", "telephone", "phone_use", "using_phone"},
    "cigarette": {"cigarette", "cigar", "smoking", "smoke", "vape", "e-cigarette", "ecig"},
    "seatbelt_on": {"seatbelt_on", "seatbelt", "seat belt", "seat_belt", "belt_on", "with_seatbelt", "belt"},
    "seatbelt_off": {"seatbelt_off", "no_seatbelt", "no seatbelt", "no seat belt", "belt_off",
                     "without_seatbelt", "no_belt"},
}

COCO_PHONE = "cell phone"  # класс COCO, который устройство использует до своей модели (DEV-8)

# Класс детектора → тип события DriverGuard
EVENT_BY_CLASS = {"phone": "phone", "cigarette": "smoking", "seatbelt_off": "seatbelt"}


def normalize(name: str) -> str | None:
    """Имя класса из стороннего датасета → наш класс или None (класс нам не нужен)."""
    key = name.strip().lower().replace("-", " ")
    for ours, aliases in ALIASES.items():
        if key == ours or key in aliases or key.replace(" ", "_") in aliases:
            return ours
    return None


def class_index(name: str) -> int:
    return CLASSES.index(name)
