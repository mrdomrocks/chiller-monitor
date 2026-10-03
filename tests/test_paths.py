"""Where an installed copy keeps site profiles."""

from app import paths


def test_dev_run_keeps_data_in_the_repo(monkeypatch):
    monkeypatch.delenv("CHILLER_DATA", raising=False)
    monkeypatch.delenv("CHILLER_INSTALLED", raising=False)
    assert paths.data_dir() == paths.ROOT / "data"


def test_data_override_wins_over_installed_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))
    monkeypatch.setenv("CHILLER_INSTALLED", "1")
    assert paths.data_dir() == tmp_path


def test_linux_install_uses_xdg_data(monkeypatch, tmp_path):
    monkeypatch.delenv("CHILLER_DATA", raising=False)
    monkeypatch.setenv("CHILLER_INSTALLED", "1")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(paths.sys, "platform", "linux")
    assert paths.data_dir() == tmp_path / "chiller-monitor"


def test_window_icon_is_packaged():
    from app.window import icon_file

    assert icon_file(".png")
    assert icon_file(".ico")


def test_windows_install_uses_local_app_data(monkeypatch, tmp_path):
    monkeypatch.delenv("CHILLER_DATA", raising=False)
    monkeypatch.setenv("CHILLER_INSTALLED", "1")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(paths.sys, "platform", "win32")
    assert paths.data_dir() == tmp_path / "ChillerMonitor"
