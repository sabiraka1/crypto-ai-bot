# tools/cleanup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $MyInvocation.MyCommand.Path -Parent) | Out-Null
Set-Location ..  # перейти в корень репо

# 1) Удаляем устаревший конфиг-модуль (мы уже на core.settings)
if (Test-Path "src\crypto_ai_bot\config") {
  git rm -r --cached src\crypto_ai_bot\config 2>$null | Out-Null
  Remove-Item -Recurse -Force src\crypto_ai_bot\config
  Write-Host "Removed src/crypto_ai_bot/config"
}

# 2) Удаляем старые дублёры индикаторов/сигналов (если остались)
$legacy = @(
  "src\crypto_ai_bot\analysis\indicators.py",
  "src\crypto_ai_bot\analysis\technical_indicators.py",
  "src\crypto_ai_bot\signals\entry_policy.py",
  "src\crypto_ai_bot\signals\signal_validator.py",
  "src\crypto_ai_bot\trading\signals\signal_aggregator.py",
  "src\crypto_ai_bot\telegram\commands.py",
  "src\crypto_ai_bot\telegram\api_utils.py"
)
foreach ($f in $legacy) {
  if (Test-Path $f) {
    git rm --cached $f 2>$null | Out-Null
    Remove-Item -Force $f
    Write-Host "Removed $f"
  }
}

# 3) Проверка на импорты старых путей
$bad = Select-String -Path "src\**\*.py" -Pattern `
  "crypto_ai_bot\.config\.settings|analysis\.technical_indicators|signals\.signal_validator|signals\.entry_policy|trading\.signals\.signal_aggregator"

if ($bad) {
  Write-Host "`n⚠ Найдены упоминания старых модулей:" -ForegroundColor Yellow
  $bad | Select-Object Path,LineNumber,Line | Format-List
} else {
  Write-Host "`n✅ Следов старых модулей не найдено."
}

Write-Host "`nГотово. Не забудь закоммитить изменения:" -ForegroundColor Cyan
Write-Host "  git add -A && git commit -m `"cleanup: drop legacy modules and switch to core.settings`""
