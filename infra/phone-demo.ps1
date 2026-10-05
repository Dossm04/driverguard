param([switch]$Stop)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'demo-env.ps1')
$repo = Split-Path -Parent $PSScriptRoot
$docker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $docker) {
    foreach ($candidate in @("$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe", "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe")) {
        if (Test-Path -LiteralPath $candidate) { $docker = $candidate; break }
    }
}
if (-not $docker) { throw 'Start Docker Desktop, then START_DEMO.cmd first.' }
$envPath = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) { throw 'Run START_DEMO.cmd first.' }
$privateDir = Join-Path $repo '.runtime'
New-Item -ItemType Directory -Path $privateDir -Force | Out-Null
$statePath = Join-Path $privateDir 'phone-state.json'
$compose = @('compose','--env-file',$envPath,'-p','driverguard-demo','-f',(Join-Path $PSScriptRoot 'docker-compose.yml'),'-f',(Join-Path $PSScriptRoot 'docker-compose.phone.yml'),'--profile','full')
$keys = @('NEXT_PUBLIC_API_URL','NEXT_PUBLIC_WS_URL','CORS_ORIGINS','NEXT_PUBLIC_MP_WASM_URL')
function Write-DgUpdates([hashtable]$Updates) {
    $seen = @{}
    $lines = foreach ($line in (Get-Content -LiteralPath $envPath -Encoding UTF8)) {
        if ($line -match '^([A-Z0-9_]+)=') {
            $key = $matches[1]
            if ($Updates.ContainsKey($key)) {
                $seen[$key] = $true
                if ($null -ne $Updates[$key]) { $key + '=' + $Updates[$key] }
                continue
            }
        }
        $line
    }
    foreach ($key in $Updates.Keys) {
        if (-not $seen.ContainsKey($key) -and $null -ne $Updates[$key]) { $lines += $key + '=' + $Updates[$key] }
    }
    [IO.File]::WriteAllText($envPath, ($lines -join "`n") + "`n", (New-Object Text.UTF8Encoding($false)))
}
function Build-DgWeb {
    & $docker @compose build web
    if ($LASTEXITCODE -ne 0) { throw 'Web build failed. Settings are backed up in .runtime/phone-state.json; run STOP_PHONE.cmd to restore local mode.' }
    & $docker @compose up -d --no-deps --wait --wait-timeout 180 backend web
    if ($LASTEXITCODE -ne 0) { throw 'Backend/web is not ready. Inspect Docker Desktop logs.' }
}
if ($Stop) {
    & $docker @compose stop phone-api phone-web
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop HTTPS tunnels.' }
    if (Test-Path -LiteralPath $statePath) {
        $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($state.Active) {
            $restore = @{}
            foreach ($key in $keys) { $restore[$key] = $state.Original.$key }
            Write-DgUpdates $restore
            Build-DgWeb
            $state.Active = $false
            $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding UTF8
        }
    }
    Write-Host 'HTTPS access stopped. Local panel: http://localhost:3000/login. Database and photos kept.'
    exit 0
}
$settings = Read-DgEnv $envPath
if ($settings['SEED'] -eq 'always') { throw 'SEED=always is not allowed. Keep SEED=auto.' }
$null = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/health/ready' -TimeoutSec 10
# Fail closed if any seeded default password is still accepted, or API is unavailable.
$checks = @(
    @{ Route='auth/login'; Body=@{email='admin@driverguard.kz';password='admin123'} },
    @{ Route='auth/driver-login'; Body=@{phone='+77012441832';pin='1234'} },
    @{ Route='auth/device'; Body=@{serial='DG-0001';secret='device-secret-1'} }
)
foreach ($check in $checks) {
    $code = 0
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:8000/api/v1/' + $check.Route) -Method Post -ContentType 'application/json' -Body ($check.Body | ConvertTo-Json -Compress) -TimeoutSec 10
        $code = [int]$response.StatusCode
    } catch {
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        else { throw 'Cannot verify authentication before starting HTTPS.' }
    }
    if ($code -ne 401) { throw ('HTTPS not started: default-credential check returned ' + $code + '. Do not reset the database; inspect authentication.') }
}
$original = @{}
foreach ($key in $keys) { $original[$key] = $settings[$key] }
if (Test-Path -LiteralPath $statePath) {
    $previous = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($previous.Active) { foreach ($key in $keys) { $original[$key] = $previous.Original.$key } }
}
& $docker @compose up -d --no-deps phone-api phone-web
if ($LASTEXITCODE -ne 0) { throw 'Could not start HTTPS tunnels.' }
function Get-DgTunnelUrl([string]$Service) {
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        $logs = (& $docker @compose logs --no-color --tail 160 $Service | Out-String)
        if ($LASTEXITCODE -ne 0) { throw 'Cannot read HTTPS tunnel logs.' }
        $urls = [regex]::Matches($logs,'https://[a-z0-9-]+\.trycloudflare\.com')
        if ($urls.Count -gt 0) { return $urls[$urls.Count-1].Value }
        Start-Sleep -Seconds 2
    }
    throw 'Cloudflare did not provide an HTTPS address. Check internet and Docker logs.'
}
$apiUrl = Get-DgTunnelUrl 'phone-api'
$webUrl = Get-DgTunnelUrl 'phone-web'
$cors = @('http://localhost:3000','http://127.0.0.1:3000') + @($settings['CORS_ORIGINS'] -split ',' | Where-Object { $_ -and $_ -notlike '*trycloudflare.com*' }) + @($webUrl)
$updates = @{
    NEXT_PUBLIC_API_URL=($apiUrl + '/api/v1')
    NEXT_PUBLIC_WS_URL=($apiUrl.Replace('https://','wss://') + '/ws/live')
    CORS_ORIGINS=(($cors | Select-Object -Unique) -join ',')
    NEXT_PUBLIC_MP_WASM_URL='/mediapipe/wasm'
}
$state = [ordered]@{ Active=$true; Original=$original; WebUrl=$webUrl; ApiUrl=$apiUrl; Note='Temporary iPhone camera demo. STOP_PHONE.cmd restores local addresses without deleting data.' }
$state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding UTF8
$changed = $false
foreach ($key in $keys) { if ($settings[$key] -cne $updates[$key]) { $changed=$true } }
Write-DgUpdates $updates
if ($changed) { Build-DgWeb }
$link = $webUrl + '/driver/login'
[IO.File]::WriteAllText((Join-Path $privateDir 'PHONE_LINK.txt'),"Open on iPhone in Safari:`r`n$link`r`n`r`nPhone: +77012441832`r`nPIN: use ACCESS_LOCAL.txt in this folder.`r`nKeep Docker Desktop and this laptop running.`r`nStop HTTPS access: STOP_PHONE.cmd.`r`n",(New-Object Text.UTF8Encoding($true)))
Write-Host ('IPHONE: ' + $link)
Write-Host ('CAMERA: ' + $webUrl + '/driver/camera')
Write-Host 'The address is temporary. Keep this laptop awake and Docker Desktop running.'
Write-Host 'Local database and passwords are unchanged. STOP_PHONE.cmd returns to local mode.'
