@echo off
REM DriverGuard - proverka kompyutera. Dvoynoy klik po etomu faylu.
REM Batnik tolko zapuskaet PowerShell: on pravilno pokazyvaet russkiy tekst.
chcp 65001 >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0check-machine.ps1"
if errorlevel 1 (
  echo.
  echo   Ne udalos zapustit proverku.
  echo   Otkroyte PowerShell i vypolnite vruchnuyu:
  echo     powershell -ExecutionPolicy Bypass -File check-machine.ps1
  echo.
  pause
)
