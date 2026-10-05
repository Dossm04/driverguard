# DriverGuard — проверка компьютера. Запускается через check-machine.bat
# PowerShell есть на всех Windows 10 и 11, ставить ничего не нужно.

$ErrorActionPreference = "SilentlyContinue"
$missing = New-Object System.Collections.ArrayList
$warn    = New-Object System.Collections.ArrayList

function Line { param($c = "-") Write-Host ("  " + ($c * 60)) -ForegroundColor DarkGray }
function Ok   { param($t) Write-Host "  [есть]  " -ForegroundColor Green -NoNewline; Write-Host $t }
function No   { param($t, $why, $where, $note)
    Write-Host "  [НЕТ]   " -ForegroundColor Red -NoNewline; Write-Host $t -ForegroundColor White
    Write-Host "          Зачем: $why" -ForegroundColor Gray
    Write-Host "          Скачать: $where" -ForegroundColor Cyan
    if ($note) { Write-Host "          $note" -ForegroundColor Yellow }
    [void]$missing.Add($t)
}
function Warn { param($t, $fix)
    Write-Host "  [!]     " -ForegroundColor Yellow -NoNewline; Write-Host $t
    if ($fix) { Write-Host "          $fix" -ForegroundColor Gray }
    [void]$warn.Add($t)
}

function Has { param($cmd) return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Ver { param($cmd, $arg = "--version")
    try { return (& $cmd $arg 2>&1 | Select-Object -First 1) } catch { return $null }
}

Clear-Host
Write-Host ""
Line "="
Write-Host "   DriverGuard: что установлено на этом компьютере" -ForegroundColor White
Line "="
Write-Host ""

$os = (Get-CimInstance Win32_OperatingSystem)
Write-Host "  Система: $($os.Caption) $($os.OSArchitecture)"
$ramGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
Write-Host "  Оперативная память: $ramGb ГБ"
$free = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
Write-Host "  Свободно на диске C: $free ГБ"
Write-Host ""
Line
Write-Host "   ЧТО НУЖНО ДЛЯ ПРОЕКТА" -ForegroundColor White
Line
Write-Host ""

# ── Git ──
if (Has git) { Ok (Ver git) }
else { No "Git" "скачать проект и вести историю изменений" `
          "https://git-scm.com/download/win" "При установке оставьте все галочки по умолчанию" }

# ── Python ──
$py = $null
if (Has python) { $py = Ver python }
elseif (Has py) {
    # Лаунчер py требует два отдельных аргумента: "py -3 --version".
    # Передать их одной строкой нельзя — команда не выполнится.
    try { $py = (& py -3 --version 2>&1 | Select-Object -First 1) } catch { $py = $null }
}
if ($py -and $py -match "(\d+)\.(\d+)") {
    $maj = [int]$Matches[1]; $min = [int]$Matches[2]
    if ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 11)) { Ok $py }
    else { Warn "$py — нужна версия 3.11 или новее" "Скачайте свежую с https://python.org/downloads" }
} else {
    No "Python" "сервер, агент устройства, скрипты проверки" `
       "https://python.org/downloads" "ВАЖНО: поставьте галочку «Add python.exe to PATH»"
}

# ── Node.js ──
if (Has node) {
    $nv = Ver node
    if ($nv -match "v(\d+)") {
        if ([int]$Matches[1] -ge 18) { Ok "Node.js $nv" }
        else { Warn "Node.js $nv — нужна 18 или новее" "Скачайте LTS с https://nodejs.org" }
    } else { Ok "Node.js $nv" }
} else {
    No "Node.js" "панель координатора и приложение водителя" `
       "https://nodejs.org — берите версию LTS" $null
}

# ── Docker ──
if (Has docker) {
    Ok (Ver docker)
    docker info *>$null
    if ($LASTEXITCODE -ne 0) {
        Warn "Docker установлен, но не запущен" `
             "Откройте Docker Desktop и дождитесь зелёного значка внизу слева"
    } else { Ok "Docker запущен и отвечает" }
} else {
    No "Docker Desktop" "база данных, хранилище фото, весь стенд одной командой" `
       "https://docker.com/products/docker-desktop" `
       "Требует WSL2 — установщик предложит сам, соглашайтесь"
}

# ── make ──
if (Has make) { Ok "make" }
else { Warn "make — не обязателен" `
            "Без него команды make demo не работают, но есть прямые команды в docs/demo-jury.md" }

Write-Host ""
Line

# ── Предупреждения по железу ──
if ($ramGb -lt 8) {
    Write-Host "  [!]     Оперативной памяти $ramGb ГБ — Docker будет тесно" -ForegroundColor Yellow
    Write-Host "          Нужно 8 ГБ и больше. Закрывайте браузер во время показа." -ForegroundColor Gray
}
if ($free -lt 15) {
    Write-Host "  [!]     На диске $free ГБ — мало" -ForegroundColor Yellow
    Write-Host "          Docker, образы и зависимости займут около 15 ГБ." -ForegroundColor Gray
}

Write-Host ""
Line "="
if ($missing.Count -eq 0) {
    Write-Host "   ВСЁ НА МЕСТЕ. Можно запускать проект." -ForegroundColor Green
    Line "="
    Write-Host ""
    Write-Host "   Дальше по порядку:" -ForegroundColor White
    Write-Host "     1. Распакуйте архив проекта в удобную папку"
    Write-Host "     2. Откройте эту папку в терминале"
    Write-Host "     3. make demo"
    Write-Host "     4. Откройте http://localhost:3000"
} else {
    Write-Host "   НЕ ХВАТАЕТ: $($missing -join ', ')" -ForegroundColor Red
    Line "="
    Write-Host ""
    Write-Host "   Устанавливайте в этом порядке:" -ForegroundColor White
    Write-Host "     1. Git"
    Write-Host "     2. Python — с галочкой «Add python.exe to PATH»"
    Write-Host "     3. Node.js LTS"
    Write-Host "     4. Docker Desktop — последним, он самый тяжёлый"
    Write-Host ""
    Write-Host "   После каждой установки ЗАКРОЙТЕ и откройте терминал заново," -ForegroundColor Yellow
    Write-Host "   иначе новые команды не появятся." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   Когда всё поставите — запустите этот файл снова."
}
Write-Host ""
Line "="
Write-Host ""
Read-Host "  Нажмите Enter, чтобы закрыть"
