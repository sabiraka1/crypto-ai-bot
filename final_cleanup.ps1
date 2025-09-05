# final_cleanup.ps1
Write-Host "Final cleanup and import fixes..." -ForegroundColor Green

$basePath = "src\crypto_ai_bot"

# 1. Remove empty adapters folder
if (Test-Path "$basePath\app\adapters") {
    Remove-Item "$basePath\app\adapters" -Recurse -Force
    Write-Host "Removed app/adapters" -ForegroundColor Yellow
}

# 2. Move correlation_manager to rules folder
if (Test-Path "$basePath\core\domain\risk\correlation_manager.py") {
    Move-Item "$basePath\core\domain\risk\correlation_manager.py" `
              "$basePath\core\domain\risk\rules\correlation.py" -Force
    Write-Host "Moved correlation_manager to rules/correlation.py" -ForegroundColor Green
}

# 3. Fix imports in Python files
Write-Host "Fixing Python imports..." -ForegroundColor Yellow

# Function to fix imports in a file
function Fix-Imports {
    param($FilePath)
    
    if (Test-Path $FilePath) {
        $content = Get-Content $FilePath -Raw
        
        # Fix correlation imports
        $content = $content -replace "from crypto_ai_bot\.core\.domain\.risk\.rules\.correlation_manager import", `
                                     "from crypto_ai_bot.core.domain.risk.rules.correlation import"
        $content = $content -replace "from crypto_ai_bot\.core\.domain\.risk\.correlation_manager import", `
                                     "from crypto_ai_bot.core.domain.risk.rules.correlation import"
        
        # Fix telegram imports
        $content = $content -replace "from crypto_ai_bot\.app\.adapters\.telegram import", `
                                     "from crypto_ai_bot.app.telegram import"
        $content = $content -replace "from crypto_ai_bot\.app\.adapters\.telegram_bot import", `
                                     "from crypto_ai_bot.app.telegram_bot import"
        $content = $content -replace "from crypto_ai_bot\.app\.subscribers\.telegram_alerts import", `
                                     "from crypto_ai_bot.app.telegram_alerts import"
        
        # Fix base_strategy imports
        $content = $content -replace "from crypto_ai_bot\.core\.domain\.strategies\.base_strategy import", `
                                     "from crypto_ai_bot.core.domain.strategies.base import"
        
        # Fix macro_ports imports (if any)
        $content = $content -replace "from crypto_ai_bot\.core\.domain\.macro\.macro_ports import", `
                                     "from crypto_ai_bot.core.application.ports import"
        
        # Fix macro/sources imports
        $content = $content -replace "from crypto_ai_bot\.core\.infrastructure\.macro\.sources\.", `
                                     "from crypto_ai_bot.core.infrastructure.macro_sources."
        
        # Save if changed
        $originalContent = Get-Content $FilePath -Raw
        if ($content -ne $originalContent) {
            $content | Out-File -FilePath $FilePath -Encoding UTF8 -NoNewline
            return $true
        }
    }
    return $false
}

# Fix imports in all Python files
$pythonFiles = Get-ChildItem -Path $basePath -Filter "*.py" -Recurse
$fixedCount = 0

foreach ($file in $pythonFiles) {
    if (Fix-Imports -FilePath $file.FullName) {
        Write-Host "  Fixed: $($file.Name)" -ForegroundColor Cyan
        $fixedCount++
    }
}

Write-Host "Fixed imports in $fixedCount files" -ForegroundColor Green

# 4. Check if utils/exceptions.py is used
$exceptionsUsed = $false
foreach ($file in $pythonFiles) {
    $content = Get-Content $file.FullName -Raw
    if ($content -match "from crypto_ai_bot\.utils\.exceptions import" -or 
        $content -match "import crypto_ai_bot\.utils\.exceptions") {
        $exceptionsUsed = $true
        break
    }
}

if (-not $exceptionsUsed) {
    Write-Host "utils/exceptions.py is not used, consider removing" -ForegroundColor Yellow
} else {
    Write-Host "utils/exceptions.py is used, keeping it" -ForegroundColor Green
}

# 5. Final structure check
Write-Host "`n=== Final Structure Check ===" -ForegroundColor Cyan

$shouldNotExist = @(
    "$basePath\app\adapters",
    "$basePath\app\subscribers", 
    "$basePath\core\domain\risk\correlation_manager.py",
    "$basePath\core\domain\macro\macro_ports.py"
)

$shouldExist = @(
    "$basePath\core\domain\risk\rules\correlation.py",
    "$basePath\app\telegram.py",
    "$basePath\core\infrastructure\macro_sources"
)

Write-Host "Should NOT exist:" -ForegroundColor Yellow
foreach ($path in $shouldNotExist) {
    if (Test-Path $path) {
        Write-Host "  FOUND: $path (needs removal)" -ForegroundColor Red
    } else {
        Write-Host "  OK: Not found" -ForegroundColor Green
    }
}

Write-Host "`nShould exist:" -ForegroundColor Yellow
foreach ($path in $shouldExist) {
    if (Test-Path $path) {
        Write-Host "  OK: $path" -ForegroundColor Green
    } else {
        Write-Host "  MISSING: $path" -ForegroundColor Red
    }
}

Write-Host "`nCleanup complete!" -ForegroundColor Green