#!/usr/bin/env pwsh
#Requires -Version 7
$envFile = ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
    $pair = $_ -split '=', 2
    if ($pair.Length -eq 2) { [Environment]::SetEnvironmentVariable($pair[0].Trim(), $pair[1].Trim(), "Process") }
  }
}
if (-not $env:TRADER_AUTOSTART) { $env:TRADER_AUTOSTART = "1" }
$port = if ($env:PORT) { $env:PORT } else { "8000" }
uvicorn crypto_ai_bot.app.server:app --host 0.0.0.0 --port $port
