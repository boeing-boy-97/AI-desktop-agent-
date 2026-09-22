# ============================================================================
# NOVA — Windows installer script
# Installs the NOVA desktop voice agent from a packaged build directory.
#
#   powershell -ExecutionPolicy Bypass -File .\installer\install.ps1
#
# Optional switches:
#   -NoAutoStart   skip the Start Menu / Run-at-login autostart entry
#   -InstallDir D:\Nova   (default: $env:LOCALAPPDATA\NOVA)
# ============================================================================
param(
    [string]$InstallDir = "",
    [switch]$NoAutoStart
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  === NOVA — Neural Operating & Voice Automation Assistant ===" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Resolve install dir
# ---------------------------------------------------------------------------
if (-not $InstallDir) {
    $InstallDir = Join-Path $env:LOCALAPPDATA "NOVA"
}
Write-Host "[1/7] Target directory: $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# ---------------------------------------------------------------------------
# 2. Copy packaged files (dist\*.exe expected next to installer dir)
# ---------------------------------------------------------------------------
$src = Join-Path $PSScriptRoot "..\dist"
Write-Host "[2/7] Copying binaries from $src …"
if (Test-Path $src) {
    Copy-Item -Path (Join-Path $src "*") -Destination $InstallDir -Recurse -Force
} else {
    Write-Warning "dist\ not found — no prebuilt exe to copy."
}

# ---------------------------------------------------------------------------
# 3. Python backend (when running from source checkout)
# ---------------------------------------------------------------------------
$backend = Join-Path $PSScriptRoot "..\backend"
if (Test-Path (Join-Path $backend "main.py")) {
    Write-Host "[3/7] Source checkout detected — creating launcher scripts."
    $py = (Get-Command python -ErrorAction SilentlyContinue)
    if ($py) {
        $launcher = Join-Path $InstallDir "start_nova.ps1"
        @"
`$root = Split-Path -Parent `$MyInvocation.MyCommand.Path
cd "$backend"
Start-Process python -ArgumentList "-m","backend.main","--port","8765" -WindowStyle Hidden
"@ | Out-File -Encoding utf8 $launcher
    }
}

# ---------------------------------------------------------------------------
# 4. Create shortcut + optional autostart
# ---------------------------------------------------------------------------
Write-Host "[4/7] Creating shortcuts …"
$ws = New-Object -ComObject WScript.Shell
$startMenu = [Environment]::GetFolderPath("Programs") + "\NOVA"
New-Item -ItemType Directory -Force -Path $startMenu | Out-Null

$desktopExe = Join-Path $InstallDir "NovaDesktop.exe"
if (Test-Path $desktopExe) {
    $lnk = $ws.CreateShortcut((Join-Path $startMenu "NOVA.lnk"))
    $lnk.TargetPath = $desktopExe
    $lnk.WorkingDirectory = $InstallDir
    $lnk.Save()
}

if (-not $NoAutoStart) {
    Write-Host "[5/7] Enabling auto-start (optional)…"
    if (Test-Path $desktopExe) {
        $startup = [Environment]::GetFolderPath("Startup")
        $lnk = $ws.CreateShortcut((Join-Path $startup "NOVA.lnk"))
        $lnk.TargetPath = $desktopExe
        $lnk.WorkingDirectory = $InstallDir
        $lnk.Save()
    }
} else {
    Write-Host "[5/7] Auto-start skipped (-NoAutoStart)."
}

# ---------------------------------------------------------------------------
# 6. Environment template
# ---------------------------------------------------------------------------
Write-Host "[6/7] Writing .env template…"
$envTemplate = Join-Path $PSScriptRoot "..\.env.example"
if (Test-Path $envTemplate) {
    Copy-Item $envTemplate (Join-Path $InstallDir ".env.example") -Force
}

# ---------------------------------------------------------------------------
# 7. Done
# ---------------------------------------------------------------------------
Write-Host "[7/7] Installation complete." -ForegroundColor Green
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Cyan
Write-Host "    1. Configure AI:   setx OPENAI_API_KEY sk-…        (or edit $InstallDir\.env.example)"
Write-Host "    2. Start NOVA:     $InstallDir\NovaDesktop.exe"
Write-Host "    3. The floating orb appears; click it to talk."
Write-Host ""
