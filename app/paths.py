"""Filesystem locations. Data stays on this PC and is not committed."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    override = os.environ.get("CHILLER_DATA")
    return Path(override) if override else ROOT / "data"


def vpn_dir() -> Path:
    return data_dir() / "vpn"
