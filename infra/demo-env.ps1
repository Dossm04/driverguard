function Read-DgEnv([string]$Path) {
    $values = @{}
    foreach ($line in (Get-Content -LiteralPath $Path -Encoding UTF8)) {
        if ($line -match '^([A-Z0-9_]+)=(.*)$') {
            $value = ($matches[2] -split '\s+#', 2)[0].Trim()
            $values[$matches[1]] = $value.Trim('"').Trim("'")
        }
    }
    return $values
}

function ConvertFrom-DgContainerEnv($Container) {
    $values = @{}
    foreach ($entry in $Container.Config.Env) {
        $pair = $entry -split '=', 2
        if ($pair.Count -eq 2) { $values[$pair[0]] = $pair[1] }
    }
    return $values
}

function Restore-DgDemoEnv([string]$Destination, [object[]]$Containers) {
    if (Test-Path -LiteralPath $Destination) { return $false }
    $backend = @($Containers | Where-Object {
        $_.Config.Labels.'com.docker.compose.project' -eq 'driverguard-demo' -and
        $_.Config.Labels.'com.docker.compose.service' -eq 'backend'
    })
    if ($backend.Count -ne 1) { throw 'Cannot identify the existing DriverGuard backend. Keep its database and restore the original infra/.env.' }
    $active = ConvertFrom-DgContainerEnv $backend[0]
    $labels = $backend[0].Config.Labels
    $folders = @($labels.'com.docker.compose.project.working_dir')
    foreach ($config in ($labels.'com.docker.compose.project.config_files' -split ',')) {
        if ($config) { $folders += Split-Path -Parent $config }
    }
    $found = @()
    foreach ($folder in ($folders | Select-Object -Unique)) {
        # Only local paths explicitly recorded by this project's containers.
        if (-not $folder -or $folder.StartsWith('\\') -or -not [IO.Path]::IsPathRooted($folder)) { continue }
        $source = Join-Path $folder '.env'
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue }
        $values = Read-DgEnv $source
        $valid = $true
        foreach ($key in @('JWT_SECRET','MINIO_ROOT_USER','MINIO_ROOT_PASSWORD','ADMIN_PASSWORD','DRIVER_PIN','DG_SECRET','BOT_PASSWORD')) {
            if (-not $values.ContainsKey($key) -or -not $active.ContainsKey($key) -or $values[$key] -cne $active[$key]) { $valid = $false; break }
        }
        $databaseUrl = 'postgresql+psycopg://' + $values['POSTGRES_USER'] + ':' + $values['POSTGRES_PASSWORD'] + '@db:5432/' + $values['POSTGRES_DB']
        if ($databaseUrl -cne $active['DATABASE_URL']) { $valid = $false }
        if ($values['SEED'] -eq 'always') { $valid = $false }
        if ($valid) { $found += $source }
    }
    if ($found.Count -eq 0) {
        throw 'The original matching infra/.env was not found. No new passwords were generated; existing data is unchanged.'
    }
    # Do not overwrite a file created by another simultaneous launch.
    [IO.File]::Copy($found[0], $Destination, $false)
    Write-Host 'Recovered matching settings from the existing local DriverGuard installation. Database and passwords kept.'
    return $true
}
