"""python -m app"""

from __future__ import annotations

import os
import socket
import threading
import webbrowser

import uvicorn

from app.main import app
from app.paths import data_dir

URL = "http://127.0.0.1:8765"


def _listening() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", 8765)) == 0


def main() -> None:
    open_browser = os.environ.get("CHILLER_OPEN_BROWSER") == "1"
    if open_browser and _listening():
        print(f"Chiller Monitor is already running at {URL}")
        webbrowser.open(URL)
        return
    if os.environ.get("CHILLER_INSTALLED") == "1":
        print(f"Site profiles: {data_dir()}")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(URL)).start()
    print(f"Chiller Monitor is at {URL}")
    print("Close this window to stop it.")
    uvicorn.run(app, host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
