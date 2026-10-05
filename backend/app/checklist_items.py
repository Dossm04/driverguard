"""Каталог чек-листа предрейсового осмотра v2 (docs/checklist_v2.md).

20 пунктов исходной формы пользователя — обязательное ядро (base=True),
остальные — добавки мирового уровня (DOT/FMCSA, ЕСТР). Каталог отдаётся PWA
(мастер ШАГ 13) и панели (расшифровка ответов) через GET /checklists/items.
"""

from typing import Literal, TypedDict

Criticality = Literal["critical", "attention"] | None
Method = Literal["auto", "answer", "photo_ai", "input"]
Answer = Literal["да", "нет", "н-п"]

# 7 обязательных фото (Приложение В ТЗ) — порядок как в мастере PWA и на панели
PHOTO_SLOTS: list[tuple[str, str]] = [
    ("front_lights", "Перёд + фары"),
    ("rear_lights", "Зад + габариты"),
    ("left_side", "Левый борт"),
    ("right_side", "Правый борт"),
    ("tires", "Шины"),
    ("windshield", "Лобовое"),
    ("under_engine", "Под двигателем"),
]
SLOT_LABELS = dict(PHOTO_SLOTS)
SLOT_HINTS: dict[str, str] = {
    "front_lights": "Включите ближний свет, встаньте в 3–4 метрах перед кабиной",
    "rear_lights": "Габариты включены, в кадре весь задний борт и фонари",
    "left_side": "Вся левая сторона от кабины до заднего колеса",
    "right_side": "Вся правая сторона, видны двери и колёса",
    "tires": "Крупно протектор и боковина одного колеса",
    "windshield": "Стекло целиком, чтобы были видны трещины и сколы",
    "under_engine": "Площадка под моторным отсеком — видны ли подтёки",
}
CUSTOM_SECTION = "П"  # пункты, добавленные координатором в Настройках → Чек-лист

SECTIONS: dict[str, str] = {
    "А": "Идентификация",
    "Б": "Двигатель и жидкости",
    "В": "Тормоза и рулевое",
    "Г": "Свет и электрика",
    "Д": "Колёса и шины",
    "Е": "Кузов, кабина, груз",
    "Ж": "Комплектность и безопасность",
    "З": "DriverGuard и готовность водителя",
    "П": "Дополнительно (настроено парком)",
}


class Item(TypedDict):
    id: str
    section: str
    text: str
    base: bool
    criticality: Criticality
    method: Method
    ai_key: str | None  # пункт сверяется с вердиктом ИИ по фото (ключ AiVerdict)
    na_allowed: bool


def _item(
    id_: str,
    text: str,
    *,
    base: bool = False,
    criticality: Criticality = None,
    method: Method = "answer",
    ai_key: str | None = None,
    na_allowed: bool = False,
) -> Item:
    return Item(
        id=id_,
        section=id_[0],
        text=text,
        base=base,
        criticality=criticality,
        method=method,
        ai_key=ai_key,
        na_allowed=na_allowed,
    )


ITEMS: list[Item] = [
    # А. Идентификация — заполняет система
    _item("А1", "Фамилия Имя водителя", base=True, method="auto"),
    _item("А2", "Дата и время осмотра", base=True, method="auto"),
    _item("А3", "Тип/модель автомашины", base=True, method="auto"),
    _item("А4", "Номер машины", base=True, method="auto"),
    _item("А5", "Пробег (одометр), км", base=True, method="input"),
    # Б. Двигатель и жидкости
    _item("Б1", "ТС обслужено согласно графику ТО", base=True, criticality="attention"),
    _item(
        "Б2",
        "Двигатель работает исправно, посторонних шумов нет",
        base=True,
        criticality="critical",
    ),
    _item("Б3", "Уровень масла и охлаждающей жидкости в норме", base=True, criticality="critical"),
    _item(
        "Б4",
        "Видимых утечек нет (масло/топливо/антифриз)",
        base=True,
        criticality="critical",
        method="photo_ai",
        ai_key="утечки",
    ),
    _item("Б5", "Топлива достаточно для рейса, крышка бака закрыта", criticality="attention"),
    _item("Б6", "АКБ: клеммы затянуты, без окисления, крепление на месте", criticality="attention"),
    # В. Тормоза и рулевое
    _item(
        "В1",
        "Рабочий тормоз: ход педали в норме, давление воздуха набирается, утечек воздуха не слышно",
        criticality="critical",
    ),
    _item("В2", "Стояночный тормоз удерживает машину", criticality="critical"),
    _item("В3", "Рулевое: люфт в норме, ГУР работает без шума", criticality="critical"),
    # Г. Свет и электрика
    _item("Г1", "Поворотники работают", base=True, criticality="critical"),
    _item("Г2", "Стоп-сигналы работают", base=True, criticality="critical"),
    _item(
        "Г3",
        "Передние фары работают (ближний/дальний)",
        base=True,
        criticality="critical",
        method="photo_ai",
        ai_key="фары",
    ),
    _item(
        "Г4",
        "Задние фонари работают",
        base=True,
        criticality="critical",
        method="photo_ai",
        ai_key="фары",
    ),
    _item("Г5", "Фары заднего хода работают", base=True, criticality="attention"),
    _item("Г6", "Камеры заднего вида работают", base=True, criticality="attention"),
    _item("Г7", "Габаритные огни и аварийная сигнализация работают", criticality="attention"),
    _item("Г8", "Звуковой сигнал (клаксон) работает", criticality="attention"),
    _item("Г9", "Дворники и омыватель работают, щётки не изношены", criticality="attention"),
    # Д. Колёса и шины
    _item(
        "Д1",
        "Шины без повреждений (порезы, грыжи, посторонние предметы)",
        base=True,
        criticality="critical",
        method="photo_ai",
        ai_key="шины",
    ),
    _item("Д2", "Давление во всех шинах в норме (визуально/манометром)", criticality="critical"),
    _item("Д3", "Глубина протектора не ниже нормы", criticality="critical"),
    _item("Д4", "Гайки колёс затянуты, метки-индикаторы не сместились", criticality="critical"),
    _item("Д5", "Запасное колесо, домкрат, баллонный ключ на месте", criticality="attention"),
    # Е. Кузов, кабина, груз
    _item(
        "Е1",
        "Кузов без повреждений (новых)",
        base=True,
        criticality="attention",
        method="photo_ai",
        ai_key="кузов",
    ),
    _item("Е2", "Кузов и кабина чистые и организованные", base=True, criticality="attention"),
    _item("Е3", "Зеркала на месте, целые, чистые, отрегулированы", criticality="critical"),
    _item(
        "Е4",
        "Лобовое стекло без трещин, обзор не ограничен",
        criticality="critical",
        method="photo_ai",
        ai_key="лобовое",
    ),
    _item("Е5", "Двери и борта закрываются, запоры исправны", criticality="attention"),
    _item(
        "Е6",
        "Груз закреплён и распределён; тент/пломбы в порядке",
        criticality="critical",
        na_allowed=True,
    ),
    _item(
        "Е7",
        "Сцепка прицепа: седло/шкворень, пневмолинии и электроразъём подключены",
        criticality="critical",
        na_allowed=True,
    ),
    # Ж. Комплектность и безопасность
    _item(
        "Ж1",
        "Огнетушитель заряжен, пломба цела, срок поверки не истёк",
        base=True,
        criticality="critical",
    ),
    _item(
        "Ж2", "Аптечка укомплектована, срок годности не истёк", base=True, criticality="attention"
    ),
    _item(
        "Ж3",
        "Знак аварийной остановки, жилет, противооткатные упоры на месте",
        criticality="attention",
    ),
    _item("Ж4", "Ремень безопасности исправен, замок фиксирует", criticality="critical"),
    _item(
        "Ж5",
        "Документы: свидетельство о регистрации, страховка, путевой лист",
        criticality="attention",
    ),
    # З. DriverGuard и готовность водителя
    _item(
        "З1",
        "Устройство DriverGuard включено, онлайн, камера не перекрыта",
        criticality="critical",
        method="auto",
    ),
    _item("З2", "Самочувствие: выспался, жалоб нет, готов к рейсу", criticality="critical"),
]

ITEMS_BY_ID: dict[str, Item] = {i["id"]: i for i in ITEMS}
ANSWERABLE_IDS: list[str] = [i["id"] for i in ITEMS if i["method"] in ("answer", "photo_ai")]

VERDICT_RANK = {"допущен": 0, "требует_внимания": 1, "не_допущен": 2}


def worst_verdict(*verdicts: str) -> str:
    return max(verdicts, key=lambda v: VERDICT_RANK[v])


def validate_answers(answers: dict, items_by_id: dict[str, Item] | None = None) -> list[str]:
    """Ошибки анкеты (пустой список — всё корректно). Значения: да/нет/н-п; A5 — число."""
    items_by_id = ITEMS_BY_ID if items_by_id is None else items_by_id
    errors = []
    for item_id, value in answers.items():
        item = items_by_id.get(item_id)
        if item is None:
            errors.append(f"{item_id}: неизвестный пункт")
            continue
        if item["method"] == "auto":
            errors.append(f"{item_id}: заполняется системой")
        elif item["method"] == "input":
            if not isinstance(value, (str, int, float)) or not str(value).strip():
                errors.append(f"{item_id}: нужно значение")
        elif value not in ("да", "нет", "н-п"):
            errors.append(f"{item_id}: ответ должен быть «да», «нет» или «н-п»")
        elif value == "н-п" and not item["na_allowed"]:
            errors.append(f"{item_id}: «не применимо» здесь недопустимо")
    return errors


def questionnaire_verdict(
    answers: dict, items_by_id: dict[str, Item] | None = None
) -> tuple[str, list[Item]]:
    """Вердикт по анкете и пункты с «нет» (правила docs/checklist_v2.md)."""
    items_by_id = ITEMS_BY_ID if items_by_id is None else items_by_id
    verdict = "допущен"
    issues: list[Item] = []
    for item_id, value in answers.items():
        item = items_by_id.get(item_id)
        if item is None or value != "нет":
            continue
        issues.append(item)
        if item["criticality"] == "critical":
            verdict = "не_допущен"
        elif item["criticality"] == "attention":
            verdict = worst_verdict(verdict, "требует_внимания")
    return verdict, issues


# ── Настраиваемый шаблон (Настройки → Чек-лист): каталог + правки парка ──
class Slot(TypedDict):
    slot: str
    label: str
    hint: str
    enabled: bool
    custom: bool


def effective_slots(cfg: dict | None, include_hidden: bool = False) -> list[Slot]:
    """Слоты фото: каталог минус скрытые парком плюс добавленные. include_hidden — для редактора."""
    cfg = cfg or {}
    hidden = set(cfg.get("hidden_slots") or [])
    out: list[Slot] = []
    for slot, label in PHOTO_SLOTS:
        enabled = slot not in hidden
        if enabled or include_hidden:
            out.append(
                Slot(
                    slot=slot,
                    label=label,
                    hint=SLOT_HINTS.get(slot, ""),
                    enabled=enabled,
                    custom=False,
                )
            )
    for c in cfg.get("custom_slots") or []:
        out.append(
            Slot(
                slot=c["slot"],
                label=c["label"],
                hint=c.get("hint") or "",
                enabled=True,
                custom=True,
            )
        )
    return out


def effective_items(cfg: dict | None, include_hidden: bool = False) -> list[Item]:
    """Пункты анкеты: каталог с правками парка, минус скрытые, плюс добавленные."""
    cfg = cfg or {}
    hidden = set(cfg.get("hidden_items") or [])
    overrides: dict[str, dict] = cfg.get("item_overrides") or {}
    out: list[Item] = []
    for item in ITEMS:
        if item["id"] in hidden and not include_hidden:
            continue
        merged = dict(item)
        ov = overrides.get(item["id"]) or {}
        if ov.get("text"):
            merged["text"] = ov["text"]
        if ov.get("base") is not None:
            merged["base"] = bool(ov["base"])
        if ov.get("criticality") is not None:
            merged["criticality"] = None if ov["criticality"] == "none" else ov["criticality"]
        out.append(Item(**merged))  # type: ignore[typeddict-item]
    for c in cfg.get("custom_items") or []:
        out.append(
            Item(
                id=c["id"],
                section=CUSTOM_SECTION,
                text=c["text"],
                base=bool(c.get("base", False)),
                criticality=c.get("criticality"),
                method="answer",
                ai_key=None,
                na_allowed=bool(c.get("na_allowed", False)),
            )
        )
    return out
