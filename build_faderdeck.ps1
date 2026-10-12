$ErrorActionPreference = "Stop"

$projectDir = $PSScriptRoot
$python = Join-Path $projectDir ".venv\Scripts\python.exe"
$entryPoint = Join-Path $projectDir "faderdeck_launcher.py"
$icon = Join-Path $projectDir "faderdeck.ico"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Could not find the project's virtual environment at $python. Run this build script from the FaderDeck project folder that contains .venv."
}

if (-not (Test-Path -LiteralPath $entryPoint)) {
    throw "Could not find faderdeck_launcher.py beside this build script."
}

if (-not (Test-Path -LiteralPath $icon)) {
    throw "Could not find the FaderDeck icon at $icon."
}

$null = & $python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    & $python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller could not be installed into the FaderDeck virtual environment."
    }
}

# A running FaderDeck locks dist\FaderDeck.exe (PyInstaller then fails with
# WinError 5). Ask it to quit properly; stopping it by force would leave a
# stale client behind in VoiceMeeter.
$builtExe = Join-Path $projectDir "dist\FaderDeck.exe"
if ((Get-Process FaderDeck -ErrorAction SilentlyContinue) -and (Test-Path -LiteralPath $builtExe)) {
    Write-Host "Asking the running FaderDeck to quit..."
    & $builtExe --quit
    Get-Process FaderDeck -ErrorAction SilentlyContinue | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue
    if (Get-Process FaderDeck -ErrorAction SilentlyContinue) {
        throw "FaderDeck is still running. Quit it from its tray icon, then build again."
    }
}

Push-Location $projectDir
try {
    & $python -m PyInstaller `
        --clean `
        --noconfirm `
        --onefile `
        --windowed `
        --name FaderDeck `
        --icon $icon `
        --add-data "$icon;." `
        --collect-all pycaw `
        --collect-all comtypes `
        --collect-all voicemeeterlib `
        --collect-all winappaudiorouter `
        $entryPoint

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed to build FaderDeck.exe."
    }
}
finally {
    Pop-Location
}

Write-Host "Built: $(Join-Path $projectDir 'dist\FaderDeck.exe')"