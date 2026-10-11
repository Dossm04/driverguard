"""ИИ-проверка 7 фото чек-листа (BE-10, ТЗ 6.1.7).

Провайдеры: openai_compat (любой OpenAI-совместимый /chat/completions, у нас —
alem.ai с Qwen 3.8 / Gemma 4, данные в Казахстане), gemini (REST generateContent
со строгой responseSchema). Без настроенного провайдера фото проверяет человек.
Вердикт считается детерминированно на сервере из статусов пунктов;
вердикт самой модели хранится только для сверки.
"""

import base64
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Literal, NamedTuple
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.checklist_items import SLOT_LABELS, worst_verdict
from app.config import get_settings

log = logging.getLogger(__name__)

Verdict = Literal["допущен", "требует_внимания", "не_допущен"]
ItemStatus = Literal["ok", "warn", "fail", "not_visible"]

NOT_VISIBLE_CONF = 0.6  # ТЗ 6.1.7: confidence <0.6 → «не видно», повторное фото
CRITICAL_FAIL_CONF = 0.8  # ТЗ 6.1.7: «не допущен» при критической неисправности ≥0.8


class ItemCheck(BaseModel):
    статус: ItemStatus
    confidence: float = Field(ge=0, le=1)
    комментарий: str = ""


class BodyDamage(BaseModel):
    описание: str
    зона: str


class AiVerdict(BaseModel):
    """Строгая схема ответа (план ШАГ 10 + пункт «кузов» для таблицы панели)."""

    фары: ItemCheck
    шины: ItemCheck
    лобовое: ItemCheck
    зеркала: ItemCheck
    утечки: ItemCheck
    кузов: ItemCheck
    повреждения_кузова: list[BodyDamage] = []
    вердикт: Verdict


# (ключ, название в таблице панели, критический по ТЗ 6.1.7)
AI_ITEMS: list[tuple[str, str, bool]] = [
    ("фары", "Фары и габариты", True),
    ("шины", "Шины", True),
    ("утечки", "Утечки", True),
    ("лобовое", "Лобовое стекло", False),
    ("зеркала", "Зеркала", False),
    ("кузов", "Кузов", False),
]
AI_ITEM_KEYS = [k for k, _, _ in AI_ITEMS]


class PhotoIn(NamedTuple):
    slot: str
    data: bytes
    content_type: str
    label: str = ""  # подпись ракурса (для слотов, добавленных парком)


class AiError(Exception):
    """ИИ недоступен или вернул невалидный ответ — наружу отдаём честную ошибку."""


def normalize(v: AiVerdict) -> AiVerdict:
    """confidence <0.6 → статус «не видно» с просьбой повторить фото (ТЗ 6.1.7)."""
    for key in AI_ITEM_KEYS:
        item: ItemCheck = getattr(v, key)
        if item.confidence < NOT_VISIBLE_CONF and item.статус != "not_visible":
            item.статус = "not_visible"
            item.комментарий = (
                f"{item.комментарий} · " if item.комментарий else ""
            ) + "не видно — повторите фото"
    return v


def compute_verdict(v: AiVerdict) -> Verdict:
    """ТЗ 6.1.7: критический fail с confidence ≥0.8 → «не допущен»;
    любые замечания/«не видно» → «требует внимания»; иначе «допущен»."""
    result: Verdict = "допущен"
    for key, _, critical in AI_ITEMS:
        item: ItemCheck = getattr(v, key)
        if item.статус == "fail" and critical and item.confidence >= CRITICAL_FAIL_CONF:
            return "не_допущен"
        if item.статус != "ok":
            result = "требует_внимания"
    if v.повреждения_кузова:
        result = worst_verdict(result, "требует_внимания")  # type: ignore[assignment]
    return result


def unavailable_verdict() -> AiVerdict:
    """Провайдер ИИ недоступен: ничего не подтверждаем, чек-лист уходит координатору
    как «требует внимания» — фото проверяет человек (правило 8: ошибку не прячем за «допущен»)."""

    def nv() -> ItemCheck:
        return ItemCheck(
            статус="not_visible", confidence=0.0, комментарий="ИИ недоступен — проверьте вручную"
        )

    return AiVerdict(
        фары=nv(),
        шины=nv(),
        лобовое=nv(),
        зеркала=nv(),
        утечки=nv(),
        кузов=nv(),
        повреждения_кузова=[],
        вердикт="требует_внимания",
    )


def mock_verdict() -> AiVerdict:
    """Синтетический образец для тестов правил; не результат проверки фотографий.

    Рабочий путь verify_photos никогда не использует этот образец.
    """

    def ok(conf: float, text: str) -> ItemCheck:
        return ItemCheck(статус="ok", confidence=conf, комментарий=text)

    return AiVerdict(
        фары=ok(0.95, "включены, исправны"),
        шины=ok(0.93, "норма, видимых повреждений нет"),
        лобовое=ok(0.97, "чистое, без трещин"),
        зеркала=ok(0.96, "на месте"),
        утечки=ok(0.91, "не обнаружены"),
        кузов=ok(0.90, "без новых повреждений"),
        повреждения_кузова=[],
        вердикт="допущен",
    )


def resolve_provider() -> str:
    s = get_settings()
    if s.ai_provider != "auto":
        return s.ai_provider
    if s.openai_compat_api_key and s.openai_compat_base_url:
        return "openai_compat"
    return "gemini" if s.gemini_api_key else "mock"


# ── Gemini ────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "Ты — инспектор предрейсового осмотра грузовика (Казахстан). Тебе дают 7 фото машины "
    "с подписями ракурсов. Оцени по каждому пункту:\n"
    "• фары — передние фары и задние фонари/габариты включены и целы;\n"
    "• шины — порезы, грыжи, износ, посторонние предметы, спущенное колесо;\n"
    "• лобовое — трещины, сколы, ограничение обзора;\n"
    "• зеркала — на месте, целые;\n"
    "• утечки — следы масла/топлива/антифриза под двигателем;\n"
    "• кузов — новые повреждения (вмятины, царапины, разрывы тента); каждое — "
    "в повреждения_кузова с зоной: «левый борт», «правый борт», «перёд», «зад».\n"
    "Статусы: ok — исправно; warn — замечание, выезд возможен; fail — неисправность, "
    "опасно; not_visible — на фото не видно (ракурс, темнота). confidence — уверенность "
    "0..1 в своей оценке. комментарий — 3–10 слов по-русски, конкретно "
    "(например: «левая фара не горит»). Не выдумывай дефекты, которых не видно.\n"
    "вердикт: не_допущен — fail по фарам, шинам или утечкам; требует_внимания — любые "
    "warn/fail по остальным пунктам или not_visible; иначе допущен. "
    "Отвечай только JSON по схеме."
)

_ITEM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "статус": {"type": "STRING", "enum": ["ok", "warn", "fail", "not_visible"]},
        "confidence": {"type": "NUMBER"},
        "комментарий": {"type": "STRING"},
    },
    "required": ["статус", "confidence", "комментарий"],
}
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        **{key: _ITEM_SCHEMA for key in AI_ITEM_KEYS},
        "повреждения_кузова": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"описание": {"type": "STRING"}, "зона": {"type": "STRING"}},
                "required": ["описание", "зона"],
            },
        },
        "вердикт": {
            "type": "STRING",
            "enum": ["допущен", "требует_внимания", "не_допущен"],
        },
    },
    "required": [*AI_ITEM_KEYS, "повреждения_кузова", "вердикт"],
}


def _build_parts(photos: list[PhotoIn]) -> list[dict]:
    parts: list[dict] = []
    for i, photo in enumerate(photos, start=1):
        label = photo.label or SLOT_LABELS.get(photo.slot, photo.slot)
        parts.append({"text": f"Фото {i}/{len(photos)}: «{label}»"})
        parts.append(
            {
                "inline_data": {
                    "mime_type": photo.content_type,
                    "data": base64.b64encode(photo.data).decode("ascii"),
                }
            }
        )
    parts.append({"text": "Оцени все пункты и верни JSON."})
    return parts


def _gemini_generate(parts: list[dict]) -> tuple[str, dict]:
    """Один вызов generateContent → (текст ответа, usageMetadata)."""
    s = get_settings()
    url = f"{s.gemini_base_url}/v1beta/models/{s.gemini_model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "temperature": 0,
        },
    }
    if s.gemini_thinking_level:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": s.gemini_thinking_level}
    try:
        with httpx.Client(timeout=s.ai_timeout_s) as client:
            resp = client.post(url, headers={"x-goog-api-key": s.gemini_api_key}, json=body)
    except httpx.HTTPError as exc:
        raise AiError(f"Gemini недоступен: {exc}") from exc
    if resp.status_code != 200:
        raise AiError(f"Gemini HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AiError("Gemini вернул ответ без текста") from exc
    return text, data.get("usageMetadata") or {}


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def clean_json_text(text: str) -> str:
    """Убираем рассуждения <think>…</think> и markdown-обёртку ```json``` — их
    добавляют открытые модели даже при запросе «только JSON»."""
    text = _THINK_RE.sub("", text)
    text = _FENCE_RE.sub("", text.strip()).strip()
    return text


def parse_verdict(text: str) -> AiVerdict:
    try:
        return AiVerdict.model_validate_json(clean_json_text(text))
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        raise AiError(f"невалидный JSON от модели: {first.get('msg', 'ошибка схемы')}") from exc


def _to_json_schema(node: dict) -> dict:
    """Схема Gemini (типы в верхнем регистре) → стандартная JSON Schema для response_format."""
    kind = node["type"].lower()
    out: dict = {"type": kind}
    if "enum" in node:
        out["enum"] = node["enum"]
    if kind == "object":
        out["properties"] = {k: _to_json_schema(v) for k, v in node["properties"].items()}
        out["required"] = node.get("required", [])
        out["additionalProperties"] = False
    if kind == "array":
        out["items"] = _to_json_schema(node["items"])
    return out


JSON_SCHEMA = _to_json_schema(RESPONSE_SCHEMA)


class _UnsupportedFormat(AiError):
    """Сервер отверг response_format — пробуем более простой вариант."""


BAD_KEY_MSG = (
    "ключ API содержит недопустимые символы (например, «•» после вставки из терминала) — "
    "проверьте OPENAI_COMPAT_API_KEY в infra/.env"
)


def key_is_valid(key: str) -> bool:
    """Ключ провайдера — только печатные ASCII: замаскированная вставка «sk-…•••» не пройдёт."""
    return bool(key) and key.isascii() and key.isprintable() and " " not in key


def _openai_chat(messages: list[dict], response_format: dict | None) -> tuple[str, dict]:
    """Один вызов /chat/completions → (текст ответа, usage)."""
    s = get_settings()
    if not key_is_valid(s.openai_compat_api_key):
        raise AiError(BAD_KEY_MSG)
    body: dict = {"model": s.openai_compat_model, "temperature": 0, "messages": messages}
    if response_format is not None:
        body["response_format"] = response_format
    url = f"{s.openai_compat_base_url.rstrip('/')}/chat/completions"
    try:
        with httpx.Client(timeout=s.ai_timeout_s) as client:
            resp = client.post(
                url, headers={"Authorization": f"Bearer {s.openai_compat_api_key}"}, json=body
            )
    except httpx.HTTPError as exc:
        raise AiError(f"OpenAI-совместимый API недоступен: {exc}") from exc
    if resp.status_code == 400 and response_format is not None:
        raise _UnsupportedFormat(resp.text[:200])
    if resp.status_code != 200:
        raise AiError(f"OpenAI-совместимый API HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AiError("OpenAI-совместимый API вернул ответ без текста") from exc
    if isinstance(content, list):  # некоторые серверы отдают content частями
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content), data.get("usage") or {}


def _build_openai_messages(photos: list[PhotoIn]) -> list[dict]:
    content: list[dict] = []
    for i, photo in enumerate(photos, start=1):
        label = photo.label or SLOT_LABELS.get(photo.slot, photo.slot)
        content.append({"type": "text", "text": f"Фото {i}/{len(photos)}: «{label}»"})
        data = base64.b64encode(photo.data).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{photo.content_type};base64,{data}"}}
        )
    content.append({"type": "text", "text": "Оцени все пункты и верни JSON."})
    system = (
        SYSTEM_PROMPT
        + "\nСхема ответа (JSON Schema, других ключей быть не должно):\n"
        + json.dumps(JSON_SCHEMA, ensure_ascii=False)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


# Лестница форматов: строгая схема → json_object → просто текст (парсим сами)
_FORMAT_LADDER: list[tuple[str, dict | None]] = [
    (
        "json_schema",
        {
            "type": "json_schema",
            "json_schema": {"name": "checklist_verdict", "schema": JSON_SCHEMA, "strict": True},
        },
    ),
    ("json_object", {"type": "json_object"}),
    ("prompt", None),
]


def _run_attempts(generate: Callable[[str | None], tuple[str, dict]]) -> tuple[AiVerdict, dict]:
    """Две попытки: вторая — с корректирующей подсказкой. generate(hint) → (текст, usage)."""
    last_error = ""
    for attempt in (1, 2):
        hint = None
        if attempt > 1:
            hint = f"Предыдущий ответ отклонён ({last_error}). Верни строго JSON по схеме."
        text, usage = generate(hint)
        try:
            verdict = parse_verdict(text)
        except AiError as exc:
            last_error = str(exc)
            log.warning("ИИ-проверка: попытка %s отклонена — %s", attempt, last_error)
            continue
        return normalize(verdict), {"attempts": attempt, "usage": usage}
    raise AiError(f"ИИ дважды вернул невалидный ответ: {last_error}")


def verify_photos(photos: list[PhotoIn]) -> tuple[AiVerdict, dict]:
    """→ (нормализованный вердикт, метаданные вызова)."""
    provider = resolve_provider()
    started = time.monotonic()
    s = get_settings()
    if provider == "mock":
        # No image has been examined. Let the submission endpoint persist the
        # photos with unavailable_verdict() for coordinator review; an admin's
        # AI connection test must also report unavailable, never a fake success.
        raise AiError("ИИ-проверка фото не настроена — требуется ручная проверка координатором")

    if provider == "gemini":
        parts = _build_parts(photos)

        def generate_gemini(hint: str | None) -> tuple[str, dict]:
            return _gemini_generate(parts if hint is None else [*parts, {"text": hint}])

        verdict, info = _run_attempts(generate_gemini)
        return verdict, {
            "provider": "gemini",
            "model": s.gemini_model,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "attempts": info["attempts"],
            "tokens": info["usage"].get("totalTokenCount"),
        }

    if provider == "openai_compat":
        messages = _build_openai_messages(photos)
        ladder = list(_FORMAT_LADDER)
        used_format = ladder[0][0]

        def generate_openai(hint: str | None) -> tuple[str, dict]:
            nonlocal used_format
            msgs = messages if hint is None else [*messages, {"role": "user", "content": hint}]
            while True:
                name, fmt = ladder[0]
                try:
                    text, usage = _openai_chat(msgs, fmt)
                except _UnsupportedFormat as exc:
                    if len(ladder) == 1:
                        raise AiError(f"сервер отверг все форматы ответа: {exc}") from exc
                    log.info("ИИ-проверка: response_format=%s не поддержан, пробуем проще", name)
                    ladder.pop(0)
                    continue
                used_format = name
                return text, usage

        verdict, info = _run_attempts(generate_openai)
        return verdict, {
            "provider": "openai_compat",
            "model": s.openai_compat_model,
            "host": urlparse(s.openai_compat_base_url).netloc,
            "format": used_format,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "attempts": info["attempts"],
            "tokens": info["usage"].get("total_tokens"),
        }

    raise AiError(f"неизвестный провайдер ИИ: {provider}")
