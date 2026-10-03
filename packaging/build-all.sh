#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
./build-linux.sh
./build-windows.sh
