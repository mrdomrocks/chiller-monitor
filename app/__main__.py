"""python -m app"""

from __future__ import annotations

import os
import threading
import webbrowser

import uvicorn

from app.main import app
from app.paths import data_dir
from app.window import URL, port_open, run_window


def main() -> None:
    window = os.environ.get("CHILLER_WINDOW") == "1"
    if window and port_open():
        run_window(start_server=False)
        return
    if os.environ.get("CHILLER_INSTALLED") == "1":
        from app.update import maybe_apply_update

        if maybe_apply_update():
            raise SystemExit(0)
    if window:
        run_window(start_server=True)
        return
    open_browser = os.environ.get("CHILLER_OPEN_BROWSER") == "1"
    if open_browser and port_open():
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
