#!/usr/bin/env pwsh
Param(
    [int]$Port = $(if ($env:PORT) { [int]$env:PORT } else { 8000 })
)

# Подхватываем .env (простая загрузка key=value)
$envFile = Join-Path (Get-Location) ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#') { return }
        if ($_ -match '^\s*$') { return }
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
            $key = $matches[1]
            # снимаем кавычки, если есть
            $val = $matches[2].Trim()
            if ($val.StartsWith('"') -and $val.EndsWith('"')) { $val = $val.Trim('"') }
            elseif ($val.StartsWith("'") -and $val.EndsWith("'")) { $val = $val.Trim("'") }
            [System.Environment]::SetEnvironmentVariable($key, $val)
        }
    }
}

if (-not $env:TRADER_AUTOSTART) { $env:TRADER_AUTOSTART = "1" }

# Предпочитаем запуск через python -m uvicorn (не зависит от PATH)
$python = (Get-Command python -ErrorAction SilentlyContinue)?.Source
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue)?.Source }

if ($python) {
    & $python -m uvicorn "crypto_ai_bot.app.server:app" --host "0.0.0.0" --port $Port
    exit $LASTEXITCODE
} else {
    # Фолбэк: uvicorn из PATH
    uvicorn "crypto_ai_bot.app.server:app" --host "0.0.0.0" --port $Port
    exit $LASTEXITCODE
}
