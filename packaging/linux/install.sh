#!/bin/sh
# Install Chiller Monitor for this user. No root account is required.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
DEST=${CHILLER_PREFIX:-"$HOME/.local/opt/chiller-monitor"}
PY=${PYTHON:-python3}

if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11 or newer is required. Found: $("$PY" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo missing)" >&2
  exit 1
fi

mkdir -p "$DEST"
rm -rf "$DEST/app" "$DEST/static"
tar -C "$ROOT" --exclude '__pycache__' -cf - app static | tar -C "$DEST" -xf -
cp "$ROOT/requirements-runtime.txt" "$DEST/requirements-runtime.txt"

if [ ! -x "$DEST/.venv/bin/python" ]; then
  rm -rf "$DEST/.venv"
  if ! "$PY" -m venv "$DEST/.venv"; then
    echo "Could not create a virtual environment. On Debian or Ubuntu, install python3-venv and run this again." >&2
    exit 1
  fi
fi

"$DEST/.venv/bin/python" -m pip install --no-index --find-links "$ROOT/wheels" -r "$DEST/requirements-runtime.txt"
SITE=$("$DEST/.venv/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')

cat > "$DEST/chiller-monitor" << EOF
#!/bin/sh
cd "$DEST"
export CHILLER_INSTALLED=1
export CHILLER_WINDOW=1
export PYTHONUTF8=1
export PYTHONPATH="$SITE\${PYTHONPATH:+:\$PYTHONPATH}"
if "$PY" -c 'import gi' >/dev/null 2>&1; then
  exec "$PY" -m app
fi
exec "$DEST/.venv/bin/python" -m app
EOF
chmod +x "$DEST/chiller-monitor"

mkdir -p "$HOME/.local/share/applications" "$HOME/.local/bin"
ln -sfn "$DEST/chiller-monitor" "$HOME/.local/bin/chiller-monitor"
cat > "$HOME/.local/share/applications/chiller-monitor.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Chiller Monitor
Comment=Local HMI for a chiller on Modbus TCP
Exec=$DEST/chiller-monitor
Terminal=false
StartupNotify=true
Categories=Utility;
EOF

echo "Installed for this user."
echo "Start it from the application menu, or run:"
echo "  $DEST/chiller-monitor"
echo "Site profiles are kept in \${XDG_DATA_HOME:-\$HOME/.local/share}/chiller-monitor"
