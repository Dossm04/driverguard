@echo off
cd /d "%~dp0"
set "DG_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%DG_PYTHON%" (
  echo Python with reportlab is required. Run: python infra\make-jury-cards.py
  pause
  exit /b 1
)
"%DG_PYTHON%" "%~dp0infra\make-jury-cards.py"
pause
