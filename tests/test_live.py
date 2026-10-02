"""Site storage and a live read of the demo chiller."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.monitor import Monitor
from app.store import create_site, get_site, update_point


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))


def test_create_site_strips_password_and_rejects_bad_area():
    site = create_site("Roof chiller")
    assert site["vpn_password"] == ""
    assert any(point["id"] == "chw_supply" for point in site["points"])
    with pytest.raises(ValueError):
        update_point(site["id"], "chw_supply", {**get_site(site["id"])["points"][0], "function": "coil", "address_number": 40001})


def test_http_creates_and_updates_a_point():
    from app.main import app

    with TestClient(app) as client:
        created = client.post("/api/sites", json={"name": "Lab"}).json()
        point = next(item for item in created["points"] if item["id"] == "setpoint")
        point["name"] = "CHW setpoint"
        point["write_max"] = 12
        saved = client.put(f"/api/sites/{created['id']}/points/setpoint", json=point)
        assert saved.status_code == 200
        renamed = next(item for item in saved.json()["points"] if item["id"] == "setpoint")
        assert renamed["name"] == "CHW setpoint"
        assert renamed["write_max"] == 12


def test_demo_poll_and_setpoint_write():
    asyncio.run(demo_session())


async def demo_session():
    monitor = Monitor()
    try:
        await monitor.start_demo()
        supply = None
        for _ in range(30):
            await asyncio.sleep(0.1)
            supply = monitor.snapshot()["values"].get("chw_supply")
            if supply and supply["quality"] == "good":
                break
        assert supply is not None
        assert supply["quality"] == "good"
        assert 5 < supply["value"] < 10
        assert supply["raw"][0] > 40

        site = get_site("demo")
        supply_point = next(point for point in site["points"] if point["id"] == "chw_supply")
        supply_point["scale"] = 1
        update_point("demo", "chw_supply", supply_point)
        scaled = None
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            scaled = monitor.snapshot()["values"].get("chw_supply")
            if scaled and scaled["quality"] == "good" and scaled["raw"] and scaled["raw"][0] < 20:
                break
        assert scaled["quality"] == "good"
        assert 5 < scaled["value"] < 10
        assert scaled["raw"][0] < 20

        await monitor.write("setpoint", 6.5)
        seen = None
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            seen = monitor.snapshot()["values"].get("setpoint")
            if seen and seen["quality"] == "good" and abs(seen["value"] - 6.5) < 0.05:
                break
        assert abs(seen["value"] - 6.5) < 0.05

        await monitor.write("enable", False)
        compressor = None
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            compressor = monitor.snapshot()["values"].get("compressor")
            if compressor and compressor["quality"] == "good" and compressor["value"] is False:
                break
        assert compressor["value"] is False
    finally:
        await monitor.shutdown()


def test_demo_http_and_websocket():
    from app.main import app

    with TestClient(app) as client:
        started = client.post("/api/demo/start")
        assert started.status_code == 200, started.text
        supply = None
        for _ in range(40):
            time.sleep(0.1)
            supply = client.get("/api/live").json()["values"].get("chw_supply")
            if supply and supply["quality"] == "good":
                break
        assert supply is not None and supply["quality"] == "good"
        assert 5 < supply["value"] < 10
        with client.websocket_connect("/ws") as socket:
            message = socket.receive_json()
            assert message["site_id"] == "demo"
            assert "chw_supply" in message["values"]
        stopped = client.post("/api/demo/stop")
        assert stopped.status_code == 200
        assert stopped.json()["simulator_running"] is False
