#!/usr/bin/env bash
# Build an RPM that installs under /opt and adds an application-menu entry.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
TOP="$ROOT/packaging/.build/rpm"
mkdir -p "$TOP" "$ROOT/dist"

rev=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo dev)
printf '%s\n' "$rev" > "$ROOT/packaging/.build/REVISION"
release=$(git -C "$ROOT" rev-list --count HEAD 2>/dev/null || echo 5)

export PATH="$ROOT/.venv/bin:$PATH"
rpmbuild -bb "$ROOT/packaging/chiller-monitor.spec" \
  --define "_topdir $TOP" \
  --define "_repodir $ROOT" \
  --define "chiller_release $release"

built=$(find "$TOP/RPMS" -type f -name 'chiller-monitor-*.rpm' -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)
if [[ -z "$built" ]]; then
  echo "rpmbuild did not produce an RPM" >&2
  exit 1
fi
cp -f "$built" "$ROOT/dist/$(basename "$built")"
echo "Linux RPM: $ROOT/dist/$(basename "$built")"
