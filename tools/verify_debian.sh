#!/bin/sh
# verify_debian.sh — run the whole suite on a Debian host.
#   tools/verify_debian.sh [BIN_DIR]
# Copies the static binaries to /tmp (executing from a 9p mount is slow and
# can be stale) and runs tools/regress.py.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
BIN=${1:-/tmp/fuai-bin}
rm -rf "$BIN"
mkdir -p "$BIN"
cp "$ROOT"/build/* "$BIN"/
chmod +x "$BIN"/*
cd "$ROOT"
python3 tools/regress.py --bin "$BIN"
