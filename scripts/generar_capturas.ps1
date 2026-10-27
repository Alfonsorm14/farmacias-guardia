# Generación local, sin emulador, red, firma ni modificaciones a la app normal.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$flutterCommand = if ($env:FLUTTER_BIN) { $env:FLUTTER_BIN } else { 'flutter' }
$pythonCommand = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { 'python' }
Push-Location (Join-Path $repoRoot 'app')
try {
    & $flutterCommand test --no-pub --dart-define=PLAY_CAPTURAS=true test_capturas/play_test.dart --reporter expanded
    if ($LASTEXITCODE -ne 0) { throw 'Ha fallado la generación de capturas con Flutter.' }
    Set-Location $repoRoot
    & $pythonCommand scripts/verificar_capturas.py --actualizar-manifiesto
    if ($LASTEXITCODE -ne 0) { throw 'Ha fallado la validación de los PNG.' }
} finally {
    Pop-Location
}
