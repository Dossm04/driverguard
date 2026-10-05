"""Пробник ИИ-проверки: прогоняет комплект из 7 фото через настроенный провайдер
и печатает вердикт, латентность и токены. Для сравнения моделей на своей машине
(из облачной среды разработки llm.alem.ai недоступен).

  cd backend
  .venv/bin/python scripts/ai_probe.py              # провайдер из .env, фото — плейсхолдеры
  .venv/bin/python scripts/ai_probe.py ~/photos     # 7 фото: front_lights.jpg, rear_lights.jpg, …
  .venv/bin/python scripts/ai_probe.py ~/photos --provider gemini
  .venv/bin/python scripts/ai_probe.py ~/photos --provider openai_compat \\
      --model gemma4 --key sk-…

Имена файлов — по слотам (front_lights, rear_lights, left_side, right_side, tires,
windshield, under_engine) с расширением jpg/jpeg/png/webp; иначе берутся первые 7 по алфавиту.
"""

import argparse
import os
import struct
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

parser = argparse.ArgumentParser(description="Пробник ИИ-проверки чек-листа")
parser.add_argument(
    "folder", nargs="?", help="папка с 7 фото (без неё — синтетические плейсхолдеры)"
)
parser.add_argument("--provider", choices=["openai_compat", "gemini", "mock"])
parser.add_argument("--model", help="модель у провайдера: qwen3-8, gemma4, gemini-3.6-flash")
parser.add_argument("--key", help="API-ключ провайдера (иначе из .env)")
args = parser.parse_args()

# Переопределения — через окружение ДО импорта настроек
if args.provider:
    os.environ["AI_PROVIDER"] = args.provider
if args.model:
    os.environ["OPENAI_COMPAT_MODEL" if args.provider != "gemini" else "GEMINI_MODEL"] = args.model
if args.key:
    key_var = "GEMINI_API_KEY" if args.provider == "gemini" else "OPENAI_COMPAT_API_KEY"
    os.environ[key_var] = args.key

from app.ai_checklist import (  # noqa: E402
    AI_ITEMS,
    AiError,
    PhotoIn,
    compute_verdict,
    verify_photos,
)
from app.checklist_items import PHOTO_SLOTS  # noqa: E402

MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def placeholder_png(size: int = 256) -> bytes:
    rows = b"".join(b"\x00" + b"\x60\x60\x60" * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def load_photos(folder: str | None) -> list[PhotoIn]:
    if not folder:
        return [PhotoIn(slot, placeholder_png(), "image/png") for slot, _ in PHOTO_SLOTS]
    files = {p.stem: p for p in sorted(Path(folder).iterdir()) if p.suffix.lower() in MIME}
    photos = []
    for slot, _ in PHOTO_SLOTS:
        path = files.get(slot)
        if path is None:
            rest = [p for p in files.values() if p.stem not in dict(PHOTO_SLOTS)]
            if not rest:
                sys.exit(f"Нет файла для слота {slot} и нет запасных фото в {folder}")
            path = rest[0]
            files = {k: v for k, v in files.items() if v != path}
        photos.append(PhotoIn(slot, path.read_bytes(), MIME[path.suffix.lower()]))
    return photos


photos = load_photos(args.folder)
print(f"Фото: {len(photos)} ({'синтетические' if not args.folder else args.folder})")
started = time.monotonic()
try:
    verdict, meta = verify_photos(photos)
except AiError as exc:
    sys.exit(f"ОШИБКА ИИ: {exc}")
elapsed = time.monotonic() - started

print(
    f"Провайдер: {meta.get('provider')} · модель: {meta.get('model')} · "
    f"формат: {meta.get('format', '-')} · попыток: {meta.get('attempts')} · "
    f"токенов: {meta.get('tokens')} · {elapsed:.1f} с"
)
print(f"{'Пункт':<16}{'Статус':<13}{'Conf.':<7}Комментарий")
for key, title, critical in AI_ITEMS:
    item = getattr(verdict, key)
    mark = " *" if critical else ""
    print(f"{title + mark:<16}{item.статус:<13}{item.confidence:<7.2f}{item.комментарий}")
for damage in verdict.повреждения_кузова:
    print(f"  повреждение: {damage.описание} — {damage.зона}")
print(f"Вердикт сервера: {compute_verdict(verdict)}   (модель сказала: {verdict.вердикт})")
