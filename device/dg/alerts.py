"""Каскад алертов (DEV-15): уровень 1 — двойной сигнал + подсказка, уровень 2 — сирена до отмены.

Звук: simpleaudio → pygame → без звука (лог). Голосовая подсказка — espeak, если установлен.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from datetime import datetime

import numpy as np

log = logging.getLogger("dg.alerts")
RATE = 22050
HINTS = {
    "fatigue": "Признаки усталости. Сделайте перерыв на ближайшей стоянке.",
    "head_nod": "Вы клюёте носом. Остановитесь и отдохните.",
    "distraction": "Внимание на дорогу.",
    "speeding": "Превышение скорости. Снизьте скорость.",
    "microsleep": "Проснитесь! Остановитесь немедленно.",
    "phone": "Уберите телефон.",
    "camera_sabotage": "Камера не видит водителя.",
    "smoking": "Курение за рулём.",
    "seatbelt": "Пристегните ремень.",
}


def _tone(freq: float, ms: int, volume: float) -> np.ndarray:
    t = np.linspace(0, ms / 1000, int(RATE * ms / 1000), endpoint=False)
    wave = np.sin(2 * np.pi * freq * t)
    env = np.minimum(1, np.minimum(t * 50, (t[-1] - t) * 50 + 1e-3))  # плавные края
    return (wave * env * volume * 32767).astype(np.int16)


class Player:
    """Проигрывает int16-массив; выбирает доступный backend один раз."""

    def __init__(self):
        self.backend = None
        try:
            import simpleaudio  # noqa: F401

            self.backend = "simpleaudio"
        except Exception:  # noqa: BLE001
            try:
                import pygame

                pygame.mixer.init(frequency=RATE, size=-16, channels=1)
                self.backend = "pygame"
            except Exception:  # noqa: BLE001
                self.backend = None
        log.info("Аудио: %s", self.backend or "нет (только лог)")

    def play(self, samples: np.ndarray, block: bool = True) -> None:
        if self.backend == "simpleaudio":
            import simpleaudio

            obj = simpleaudio.play_buffer(samples.tobytes(), 1, 2, RATE)
            if block:
                obj.wait_done()
        elif self.backend == "pygame":
            import pygame

            sound = pygame.sndarray.make_sound(samples.copy())
            sound.play()
            if block:
                time.sleep(len(samples) / RATE)
        elif block:
            time.sleep(len(samples) / RATE)


class Alerts:
    def __init__(self, volume_day: float = 0.8, volume_night: float = 0.5, enabled: bool = True):
        self.enabled = enabled
        self.volume_day, self.volume_night = volume_day, volume_night
        self.player = Player() if enabled else None
        self._siren = threading.Event()
        self._siren_thread: threading.Thread | None = None
        self.espeak = shutil.which("espeak") or shutil.which("espeak-ng")
        self.log: list[tuple[str, str]] = []

    @property
    def volume(self) -> float:
        hour = datetime.now().hour
        return self.volume_night if hour >= 22 or hour < 6 else self.volume_day

    def level1(self, event_type: str) -> None:
        """Короткий двойной сигнал + голосовая подсказка."""
        self.log.append(("level1", event_type))
        log.info("Алерт 1: %s — %s", event_type, HINTS.get(event_type, ""))
        if not self.player:
            return
        beep = np.concatenate(
            [_tone(880, 120, self.volume), np.zeros(int(RATE * 0.08), np.int16), _tone(880, 120, self.volume)]
        )
        threading.Thread(target=self._beep_and_say, args=(beep, HINTS.get(event_type, "")), daemon=True).start()

    def _beep_and_say(self, beep: np.ndarray, text: str) -> None:
        self.player.play(beep)
        if text and self.espeak:
            subprocess.run([self.espeak, "-v", "ru", text], check=False, capture_output=True)

    def siren_on(self) -> None:
        """Уровень 2: сирена, пока не вызовут siren_off (минимум 2 с)."""
        if self._siren.is_set():
            return
        self.log.append(("siren_on", ""))
        log.warning("Алерт 2: СИРЕНА")
        self._siren.set()
        if self.player:
            self._siren_thread = threading.Thread(target=self._siren_loop, daemon=True)
            self._siren_thread.start()

    def _siren_loop(self) -> None:
        started = time.monotonic()
        pattern = np.concatenate([_tone(660, 250, self.volume), _tone(990, 250, self.volume)])
        while self._siren.is_set() or time.monotonic() - started < 2.0:
            self.player.play(pattern)

    def siren_off(self) -> None:
        if self._siren.is_set():
            self.log.append(("siren_off", ""))
            self._siren.clear()

    def stop(self) -> None:
        self.siren_off()
