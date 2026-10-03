"""Native window for the installed plant page."""

from __future__ import annotations

import socket
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path

import uvicorn

from app.main import app
from app.paths import ROOT

URL = "http://127.0.0.1:8765"


def run_window(*, start_server: bool) -> None:
    server = None
    thread = None
    if start_server:
        config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning")
        server = uvicorn.Server(config)
        # Signal handlers can only be installed on the main thread, which is the window.
        server.capture_signals = lambda: nullcontext()
        thread = threading.Thread(target=server.run, name="chiller-monitor", daemon=True)
        thread.start()
        if not _wait_until_up():
            server.should_exit = True
            thread.join(timeout=3)
            _tell("Chiller Monitor did not start.")
            raise SystemExit(1)
    try:
        if sys.platform == "win32":
            _run_windows()
        else:
            _run_gtk()
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=3)


def icon_file(suffix: str) -> str | None:
    candidates = [
        ROOT / f"chiller-monitor{suffix}",
        ROOT / "packaging" / "icons" / f"chiller-monitor{suffix}",
    ]
    if suffix == ".png":
        candidates.append(Path("/usr/share/icons/hicolor/256x256/apps/chiller-monitor.png"))
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def _run_gtk() -> None:
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.1")
        from gi.repository import GLib, Gtk, WebKit2
    except (ImportError, ValueError) as exc:
        _tell(
            "Chiller Monitor needs GTK and WebKit for its window. "
            "Install python3-gobject, gtk3, and webkit2gtk4.1."
        )
        raise SystemExit(1) from exc

    GLib.set_prgname("chiller-monitor")
    GLib.set_application_name("Chiller Monitor")
    window = Gtk.Window(title="Chiller Monitor")
    window.set_default_size(1360, 860)
    window.set_position(Gtk.WindowPosition.CENTER)
    icon = icon_file(".png")
    if icon:
        window.set_icon_from_file(icon)
    view = WebKit2.WebView()
    view.get_settings().set_enable_javascript(True)
    view.load_uri(URL)
    window.add(view)
    window.connect("destroy", lambda _widget: Gtk.main_quit())
    window.show_all()
    Gtk.main()


def _run_windows() -> None:
    if not _webview2_installed():
        _tell(
            "Chiller Monitor needs the Microsoft Edge WebView2 Runtime. "
            "Windows 11 and current Windows 10 include it with Edge.\n\n"
            "Install it from https://developer.microsoft.com/microsoft-edge/webview2/ "
            "and start Chiller Monitor again."
        )
        raise SystemExit(1)
    try:
        import webview
    except ImportError as exc:
        _tell("Chiller Monitor could not load its window. Reinstall the program.")
        raise SystemExit(1) from exc
    webview.create_window("Chiller Monitor", URL, width=1360, height=860, text_select=True)
    try:
        webview.start(icon=icon_file(".ico"))
    except Exception as exc:
        _tell(f"Chiller Monitor could not open its window.\n\n{exc}")
        raise SystemExit(1) from exc


def _webview2_installed() -> bool:
    import winreg

    guids = (
        "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",
        "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}",
        "{65C35B14-6C1D-4122-AC46-7148CC9D6497}",
    )
    roots = (
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
    )
    for guid in guids:
        for hive, pattern in roots:
            try:
                with winreg.OpenKey(hive, pattern.format(guid=guid)) as key:
                    build, _ = winreg.QueryValueEx(key, "pv")
            except OSError:
                continue
            if build and not str(build).startswith("0"):
                return True
    return False


def _tell(text: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, "Chiller Monitor", 0x10)
        return
    print(text, file=sys.stderr)


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
