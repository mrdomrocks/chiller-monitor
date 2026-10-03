#!/usr/bin/env bash
# Build a per-user Windows installer. Python is bundled; Wine compiles the setup program.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
VERSION=$(.venv/bin/python -c 'from app import __version__; print(__version__)')
WORK="$ROOT/packaging/.build/windows"
STAGE="$WORK/staging"
NSIS="$ROOT/packaging/.build/nsis"
mkdir -p "$STAGE/python/Lib/site-packages" "$ROOT/dist"

PY_ZIP=""
PY_VER=""
for candidate in 3.12.10 3.12.9 3.12.8 3.12.7 3.13.5 3.13.3 3.13.2; do
  url="https://www.python.org/ftp/python/${candidate}/python-${candidate}-embed-amd64.zip"
  dest="$WORK/python-${candidate}-embed-amd64.zip"
  mkdir -p "$WORK"
  if [[ ! -f "$dest" ]]; then
    if ! curl -fL --retry 3 --retry-delay 2 -o "$dest" "$url"; then
      rm -f "$dest"
      continue
    fi
  fi
  if unzip -tqq "$dest"; then
    PY_ZIP="$dest"
    PY_VER="$candidate"
    break
  fi
  rm -f "$dest"
done
if [[ -z "$PY_ZIP" ]]; then
  echo "Could not download the Windows embeddable Python package." >&2
  exit 1
fi
echo "Using Windows Python $PY_VER"

rm -rf "$STAGE/python"
mkdir -p "$STAGE/python"
unzip -q -o "$PY_ZIP" -d "$STAGE/python"
pth=$(find "$STAGE/python" -maxdepth 1 -name 'python*._pth' | head -1)
zipname=$(grep -v '^#' "$pth" | grep -v '^$' | head -1)
printf '%s\n.\nLib\\site-packages\n..\nimport site\n' "$zipname" > "$pth"

abi="cp$(echo "$PY_VER" | awk -F. '{printf "%d%d", $1, $2}')"
py_short=$(echo "$PY_VER" | awk -F. '{printf "%d.%d", $1, $2}')

.venv/bin/python -m pip install \
  --target "$STAGE/python/Lib/site-packages" \
  --platform win_amd64 \
  --python-version "$py_short" \
  --implementation cp \
  --abi "$abi" \
  --only-binary=:all: \
  --upgrade \
  -r "$ROOT/packaging/requirements-windows.txt"
# pywebview is a wheel. Its proxy-tools dependency is published only as source.
.venv/bin/python -m pip install \
  --target "$STAGE/python/Lib/site-packages" \
  --platform win_amd64 \
  --python-version "$py_short" \
  --implementation cp \
  --abi "$abi" \
  --only-binary=:all: \
  --no-deps \
  --upgrade \
  pywebview==6.2.1
.venv/bin/python -m pip install \
  --target "$STAGE/python/Lib/site-packages" \
  --no-deps \
  --upgrade \
  proxy-tools

rm -rf "$STAGE/app" "$STAGE/static"
rsync -a --exclude '__pycache__' "$ROOT/app" "$ROOT/static" "$STAGE/"
cp "$ROOT/packaging/windows/Chiller Monitor.bat" "$STAGE/Chiller Monitor.bat"
cp "$ROOT/packaging/windows/chiller-monitor.pyw" "$STAGE/chiller-monitor.pyw"
cp "$ROOT/packaging/icons/chiller-monitor.ico" "$STAGE/chiller-monitor.ico"
cp "$ROOT/packaging/windows/README.txt" "$STAGE/README.txt"

if [[ ! -x "$NSIS/makensis.exe" ]]; then
  mkdir -p "$ROOT/packaging/.build"
  nsis_zip="$ROOT/packaging/.build/nsis.zip"
  if [[ ! -f "$nsis_zip" ]]; then
    curl -fL --retry 3 --retry-delay 2 -o "$nsis_zip" \
      "https://sourceforge.net/projects/nsis/files/NSIS%203/3.10/nsis-3.10.zip/download" \
      || curl -fL --retry 3 --retry-delay 2 -o "$nsis_zip" \
        "https://prdownloads.sourceforge.net/nsis/nsis-3.10.zip"
  fi
  rm -rf "$NSIS"
  unzip -q "$nsis_zip" -d "$ROOT/packaging/.build"
  extracted=$(find "$ROOT/packaging/.build" -maxdepth 2 -type f -name makensis.exe | head -1)
  if [[ -z "$extracted" ]]; then
    echo "NSIS archive did not contain makensis.exe" >&2
    exit 1
  fi
  if [[ "$(dirname "$extracted")" != "$NSIS" ]]; then
    mv "$(dirname "$extracted")" "$NSIS"
  fi
fi

outfile="$ROOT/dist/ChillerMonitor-${VERSION}-Setup.exe"
rm -f "$outfile"
sed "s|__OUTFILE__|../../../dist/ChillerMonitor-${VERSION}-Setup.exe|" \
  "$ROOT/packaging/windows/installer.nsi" > "$WORK/installer.nsi"

export WINEDEBUG=-all
(cd "$WORK" && wine "$NSIS/makensis.exe" installer.nsi)
echo "Windows installer: $outfile"
