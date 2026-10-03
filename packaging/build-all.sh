#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
./build-rpm.sh
./build-windows.sh
