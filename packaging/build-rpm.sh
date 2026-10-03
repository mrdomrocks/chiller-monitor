#!/usr/bin/env bash
# Build an RPM that installs under /opt and adds an application-menu entry.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
TOP="$ROOT/packaging/.build/rpm"
mkdir -p "$TOP" "$ROOT/dist"

export PATH="$ROOT/.venv/bin:$PATH"
rpmbuild -bb "$ROOT/packaging/chiller-monitor.spec" \
  --define "_topdir $TOP" \
  --define "_repodir $ROOT"

built=$(find "$TOP/RPMS" -type f -name 'chiller-monitor-*.rpm' -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)
if [[ -z "$built" ]]; then
  echo "rpmbuild did not produce an RPM" >&2
  exit 1
fi
cp -f "$built" "$ROOT/dist/$(basename "$built")"
echo "Linux RPM: $ROOT/dist/$(basename "$built")"
