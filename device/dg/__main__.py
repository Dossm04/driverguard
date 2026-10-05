"""Точка входа: python -m dg --simulate | --source 0 | --source video.mp4 (DEV-25)."""

from __future__ import annotations

import argparse
import logging
import sys

from dg import app, config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dg", description="DriverGuard device — DMS-мониторинг усталости водителя")
    parser.add_argument("--simulate", action="store_true", help="без камеры: события и движение по трассе")
    parser.add_argument("--source", default=None, help="индекс камеры (0) или путь к видеофайлу")
    parser.add_argument("--config", default=None, help="путь к config.yaml (по умолчанию device/config.yaml)")
    parser.add_argument("--api", default=None, help="URL backend, напр. http://localhost:8000/api/v1")
    parser.add_argument("--serial", default=None)
    parser.add_argument("--secret", default=None)
    parser.add_argument(
        "--gps",
        choices=["none", "gpsd", "sim"],
        default=None,
        help="источник GPS для камеры (по умолчанию gpsd, если доступен, иначе none)",
    )
    parser.add_argument("--no-sync", action="store_true", help="не отправлять на backend (только SQLite)")
    parser.add_argument("--no-sound", action="store_true")
    parser.add_argument("--display", action="store_true", help="окно с кадром и статусом (нужен GUI)")
    parser.add_argument("--duration", type=float, default=None, help="остановиться через N секунд")
    parser.add_argument("--speedup", type=float, default=1.0, help="ускорение симуляции (x1 = реальное время)")
    parser.add_argument("--seed", type=int, default=None, help="детерминированная симуляция")
    parser.add_argument(
        "--detector",
        choices=["auto", "on", "off"],
        default=None,
        help="детектор телефона/курения/ремня (YOLOv8-ONNX): auto — если есть модель и onnxruntime",
    )
    parser.add_argument("--yolo", default=None, help="путь к ONNX-модели детектора (иначе config.yaml detector.model)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    cfg = config.load(args.config)
    if args.api:
        cfg.api_url = args.api.rstrip("/")
    if args.serial:
        cfg.serial = args.serial
    if args.secret:
        cfg.secret = args.secret
    if args.yolo:
        cfg.detector_model = args.yolo

    if args.simulate:
        return app.run_simulate(
            cfg, sync=not args.no_sync, speedup=args.speedup, duration_s=args.duration, seed=args.seed
        )
    if args.source is None:
        parser.error("укажите --simulate или --source 0 | путь к видео")
    gps_mode = args.gps or ("gpsd" if _gpsd_available() else "none")
    return app.run_camera(
        cfg,
        args.source,
        gps_mode=gps_mode,
        sync=not args.no_sync,
        sound=not args.no_sound,
        display=args.display,
        duration_s=args.duration,
        detector_mode=args.detector,
    )


def _gpsd_available() -> bool:
    import socket

    try:
        with socket.create_connection(("127.0.0.1", 2947), timeout=0.3):
            return True
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(main())
