"""Choosing a GitHub release without contacting the network."""

from fastapi.testclient import TestClient

import app.update as update
from app.main import app
from app.update import allowed_download, choose_asset, maybe_apply_update, newer_release, updates_enabled


def test_development_copy_does_not_offer_an_update():
    with TestClient(app) as client:
        body = client.get("/api/update").json()
    assert body["available"] is False


def test_update_is_offered_only_for_a_different_build():
    current = "a" * 40
    assert newer_release(current, "b" * 40) is True
    assert newer_release(current, current) is False
    assert newer_release("", "b" * 40) is True
    assert newer_release("dev", "b" * 40) is True
    assert newer_release(current, "latest") is False


def test_installed_copy_checks_without_a_recorded_revision(monkeypatch):
    monkeypatch.setenv("CHILLER_INSTALLED", "1")
    monkeypatch.setattr(update, "local_revision", lambda: "")
    assert updates_enabled() is True


def test_launch_installs_a_newer_release_once(monkeypatch, tmp_path):
    monkeypatch.setenv("CHILLER_INSTALLED", "1")
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))
    monkeypatch.delenv("CHILLER_UPDATE", raising=False)
    latest = "c" * 40
    calls = []

    def describe(timeout=20):
        return {"available": True, "latest": latest, "current": "a" * 40}

    def install():
        calls.append("install")
        update.mark_attempted(latest)
        return {"ok": True}

    monkeypatch.setattr(update, "describe_update", describe)
    monkeypatch.setattr(update, "begin_install", install)
    assert maybe_apply_update() is True
    assert maybe_apply_update() is False
    assert calls == ["install"]


def test_a_cancelled_install_is_left_for_the_plant_page(monkeypatch, tmp_path):
    monkeypatch.setenv("CHILLER_INSTALLED", "1")
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))
    latest = "d" * 40
    update.mark_attempted(latest)
    calls = []
    monkeypatch.setattr(
        update,
        "describe_update",
        lambda timeout=20: {"available": True, "latest": latest, "current": ""},
    )
    monkeypatch.setattr(update, "begin_install", lambda: calls.append("install"))
    assert maybe_apply_update() is False
    assert calls == []


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
            "name": "chiller-monitor-0.1.0-linux-x86_64.tar.gz",
            "browser_download_url": "https://github.com/mrdomrocks/chiller-monitor/releases/download/abc/chiller-monitor-0.1.0-linux-x86_64.tar.gz",
        },
        {
            "name": "notes.tar.gz",
            "browser_download_url": "https://github.com/mrdomrocks/chiller-monitor/releases/download/abc/notes.tar.gz",
        },
        {
            "name": "evil.rpm",
            "browser_download_url": "https://evil.example/chiller-monitor.x86_64.rpm",
        },
    ]
    linux = choose_asset(assets, "linux")
    windows = choose_asset(assets, "windows")
    archive = choose_asset(assets, "archive")
    assert linux is not None and linux["name"].endswith(".rpm")
    assert windows is not None and windows["name"].endswith(".exe")
    assert archive is not None and archive["name"].startswith("chiller-monitor-")
    assert choose_asset([assets[3]], "archive") is None
    assert choose_asset([assets[4]], "linux") is None
    assert allowed_download("https://github.com/other/chiller-monitor/releases/download/abc/a.rpm") is False
