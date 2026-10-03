"""Native window for the installed plant page."""

from __future__ import annotations

import socket
import threading
import time

import uvicorn

from app.main import app

URL = "http://127.0.0.1:8765"


def run_window(*, start_server: bool) -> None:
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.1")
        from gi.repository import GLib, Gtk, WebKit2
    except (ImportError, ValueError) as exc:
        raise SystemExit(
            "Chiller Monitor needs GTK and WebKit for its window. "
            "Install python3-gobject, gtk3, and webkit2gtk4.1."
        ) from exc

    server = None
    thread = None
    if start_server:
        config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="info")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, name="chiller-monitor")
        thread.start()
        if not _wait_until_up():
            server.should_exit = True
            thread.join(timeout=3)
            raise SystemExit(f"Chiller Monitor did not start on {URL}")

    GLib.set_prgname("chiller-monitor")
    GLib.set_application_name("Chiller Monitor")
    window = Gtk.Window(title="Chiller Monitor")
    window.set_default_size(1360, 860)
    window.set_position(Gtk.WindowPosition.CENTER)
    view = WebKit2.WebView()
    view.get_settings().set_enable_javascript(True)
    view.load_uri(URL)
    window.add(view)

    def close_window(_widget: Gtk.Window) -> None:
        if server is not None:
            server.should_exit = True
        Gtk.main_quit()

    window.connect("destroy", close_window)
    window.show_all()
    Gtk.main()
    if thread is not None:
        thread.join(timeout=3)


def port_open() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", 8765)) == 0


def _wait_until_up(timeout: float = 15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open():
            return True
        time.sleep(0.05)
    return False
