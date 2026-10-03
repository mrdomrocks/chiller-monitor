#!/usr/bin/env bash
# Build an offline Linux archive for 64-bit Python 3.11–3.14.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
VERSION=$(.venv/bin/python -c 'from app import __version__; print(__version__)')
WORK="$ROOT/packaging/.build/linux"
SRC="$WORK/chiller-monitor"
WHEELS="$SRC/wheels"

rm -rf "$SRC"
mkdir -p "$WHEELS" "$ROOT/dist"
rsync -a --exclude '__pycache__' "$ROOT/app" "$ROOT/static" "$SRC/"
cp "$ROOT/packaging/requirements-runtime.txt" "$SRC/requirements-runtime.txt"
cp "$ROOT/packaging/linux/install.sh" "$ROOT/packaging/linux/uninstall.sh" "$ROOT/packaging/linux/README.txt" "$SRC/"
chmod +x "$SRC/install.sh" "$SRC/uninstall.sh"

download() {
  local ver="$1" abi="$2" platform="$3"
  .venv/bin/python -m pip download \
    -r "$ROOT/packaging/requirements-runtime.txt" \
    -d "$WHEELS" \
    --only-binary=:all: \
    --platform "$platform" \
    --python-version "$ver" \
    --implementation cp \
    --abi "$abi"
}

for spec in 3.11:cp311 3.12:cp312 3.13:cp313 3.14:cp314; do
  ver=${spec%%:*}
  abi=${spec##*:}
  if ! download "$ver" "$abi" manylinux2014_x86_64; then
    echo "Retrying Python $ver wheels for a newer manylinux tag"
    download "$ver" "$abi" manylinux_2_28_x86_64
  fi
done

ARCHIVE="$ROOT/dist/chiller-monitor-${VERSION}-linux-x86_64.tar.gz"
tar -C "$WORK" -czf "$ARCHIVE" chiller-monitor
echo "Linux archive: $ARCHIVE"
