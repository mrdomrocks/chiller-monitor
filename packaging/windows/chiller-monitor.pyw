"""Windows entry point. pythonw runs this with no console."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
os.environ.setdefault("CHILLER_INSTALLED", "1")
os.environ.setdefault("CHILLER_WINDOW", "1")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONNOUSERSITE", "1")

if sys.platform == "win32":
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ChillerMonitor.Desktop")

from app.__main__ import main

if __name__ == "__main__":
    main()
