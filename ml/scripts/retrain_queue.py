#!/usr/bin/env python
"""Очередь дообучения (ML-5): ложные срабатывания из панели → кадры для доразметки.

  python scripts/retrain_queue.py --api http://localhost:8000/api/v1 --mark
  python scripts/retrain_queue.py --api http://192.168.1.20:8000/api/v1 --email admin@driverguard.kz --password admin123

Что делает: логинится координатором/админом → GET /retrain-queue?exported=false → для каждого события
скачивает клип (presigned-ссылка) и режет кадры вокруг момента события (клип устройства = 10 с до + 5 с после,
см. device/config.yaml clip.pre_s) в data/incoming/<дата>/<тип>/retrain__<uuid>__NN.jpg + meta.csv;
с --mark помечает элементы выгруженными (POST /retrain-queue/mark-exported).
Имя retrain__<uuid>__NN делает событие «сессией» для сплита без утечки (prepare_dataset.py).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dgml.classes import EVENT_BY_CLASS  # noqa: E402

LABEL_BY_EVENT = {v: k for k, v in EVENT_BY_CLASS.items()}  # событие → класс детектора (phone→phone, smoking→cigarette)


def login(api: str, email: str, password: str) -> str:
    r = requests.post(f"{api}/auth/login", json={"email": email, "password": password}, timeout=15)
    if r.status_code != 200:
        raise SystemExit(f"Вход не удался ({r.status_code}): {r.text[:200]}")
    return r.json()["access_token"]


def cut_frames(clip: Path, out_dir: Path, uuid8: str, offset_s: float, window_s: float, step_s: float) -> int:
    import cv2

    cap = cv2.VideoCapture(str(clip))
    if not cap.isOpened():
        return 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    t = max(0.0, offset_s - window_s)
    while t <= offset_s + window_s:
        idx = int(round(t * fps))
        if total and idx >= total:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            break
        cv2.imwrite(str(out_dir / f"retrain__{uuid8}__{n:02d}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        n += 1
        t += step_s
    cap.release()
    return n


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Выгрузка очереди дообучения из панели")
    p.add_argument("--api", default=os.environ.get("DG_API_URL", "http://localhost:8000/api/v1"))
    p.add_argument("--email", default=os.environ.get("DG_ADMIN_EMAIL", "admin@driverguard.kz"))
    p.add_argument("--password", default=os.environ.get("DG_ADMIN_PASSWORD", "admin123"))
    p.add_argument("--out", default="data/incoming")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--offset", type=float, default=10.0, help="секунда клипа с событием (device clip.pre_s)")
    p.add_argument("--window", type=float, default=1.0, help="± секунд вокруг события")
    p.add_argument("--step", type=float, default=0.25, help="шаг между кадрами, с")
    p.add_argument("--internal", action="store_true", help="ссылки на клипы внутри docker-сети (minio:9000)")
    p.add_argument("--mark", action="store_true", help="пометить выгруженные элементы в панели")
    a = p.parse_args(argv)
    api = a.api.rstrip("/")
    headers = {"Authorization": f"Bearer {login(api, a.email, a.password)}"}
    r = requests.get(f"{api}/retrain-queue", params={"exported": "false", "limit": a.limit,
                                                      "internal": str(a.internal).lower()}, headers=headers, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"GET /retrain-queue → {r.status_code}: {r.text[:200]}")
    items = r.json()["items"]
    if not items:
        print("Очередь дообучения пуста — ложных срабатываний нет")
        return 0
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    root = Path(a.out) / day
    root.mkdir(parents=True, exist_ok=True)
    meta_path = root / "meta.csv"
    new_meta = not meta_path.is_file()
    done_ids: list[int] = []
    frames_total = 0
    with meta_path.open("a", newline="", encoding="utf-8") as mf:
        w = csv.writer(mf)
        if new_meta:
            w.writerow(["queue_id", "event_uuid", "event_type", "label", "event_ts", "driver", "vehicle", "speed_kmh",
                        "model_version", "frames", "note"])
        for it in items:
            label = LABEL_BY_EVENT.get(it["event_type"], it["event_type"])
            uuid8 = it["event_uuid"].replace("-", "")[:8]
            frames = 0
            note = ""
            if it.get("clip_url"):
                try:
                    resp = requests.get(it["clip_url"], timeout=60, stream=True)
                    resp.raise_for_status()
                    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                        for chunk in resp.iter_content(1 << 16):
                            tmp.write(chunk)
                        tmp_path = Path(tmp.name)
                    frames = cut_frames(tmp_path, root / label, uuid8, a.offset, a.window, a.step)
                    tmp_path.unlink(missing_ok=True)
                    if not frames:
                        note = "клип не открылся"
                except (requests.RequestException, OSError) as exc:
                    note = f"клип не скачан: {exc.__class__.__name__}"
            else:
                note = "без клипа — только метаданные"
            w.writerow([
                it["id"], it["event_uuid"], it["event_type"], label, it["event_ts"], it.get("driver_name") or "",
                it.get("vehicle_plate") or "", it.get("speed_kmh") or "", it.get("model_version") or "", frames, note,
            ])
            frames_total += frames
            done_ids.append(it["id"])
            who = it.get("driver_name") or "—"
            print(f"{it['event_type']:<10} {it['event_ts'][:19]} {who:<14} кадров: {frames} {note}")
    print(f"\nВыгружено {len(done_ids)} событий, {frames_total} кадров → {root}")
    if a.mark and done_ids:
        r = requests.post(f"{api}/retrain-queue/mark-exported", json={"ids": done_ids}, headers=headers, timeout=30)
        print(f"Помечено выгруженными: {r.json().get('exported') if r.status_code == 200 else r.text[:200]}")
    print("Дальше: разметить кадры (Roboflow/CVAT), положить экспорт в data/raw/retrain-<дата>/ и "
          "scripts/prepare_dataset.py … --force → train.py --version vN+1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
