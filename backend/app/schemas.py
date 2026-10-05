"""Pydantic-схемы API. Формат события устройства — Приложение Б ТЗ."""

import uuid as uuid_mod
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EventType = Literal[
    "microsleep",
    "distraction",
    "phone",
    "smoking",
    "seatbelt",
    "speeding",
    "fatigue",
    "head_nod",
    "camera_sabotage",
    "harsh_braking",
    "sos",
]
Severity = Literal["critical", "warning", "info"]
EventStatus = Literal["new", "confirmed", "false_positive"]
Role = Literal["admin", "coordinator", "driver", "viewer"]

# Контракт формы «Добавить водителя» (WEB-6) дублируется на сервере
PHONE_RE = r"^\+7\d{10}$"
PIN_RE = r"^\d{4,6}$"


# ── Auth ──────────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class DriverLoginIn(BaseModel):
    phone: str = Field(max_length=32)
    pin: str = Field(max_length=32)


class DeviceLoginIn(BaseModel):
    serial: str = Field(max_length=40)
    secret: str = Field(max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(max_length=2048)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    role: str
    email: str | None = None
    phone: str | None = None
    created_at: datetime | None = None
    last_seen: datetime | None = None
    online: bool = False


StaffRole = Literal["admin", "coordinator", "viewer"]


def _password_fits_bcrypt(value: str | None) -> str | None:
    """bcrypt хэширует только первые 72 байта — длиннее не принимаем молча."""
    if value is not None and len(value.encode()) > 72:
        raise ValueError("пароль не длиннее 72 байт")
    return value


class UserIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    email: str = Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: StaffRole
    password: str = Field(min_length=8, max_length=128)

    _password_bytes = field_validator("password")(_password_fits_bcrypt)


class UserPatch(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    role: StaffRole | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)

    _password_bytes = field_validator("password")(_password_fits_bcrypt)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    user: UserOut | None = None
    driver_id: int | None = None


# ── Справочники ───────────────────────────────────────────────────────
class DepotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class DriverIn(BaseModel):
    name: str = Field(min_length=3)
    depot_id: int | None = None
    phone: str | None = Field(default=None, pattern=PHONE_RE, description="+7XXXXXXXXXX")
    pin: str | None = Field(
        default=None, pattern=PIN_RE, description="PIN для входа в PWA, 4–6 цифр"
    )


class DriverPatch(BaseModel):
    name: str | None = Field(default=None, min_length=3)
    depot_id: int | None = None
    phone: str | None = Field(default=None, pattern=PHONE_RE)
    pin: str | None = Field(default=None, pattern=PIN_RE, description="Сброс PIN учётки PWA")
    vehicle_id: int | None = Field(
        default=None, description="Закрепить машину (0/null — открепить)"
    )


class DriverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    depot_id: int | None
    phone: str | None
    depot_name: str | None = None
    vehicle_plate: str | None = None
    vehicle_id: int | None = None
    photo_url: str | None = None


class VehicleIn(BaseModel):
    plate: str
    model: str
    depot_id: int | None = None
    driver_id: int | None = None
    profile: Literal["trassa", "gorod"] = "trassa"


class VehiclePatch(BaseModel):
    plate: str | None = None
    model: str | None = None
    depot_id: int | None = None
    driver_id: int | None = None
    profile: Literal["trassa", "gorod"] | None = None


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plate: str
    model: str
    depot_id: int | None
    driver_id: int | None
    profile: str


class DeviceIn(BaseModel):
    serial: str = Field(min_length=1, max_length=40)   # колонка String(40) в БД
    secret: str = Field(min_length=1, max_length=128)
    vehicle_id: int | None = None

    # Та же защита, что у паролей пользователей: bcrypt хэширует только первые
    # 72 байта и на более длинной строке выбрасывает исключение. Без валидатора
    # секрет из русской фразы (79 байт) превращался в 500 вместо понятной ошибки.
    _secret_bytes = field_validator("secret")(_password_fits_bcrypt)
    fw_version: str | None = Field(default=None, max_length=40)
    model_version: str | None = Field(default=None, max_length=20)


DeviceStatus = Literal["active", "disabled", "reboot_requested"]


class DevicePatch(BaseModel):
    vehicle_id: int | None = None
    fw_version: str | None = Field(default=None, max_length=40)
    model_version: str | None = Field(default=None, max_length=20)
    status: DeviceStatus | None = None  # disabled — устройство теряет доступ (SEC)


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    serial: str
    vehicle_id: int | None
    fw_version: str | None
    model_version: str | None
    last_seen: datetime | None
    status: str
    online: bool = False
    vehicle_plate: str | None = None


# ── Рейсы ─────────────────────────────────────────────────────────────
class HeartbeatIn(BaseModel):
    """Телеметрия устройства (DEV-23): типизирована, нечисловые значения → 422, а не 500."""

    ts: datetime | None = None  # время устройства (офлайн-очередь), иначе серверное
    fw_version: str | None = Field(default=None, max_length=40)
    model_version: str | None = Field(default=None, max_length=20)  # ML-4: версия детектора
    temp_c: float | None = None
    fps: float | None = Field(default=None, ge=0)
    disk_free: float | None = Field(default=None, ge=0)
    gps_fix: bool | None = None
    net: str | None = Field(default=None, max_length=20)
    trip_km_delta: float | None = Field(default=None, ge=0, le=2000)
    event: str | None = Field(default=None, max_length=40)
    mode: str | None = Field(default=None, max_length=20)


class TripStartIn(BaseModel):
    driver_id: int
    vehicle_id: int
    device_id: int | None = None


class BreakIn(BaseModel):
    reason: Literal["устал", "туалет", "еда", "заправка", "другое"]


class TripOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    driver_id: int
    vehicle_id: int
    device_id: int | None
    started_at: datetime
    ended_at: datetime | None
    distance_km: float
    status: str


# ── События (Приложение Б) ────────────────────────────────────────────
class EventClipInfo(BaseModel):
    available: bool = False
    duration_s: int | None = None


class EventIn(BaseModel):
    uuid: uuid_mod.UUID
    device_serial: str | None = None
    trip_id: int | None = None
    driver_id: int | None = None
    type: EventType
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    ts: datetime
    lat: float | None = None
    lon: float | None = None
    gps_valid: bool = True
    speed_kmh: float | None = None
    speed_source: str | None = None
    value: float | None = None
    context: dict | None = None
    clip: EventClipInfo | None = None
    fw_version: str | None = None
    model_version: str | None = None
    is_demo: bool = False


class EventBatchOut(BaseModel):
    accepted: int
    duplicates: int


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: uuid_mod.UUID
    type: str
    severity: str
    confidence: float
    ts: datetime
    lat: float | None
    lon: float | None
    gps_valid: bool
    speed_kmh: float | None
    value: float | None
    clip_key: str | None
    status: str
    is_demo: bool
    driver_id: int | None
    context: dict | None = None  # причина SOS, заметка устройства (BOT-2)
    driver_name: str | None = None
    vehicle_plate: str | None = None
    driver_phone: str | None = None


class EventListOut(BaseModel):
    items: list[EventOut]
    total: int
    page: int
    page_size: int


class ClipDownloadOut(BaseModel):
    url: str


class ClipUploadOut(BaseModel):
    upload_url: str
    clip_key: str
    expires_in: int


# Ремень принимается только с явно указанным источником object_model.
CameraEventType = Literal[
    "microsleep", "fatigue", "head_nod", "distraction", "camera_sabotage", "phone", "smoking",
    "seatbelt",
]


class CameraEventIn(BaseModel):
    """Событие DMS из браузера телефона (PWA «Камера»): те же правила, что на устройстве."""

    uuid: uuid_mod.UUID
    type: CameraEventType
    severity: Severity
    confidence: float = Field(ge=0, le=1)
    ts: datetime
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    gps_valid: bool = False
    speed_kmh: float | None = Field(default=None, ge=0, le=300)
    value: float | None = None
    note: str | None = Field(default=None, max_length=512)
    detector: Literal["face_rules", "hand_gesture", "object_model"] | None = None
    model_run_id: str | None = Field(default=None, min_length=1, max_length=120)
    model_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_detector(self):
        if self.type == "seatbelt" and self.detector != "object_model":
            raise ValueError("Ремень требует отдельной модели предметов")
        if self.detector == "object_model" and not (self.model_run_id and self.model_sha256):
            raise ValueError("Укажите версию и контрольную сумму модели предметов")
        return self


class CameraHeartbeatIn(BaseModel):
    """Телеметрия PWA «Камера»: позиция телефона для Live-карты и признак «онлайн»."""

    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    gps_valid: bool = False
    speed_kmh: float | None = Field(default=None, ge=0, le=300)
    fps: float | None = Field(default=None, ge=0, le=120)


class SosIn(BaseModel):
    """SOS из PWA (APP-5): причина + координаты Geolocation API."""

    reason: Literal["Поломка", "ДТП", "Здоровье", "Другое"]
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    gps_valid: bool = True
    comment: str | None = Field(default=None, max_length=200)


class ReviewIn(BaseModel):
    status: Literal["confirmed", "false_positive"]
    comment: str | None = Field(default=None, max_length=200)  # напр. «Telegram: Айгерим»


# ── Чек-листы (BE-10, WEB-7) ───────────────────────────────────────────
ChecklistVerdict = Literal["допущен", "требует_внимания", "не_допущен"]
ChecklistStatus = Literal["pending", "approved", "approved_with_note", "sent_to_repair"]
ChecklistAction = Literal["approve", "approve_with_note", "send_to_repair"]


class ChecklistReviewIn(BaseModel):
    action: ChecklistAction
    note: str | None = Field(default=None, max_length=500)


class ChecklistItemCatalogOut(BaseModel):
    id: str
    section: str
    section_title: str
    text: str
    base: bool
    criticality: str | None
    method: str
    ai_key: str | None
    na_allowed: bool
    enabled: bool = True
    custom: bool = False
    default_text: str | None = None  # для редактора: исходные значения каталога
    default_base: bool | None = None
    default_criticality: str | None = None


class ChecklistSlotOut(BaseModel):
    slot: str
    label: str
    hint: str = ""
    enabled: bool = True
    custom: bool = False


class ChecklistTemplateOut(BaseModel):
    slots: list[ChecklistSlotOut]
    items: list[ChecklistItemCatalogOut]
    version: int = 0


class ChecklistPhotoOut(BaseModel):
    slot: str
    label: str
    key: str | None
    url: str | None = None
    ai: Literal["ok", "warn", "fail", "not_visible", "none"] = "none"


class ChecklistAiItemOut(BaseModel):
    key: str
    title: str
    critical: bool
    status: str
    confidence: float
    comment: str


class ChecklistAnswerIssueOut(BaseModel):
    id: str
    text: str
    criticality: str | None


class ChecklistOut(BaseModel):
    id: int
    driver_id: int
    driver_name: str | None
    vehicle_plate: str | None
    vehicle_model: str | None
    created_at: datetime
    verdict: ChecklistVerdict
    status: ChecklistStatus
    note: str | None
    reviewed_at: datetime | None
    reviewed_by_name: str | None
    photos: list[ChecklistPhotoOut]
    ai_items: list[ChecklistAiItemOut]
    body_damage: list[dict]
    ai_meta: dict
    answers: dict | None
    answered: int
    answer_issues: list[ChecklistAnswerIssueOut]
    discrepancies: list[str]


class ChecklistListOut(BaseModel):
    items: list[ChecklistOut]
    total: int
    page: int
    page_size: int


# ── Настройки (BE-15): валидация по разделам ─────────────────────────
class ScoringModifiers(BaseModel):
    fast_kmh: float = Field(ge=20, le=150, description="порог «быстро», км/ч")
    fast_mult: float = Field(ge=1, le=3, description="множитель phone/microsleep на скорости")
    slow_kmh: float = Field(ge=0, le=20, description="порог «стоим», км/ч")
    slow_mult: float = Field(ge=0, le=1, description="множитель phone на стоянке")


class ScoringSettings(BaseModel):
    weights: dict[str, float]
    modifiers: ScoringModifiers

    @field_validator("weights")
    @classmethod
    def _weights_known(cls, value: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(value) - set(get_args(EventType)))
        if unknown:
            raise ValueError(f"неизвестные типы событий: {', '.join(unknown)}")
        bad = [k for k, v in value.items() if not 0 <= float(v) <= 50]
        if bad:
            raise ValueError(f"вес должен быть от 0 до 50: {', '.join(bad)}")
        return {k: float(v) for k, v in value.items()}


class ThresholdSettings(BaseModel):
    MICROSLEEP_MS: int = Field(ge=500, le=5000)
    PERCLOS_WARN: float = Field(ge=0.05, le=0.6)
    YAWN_MS: int = Field(ge=500, le=5000)
    NOD_MS: int = Field(ge=500, le=5000)
    NOFACE_MS: int = Field(ge=1000, le=10000)
    speed_limit_highway: int = Field(ge=60, le=130)
    speed_limit_city: int = Field(ge=30, le=80)


class NotificationSettings(BaseModel):
    telegram_chat_id: str = Field(default="", pattern=r"^-?\d{0,20}$")
    critical_types: list[EventType]


class RetentionSettings(BaseModel):
    """Сроки хранения (ТЗ 6.2.3): события 12 мес, клипы 90 дн, фото 180 дн, аудит 3 года."""

    events_months: int = Field(ge=1, le=36)
    clips_days: int = Field(ge=7, le=365)
    photos_days: int = Field(ge=7, le=365)
    audit_years: int = Field(ge=1, le=10)


class ChecklistSlotCfg(BaseModel):
    slot: str = Field(pattern=r"^[a-z][a-z0-9_]{1,29}$")
    label: str = Field(min_length=1, max_length=60)
    hint: str = Field(default="", max_length=200)


class ChecklistItemCfg(BaseModel):
    id: str = Field(pattern=r"^П[0-9]{1,2}$", description="Свои пункты — раздел «П»")
    text: str = Field(min_length=3, max_length=200)
    base: bool = False
    criticality: Literal["critical", "attention"] | None = None
    na_allowed: bool = False


class ChecklistItemOverride(BaseModel):
    text: str | None = Field(default=None, min_length=3, max_length=200)
    base: bool | None = None
    criticality: Literal["critical", "attention", "none"] | None = None


class ChecklistSettings(BaseModel):
    """Настройки → Чек-лист: что скрыть, что поправить, что добавить (каталог остаётся в коде)."""

    hidden_slots: list[str] = []
    custom_slots: list[ChecklistSlotCfg] = []
    hidden_items: list[str] = []
    item_overrides: dict[str, ChecklistItemOverride] = {}
    custom_items: list[ChecklistItemCfg] = []

    @model_validator(mode="after")
    def _consistent(self) -> "ChecklistSettings":
        from app.checklist_items import ITEMS_BY_ID, SLOT_LABELS

        unknown = [s for s in self.hidden_slots if s not in SLOT_LABELS]
        if unknown:
            raise ValueError(f"неизвестные слоты фото: {', '.join(unknown)}")
        ids = [c.slot for c in self.custom_slots]
        if len(set(ids)) != len(ids) or any(s in SLOT_LABELS for s in ids):
            raise ValueError(
                "id добавленных слотов должны быть уникальны и не совпадать со стандартными"
            )
        if len(SLOT_LABELS) - len(set(self.hidden_slots)) + len(ids) == 0:
            raise ValueError("нужен хотя бы один слот фото")
        unknown = [i for i in self.hidden_items if i not in ITEMS_BY_ID]
        if unknown:
            raise ValueError(f"неизвестные пункты: {', '.join(unknown)}")
        unknown = [i for i in self.item_overrides if i not in ITEMS_BY_ID]
        if unknown:
            raise ValueError(f"неизвестные пункты: {', '.join(unknown)}")
        cids = [c.id for c in self.custom_items]
        if len(set(cids)) != len(cids):
            raise ValueError("id добавленных пунктов должны быть уникальны")
        return self


SETTING_MODELS: dict[str, type[BaseModel]] = {
    "scoring": ScoringSettings,
    "thresholds": ThresholdSettings,
    "notifications": NotificationSettings,
    "retention": RetentionSettings,
    "checklist": ChecklistSettings,
}


class SettingIn(BaseModel):
    value: dict


class SettingOut(BaseModel):
    key: str
    value: dict
    version: int
    updated_at: datetime | None
    updated_by_name: str | None


class ScoringPreviewRow(BaseModel):
    driver_id: int
    name: str
    score_now: int
    score_new: int
    delta: int


class TrainingAssignIn(BaseModel):
    training_id: int | None = Field(
        default=None, description="Без id — назначается урок «Управление усталостью»"
    )


# ── очередь дообучения (ML-5) ──
class RetrainItemOut(BaseModel):
    id: int
    event_uuid: uuid_mod.UUID
    label_hint: str | None
    frame_key: str | None
    created_at: datetime
    exported_at: datetime | None
    event_type: str
    event_ts: datetime
    severity: str
    confidence: float
    speed_kmh: float | None
    status: str
    model_version: str | None
    driver_name: str | None
    vehicle_plate: str | None
    clip_url: str | None


class RetrainListOut(BaseModel):
    items: list[RetrainItemOut]
    total: int


class RetrainExportIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class RetrainExportOut(BaseModel):
    exported: int
    ids: list[int]
