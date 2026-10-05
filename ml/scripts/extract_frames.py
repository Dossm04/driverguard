#!/usr/bin/env python
"""Нарезка кадров из видео кабины (ML-1).

  python scripts/extract_frames.py video.mp4 --session 2026-09-10-ivanov --out data/raw/cabin
  python scripts/extract_frames.py night/*.mp4 --session-from-name --gray  # ИК-съёмка ночью

Имена файлов: <source>__<session>__000123.jpg — сессия нужна для сплита без утечки (split.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dgml.frames import extract_frames, safe_token  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Кадры из видео кабины → JPG для разметки")
    p.add_argument("videos", nargs="+", help="видеофайлы")
    p.add_argument("--out", default="data/raw/cabin", help="папка для кадров (относительно ml/)")
    p.add_argument("--source", default="cabin", help="источник: cabin (своя съёмка) | другое")
    p.add_argument("--session", default=None, help="id сессии (человек+поездка); по умолчанию — имя файла")
    p.add_argument("--session-from-name", action="store_true", help="сессия = имя файла без расширения")
    p.add_argument("--every-ms", type=int, default=500, help="шаг между кадрами, мс")
    p.add_argument("--min-hamming", type=int, default=6, help="отсев похожих кадров (dHash), 0 — не отсеивать")
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--gray", action="store_true", help="сохранять в оттенках серого (ИК)")
    a = p.parse_args(argv)
    total = 0
    for video in a.videos:
        session = a.session if (a.session and not a.session_from_name) else safe_token(Path(video).stem)
        n = extract_frames(video, a.out, session=session, source=a.source, every_ms=a.every_ms,
                           min_hamming=a.min_hamming, max_frames=a.max_frames, gray=a.gray)
        print(f"{video}: {n} кадров → {a.out} (сессия {session})")
        total += n
    print(f"Итого {total} кадров. Дальше: разметка (Roboflow/CVAT) → scripts/prepare_dataset.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
