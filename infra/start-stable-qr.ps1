param([switch]$Stop)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'demo-env.ps1')
$envPath = Join-Path $PSScriptRoot '.env'
$stateDir = Join-Path $repo '.runtime'
$statePath = Join-Path $stateDir 'stable-qr-state.json'
$domain = 'mothball-urgent-quaintly.ngrok-free.dev'
$public = 'https://' + $domain
$docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $docker) {
    foreach ($candidate in @("$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe", "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe")) {
        if (Test-Path -LiteralPath $candidate) { $docker = $candidate; break }
    }
}
if (-not $docker) { throw 'Start Docker Desktop first.' }
if (-not (Test-Path -LiteralPath $envPath)) { throw 'Run START_DEMO.cmd first. The database will not be reset.' }
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
$compose = @('compose','--env-file',$envPath,'-p','driverguard-demo','-f',(Join-Path $PSScriptRoot 'docker-compose.yml'),'-f',(Join-Path $PSScriptRoot 'docker-compose.stable-qr.yml'),'--profile','full')

function Set-DgEnv([hashtable]$changes) {
    $seen = @{}
    $lines = @()
    foreach ($line in (Get-Content -LiteralPath $envPath -Encoding UTF8)) {
        if ($line -match '^([A-Z0-9_]+)=') {
            $key = $matches[1]
            if ($changes.ContainsKey($key)) { $lines += $key + '=' + $changes[$key]; $seen[$key] = $true; continue }
        }
        $lines += $line
    }
    foreach ($key in $changes.Keys) {
        if (-not $seen.ContainsKey($key)) { $lines += $key + '=' + $changes[$key] }
    }
    [IO.File]::WriteAllText($envPath, ($lines -join "`n") + "`n", (New-Object Text.UTF8Encoding($false)))
}

function Build-DgWeb {
    & $docker @compose build web
    if ($LASTEXITCODE -ne 0) { throw 'Web build failed. Existing database was not changed.' }
    & $docker @compose up -d --no-deps --wait --wait-timeout 240 backend web
    if ($LASTEXITCODE -ne 0) { throw 'Web/backend did not become healthy. Existing database was not reset.' }
}

if ($Stop) {
    $settings = Read-DgEnv $envPath
    if (-not $settings['NGROK_AUTHTOKEN']) { Write-Host 'Stable tunnel is not configured.'; exit 0 }
    & $docker @compose stop stable-ngrok stable-gateway
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the stable tunnel.' }
    Set-DgEnv @{
        NEXT_PUBLIC_API_URL='http://localhost:8000/api/v1'
        NEXT_PUBLIC_WS_URL='ws://localhost:8000/ws/live'
        CORS_ORIGINS='http://localhost:3000,http://127.0.0.1:3000'
        NEXT_PUBLIC_MP_WASM_URL='/mediapipe/wasm'
    }
    Build-DgWeb
    Write-Host 'Stable tunnel stopped. Local panel: http://localhost:3000/login. Database and photos remain.'
    exit 0
}

& $docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop and wait until Engine is running.' }
$settings = Read-DgEnv $envPath
if ($settings['SEED'] -eq 'always') { throw 'SEED=always would reset data. Set SEED=auto first.' }
$null = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/health/ready' -TimeoutSec 10

if (-not $settings['NGROK_AUTHTOKEN']) {
    Write-Host 'In ngrok dashboard open Your Authtoken, click Copy, then paste it here.'
    Write-Host 'Input is hidden and the token stays only in infra/.env on this laptop.'
    $secure = Read-Host 'ngrok Authtoken' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    if (-not $token -or $token -match '\s' -or $token.StartsWith('rd_')) { throw 'That is not an ngrok Authtoken. Domain ID rd_... is not a token.' }
    Set-DgEnv @{ NGROK_AUTHTOKEN=$token }
    $token = $null
    $settings = Read-DgEnv $envPath
}

$desired = @{
    NEXT_PUBLIC_API_URL=($public + '/api/v1')
    NEXT_PUBLIC_WS_URL=('wss://' + $domain + '/ws/live')
    CORS_ORIGINS=('http://localhost:3000,http://127.0.0.1:3000,' + $public)
    NEXT_PUBLIC_MP_WASM_URL='/mediapipe/wasm'
}
$changed = $false
foreach ($key in $desired.Keys) { if ($settings[$key] -cne $desired[$key]) { $changed=$true } }
Set-DgEnv $desired
& $docker @compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Docker configuration invalid. The token was saved locally.' }
if ($changed) { Build-DgWeb }
& $docker @compose up -d --wait --wait-timeout 240 stable-gateway stable-ngrok
if ($LASTEXITCODE -ne 0) { throw 'ngrok tunnel did not start. Check Docker Desktop logs for driverguard-demo-stable-ngrok-1.' }

# Check public service without printing the credential or the full environment.
for ($i=0; $i -lt 6; $i++) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri ($public + '/api/v1/health/ready') -Headers @{'ngrok-skip-browser-warning'='true'} -TimeoutSec 12
        if ($response.StatusCode -eq 200 -and $response.Content -match '"db":"ok"') { break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (-not $response -or $response.StatusCode -ne 200 -or $response.Content -notmatch '"db":"ok"') {
    throw 'Public API not ready. Do not use the QR yet; inspect stable-ngrok logs.'
}
[IO.File]::WriteAllText((Join-Path $stateDir 'STABLE_LINK.txt'),"Jury: $public/jury.html`r`nPhone: $public/driver/login`r`nPanel: $public/login`r`nKeep Docker and the laptop online.`r`n",(New-Object Text.UTF8Encoding($false)))
$state = [ordered]@{ Domain=$domain; Active=$true; UpdatedAt=[DateTimeOffset]::UtcNow.ToString('o') }
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Host ('STABLE JURY: ' + $public + '/jury.html')
Write-Host ('STABLE PHONE: ' + $public + '/driver/login')
Write-Host ('STABLE PANEL: ' + $public + '/login')
Write-Host 'Login: use the existing number/PIN or admin password from .runtime/ACCESS_LOCAL.txt.'
Write-Host 'Database and photos are unchanged. Keep Docker Desktop and this laptop running.'
