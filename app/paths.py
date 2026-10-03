"""Filesystem locations. Data stays on this PC and is not committed."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    override = os.environ.get("CHILLER_DATA")
    if override:
        return Path(override)
    if os.environ.get("CHILLER_INSTALLED") == "1":
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
            return base / "ChillerMonitor"
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
        return base / "chiller-monitor"
    return ROOT / "data"


def vpn_dir() -> Path:
    return data_dir() / "vpn"
