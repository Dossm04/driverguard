param([switch]$Stop, [switch]$NoOpen, [switch]$Rebuild)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'demo-env.ps1')
$docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $docker) {
    foreach ($candidate in @("$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe", "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe")) {
        if (Test-Path -LiteralPath $candidate) { $docker = $candidate; break }
    }
}
if (-not $docker) { throw 'Install Docker Desktop for Windows, start it, then run START_DEMO.cmd again.' }
& $docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop and wait until Engine is running.' }
$compose = @('compose', '--env-file', (Join-Path $PSScriptRoot '.env'), '-p', 'driverguard-demo', '-f', (Join-Path $PSScriptRoot 'docker-compose.yml'), '--profile', 'full')
function New-Hex([int]$count) {
    $bytes = New-Object byte[] $count
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}
$envPath = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    $existing = @(& $docker ps -aq --filter 'label=com.docker.compose.project=driverguard-demo')
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the existing DriverGuard installation.' }
    if ($existing.Count -gt 0) {
        $raw = & $docker inspect @existing
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect DriverGuard settings.' }
        $containers = @($raw | ConvertFrom-Json)
        $null = Restore-DgDemoEnv -Destination $envPath -Containers $containers
    } else {
        $volumes = @(& $docker volume ls --filter 'label=com.docker.compose.project=driverguard-demo' --format '{{.Name}}')
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect DriverGuard data volumes.' }
        if ($volumes.Count -gt 0) { throw 'DriverGuard data exists without its containers. Restore the original infra/.env before starting; no passwords or data were changed.' }
    }
}
if (-not (Test-Path -LiteralPath $envPath)) {
    $template = Get-Content -LiteralPath (Join-Path $PSScriptRoot '.env.example') -Encoding UTF8
    $values = [ordered]@{}
    foreach ($line in $template) { if ($line -match '^([A-Z0-9_]+)=(.*)$') { $values[$matches[1]] = ($matches[2] -split '\s+#',2)[0].Trim() } }
    $values['JWT_SECRET'] = New-Hex 32
    $values['POSTGRES_PASSWORD'] = New-Hex 16
    $values['MINIO_ROOT_PASSWORD'] = New-Hex 24
    $values['ADMIN_PASSWORD'] = New-Hex 10
    $values['DRIVER_PIN'] = [string]([Convert]::ToUInt32((New-Hex 4),16) % 900000 + 100000)
    $values['DG_SECRET'] = New-Hex 24
    $values['BOT_PASSWORD'] = New-Hex 18
    $values['DB_PORT'] = '15432'
    $values['DATABASE_URL'] = 'postgresql+psycopg://driverguard:' + $values['POSTGRES_PASSWORD'] + '@localhost:15432/driverguard'
    $values['HOST_BIND'] = '127.0.0.1'
    $values['AI_PROVIDER'] = 'mock'
    $values['DEMO_MODE'] = 'true'
    $values['SEED'] = 'auto'
    $envText = ($values.GetEnumerator() | ForEach-Object { $_.Key + '=' + $_.Value }) -join "`n"
    [IO.File]::WriteAllText($envPath, $envText + "`n", (New-Object Text.UTF8Encoding($false)))
}
$settings = Read-DgEnv $envPath
if ($Stop) {
    & $docker @compose stop
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the demo. Check Docker Desktop.' }
    Write-Host 'Stopped. Database and photos are kept.'
    exit 0
}
if ($settings['SEED'] -eq 'always') { throw 'SEED=always would erase data. Set SEED=auto in infra/.env before starting.' }
foreach ($service in @('backend','web')) {
    $imageId = & $docker image ls --filter "reference=driverguard-demo-$service" --format '{{.ID}}'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read Docker images.' }
    if (-not $imageId -or $Rebuild) {
        & $docker @compose build $service
        if ($LASTEXITCODE -ne 0) { throw "Build failed: $service. Check network and Docker memory." }
    }
}
& $docker @compose up -d --wait --wait-timeout 240 db minio minio-init backend web
if ($LASTEXITCODE -ne 0) { throw 'Demo did not become healthy. Open Docker Desktop and inspect driverguard-demo logs.' }
$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/health/ready' -TimeoutSec 10
$privateDir = Join-Path $repo '.runtime'
New-Item -ItemType Directory -Path $privateDir -Force | Out-Null
$access = @"
DriverGuard - LOCAL ACCESS. Do not publish this file or infra/.env.
Panel: http://localhost:3000/login
Email: admin@driverguard.kz
Password: $($settings['ADMIN_PASSWORD'])

Driver: http://localhost:3000/driver/login
Phone: +77012441832
PIN: $($settings['DRIVER_PIN'])

Camera: http://localhost:3000/driver/camera
AI photo checks: demo mock (no real image analysis).
STOP_DEMO.cmd stops the app and keeps its data.
Use a private window for the driver and a normal window for the panel.
"@
$accessPath = Join-Path $privateDir 'ACCESS_LOCAL.txt'
[IO.File]::WriteAllText($accessPath, $access, (New-Object Text.UTF8Encoding($true)))
Write-Host 'READY: http://localhost:3000'
Write-Host "Login details: $accessPath"
if (-not $NoOpen) {
    Start-Process -FilePath notepad.exe -ArgumentList ('"' + $accessPath + '"')
    Start-Process 'http://localhost:3000/login'
}
