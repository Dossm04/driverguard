# PDF-демо для менторов (RU и KZ)

`docs/DriverGuard_демо_RU.pdf` и `docs/DriverGuard_демо_KZ.pdf` — обзор системы: архитектура, каждая
страница панели и PWA со скриншотами, Telegram-бот, устройство, скоринг, ML-контур, сценарий показа,
запуск, статус. Собираются из одного источника `build.py` (тексты на двух языках рядом, `L(ru, kz)`).

## Пересобрать

```bash
# 1. стек запущен (make demo или backend :8000 + web :3000), затем свежие скриншоты:
cd web && node ../docs/demo-pdf/shots.js            # → docs/screens/demo/*.png
# 2. PDF (нужны Pillow в backend/.venv и Playwright из web/node_modules):
cd .. && backend/.venv/bin/python docs/demo-pdf/build.py docs/screens/demo
```

`render.js` печатает HTML в A4 через Chromium (шрифт DejaVu Sans — кириллица и казахские буквы без
дополнительных шрифтов). Скриншоты в `docs/screens/demo/` уменьшены до 1200 px по ширине.
