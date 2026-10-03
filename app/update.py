"""Check GitHub for a newer installed build and replace this one."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.paths import data_dir, revision_file

REPO = "mrdomrocks/chiller-monitor"
RELEASES = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
_MAX_BYTES = 80 * 1024 * 1024
_last: dict | None = None


def local_revision() -> str:
    path = revision_file()
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def updates_enabled() -> bool:
    revision = local_revision()
    return os.environ.get("CHILLER_INSTALLED") == "1" and len(revision) == 40 and all(
        ch in "0123456789abcdef" for ch in revision
    )


def newer_release(current: str, latest: str) -> bool:
    current = current.strip().lower()
    latest = latest.strip().lower()
    if len(current) != 40 or len(latest) < 7:
        return False
    return current != latest


def allowed_download(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.path.startswith(DOWNLOAD_PREFIX.removeprefix("https://github.com"))
    )


def choose_asset(assets: list[dict], kind: str) -> dict | None:
    suffix = ".exe" if kind == "windows" else ".rpm" if kind == "linux" else ""
    if not suffix:
        return None
    for asset in assets:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        if name.endswith(suffix) and allowed_download(url):
            return {"name": name, "url": url}
    return None


def package_kind() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return ""


def _fetch_release() -> dict:
    request = urllib.request.Request(
        RELEASES,
        headers={
            "User-Agent": "chiller-monitor",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub did not return a release")
    return payload


def describe_update() -> dict:
    current = local_revision()
    if not updates_enabled():
        return {"available": False, "current": current, "latest": "", "detail": ""}
    try:
        release = _fetch_release()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        return {"available": False, "current": current, "latest": "", "detail": str(exc)}
    latest = str(release.get("tag_name") or "")
    asset = choose_asset(list(release.get("assets") or []), package_kind())
    available = newer_release(current, latest) and asset is not None
    global _last
    _last = {
        "available": available,
        "current": current,
        "latest": latest,
        "detail": str(release.get("name") or latest),
        "asset": asset,
    }
    return {"available": available, "current": current, "latest": latest, "detail": _last["detail"]}


def _download(url: str, dest: Path) -> None:
    if not allowed_download(url):
        raise ValueError("Refusing an update that is not from this project's GitHub releases")
    request = urllib.request.Request(url, headers={"User-Agent": "chiller-monitor"})
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(dest.suffix + ".part")
    size = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temp.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_BYTES:
                    raise ValueError("The update is larger than expected")
                handle.write(chunk)
        temp.replace(dest)
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _spawn(command: list[str], script: Path) -> None:
    kwargs: dict = {
        "cwd": str(script.parent),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


def _arm_linux(package: Path) -> None:
    folder = package.parent
    log = folder / "install.log"
    waiter = folder / "port-free.py"
    waiter.write_text(
        "import socket, sys\n"
        "sock = socket.socket()\n"
        "sock.settimeout(0.2)\n"
        "sys.exit(0 if sock.connect_ex(('127.0.0.1', 8765)) else 1)\n",
        encoding="utf-8",
    )
    script = folder / "install-update.sh"
    script.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                "set -u",
                f"pkg={_shell(package)}",
                f"log={_shell(log)}",
                f"waiter={_shell(waiter)}",
                "for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do",
                "  if python3 \"$waiter\"; then",
                "    break",
                "  fi",
                "  sleep 0.5",
                "done",
                "if command -v pkexec >/dev/null 2>&1; then",
                "  pkexec dnf -y install \"$pkg\" >\"$log\" 2>&1 || true",
                "else",
                "  echo \"pkexec is not available\" >\"$log\"",
                "fi",
                "exec /usr/bin/chiller-monitor",
                "",
            ]
        ),
        encoding="utf-8",
    )
    script.chmod(0o700)
    _spawn(["/bin/sh", str(script)], script)


def _arm_windows(package: Path) -> None:
    folder = package.parent
    app = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Programs" / "ChillerMonitor"
    script = folder / "install-update.bat"
    script.write_text(
        "\r\n".join(
            [
                "@echo off",
                f'set "SETUP={package}"',
                f'set "APP={app}"',
                "set /a TRIES=0",
                ":wait",
                "set /a TRIES+=1",
                "if %TRIES% GTR 40 goto install",
                "ping -n 2 127.0.0.1 >nul",
                'netstat -an | find "127.0.0.1:8765" | find "LISTENING" >nul',
                "if %ERRORLEVEL%==0 goto wait",
                ":install",
                '"%SETUP%" /S',
                'start "" "%APP%\\python\\pythonw.exe" "%APP%\\chiller-monitor.pyw"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    _spawn(["cmd", "/c", str(script)], script)


def _shell(path: Path) -> str:
    return "'" + str(path).replace("'", "'\"'\"'") + "'"


def begin_install() -> dict:
    info = _last if _last and _last.get("available") else describe_update()
    if not info.get("available"):
        raise RuntimeError(info.get("detail") or "Chiller Monitor is already up to date")
    asset = info.get("asset") or (_last or {}).get("asset")
    if not asset:
        raise RuntimeError("The GitHub release has no installer for this computer")
    folder = data_dir() / "updates"
    dest = folder / Path(str(asset["name"])).name
    _download(str(asset["url"]), dest)
    if package_kind() == "linux":
        _arm_linux(dest)
    elif package_kind() == "windows":
        _arm_windows(dest)
    else:
        raise RuntimeError("Updates are available for Windows and Linux installs")
    return {
        "ok": True,
        "detail": "Chiller Monitor will close, install the update, and reopen. On Linux, approve the password prompt.",
    }


def schedule_exit() -> None:
    loop = asyncio.get_running_loop()
    loop.call_later(1.0, lambda: os._exit(0))
