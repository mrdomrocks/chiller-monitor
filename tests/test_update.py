"""Choosing a GitHub release without contacting the network."""

from fastapi.testclient import TestClient

from app.main import app
from app.update import allowed_download, choose_asset, newer_release


def test_development_copy_does_not_offer_an_update():
    with TestClient(app) as client:
        body = client.get("/api/update").json()
    assert body["available"] is False


def test_update_is_offered_only_for_a_different_build():
    current = "a" * 40
    assert newer_release(current, "b" * 40) is True
    assert newer_release(current, current) is False
    assert newer_release("", "b" * 40) is False
    assert newer_release("dev", "b" * 40) is False


def test_installer_must_come_from_this_repository():
    assets = [
        {
            "name": "chiller-monitor.x86_64.rpm",
            "browser_download_url": "https://github.com/mrdomrocks/chiller-monitor/releases/download/abc/chiller-monitor.x86_64.rpm",
        },
        {
            "name": "ChillerMonitor-Setup.exe",
            "browser_download_url": "https://github.com/mrdomrocks/chiller-monitor/releases/download/abc/ChillerMonitor-Setup.exe",
        },
        {
            "name": "evil.rpm",
            "browser_download_url": "https://evil.example/chiller-monitor.x86_64.rpm",
        },
    ]
    linux = choose_asset(assets, "linux")
    windows = choose_asset(assets, "windows")
    assert linux is not None and linux["name"].endswith(".rpm")
    assert windows is not None and windows["name"].endswith(".exe")
    assert choose_asset([assets[2]], "linux") is None
    assert allowed_download("https://github.com/other/chiller-monitor/releases/download/abc/a.rpm") is False
