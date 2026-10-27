#!/usr/bin/env bash
# Generación local, sin emulador, red, firma ni modificaciones a la app normal.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
FLUTTER_BIN="${FLUTTER_BIN:-flutter}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
cd "$ROOT/app"
"$FLUTTER_BIN" test --no-pub --dart-define=PLAY_CAPTURAS=true test_capturas/play_test.dart --reporter expanded
cd "$ROOT"
"$PYTHON_BIN" scripts/verificar_capturas.py --actualizar-manifiesto
