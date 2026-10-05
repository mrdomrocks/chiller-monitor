"""Site storage and a live read of the demo chiller."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.monitor import Monitor
from app.simulator import stage_loads
from app.store import _load, _save, create_site, ensure_demo, get_site, update_point, update_site


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CHILLER_DATA", str(tmp_path))


def test_create_site_strips_password_and_rejects_bad_area():
    site = create_site("Roof chiller")
    assert site["vpn_password"] == ""
    assert any(point["id"] == "chw_supply" for point in site["points"])
    assert all(point["id"] != "cond_pump" for point in site["points"])
    assert "cond_pump" not in site["bindings"]
    count = next(point for point in site["points"] if point["id"] == "compressor_count")
    assert count["writable"] is False
    assert site["bindings"]["comp_2_load"] == "comp_2_load"
    assert site["bindings"]["chiller_name"] == "chiller_name"
    assert site["bindings"]["comp_6_run"] == "comp_6_run"
    with pytest.raises(ValueError):
        update_point(site["id"], "chw_supply", {**get_site(site["id"])["points"][0], "function": "coil", "address_number": 40001})


def test_rtu_over_tcp_protocol_is_saved_with_the_site():
    site = create_site("Tunnel")
    assert site["protocol"] == "tcp"
    assert site["inter_frame_ms"] == 0
    saved = update_site(site["id"], {"name": site["name"], "protocol": "rtu", "inter_frame_ms": 20})
    assert saved["protocol"] == "rtu"
    assert saved["inter_frame_ms"] == 20
    assert get_site(site["id"])["protocol"] == "rtu"
    with pytest.raises(ValueError):
        update_site(site["id"], {"name": site["name"], "protocol": "ascii"})


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


def test_display_layout_is_saved_with_the_site():
    from app.store import public_site, update_hmi

    site = create_site("Layout")
    assert site["layout"]["table"] is True
    assert site["layout"]["profile"] is True
    assert site["layout"]["compressors"] is True
    saved = update_hmi(site["id"], {"layout": {"table": False}})
    assert saved["layout"]["table"] is False
    assert saved["layout"]["mimic"] is True
    stored = get_site(site["id"])
    assert stored["layout"]["table"] is False
    cleaned = update_hmi(site["id"], {"layout": {"table": False, "extra": True}})
    assert "extra" not in cleaned["layout"]
    assert cleaned["layout"]["table"] is False

    data = _load()
    found = next(item for item in data["sites"] if item["id"] == site["id"])
    del found["layout"]
    _save(data)
    published = public_site(get_site(site["id"]))
    assert published["layout"]["status"] is True
    assert published["layout"]["outputs"] is True


def test_stage_loads_follows_fitted_count():
    two = stage_loads(2, 60, True)
    assert two[0] == (100.0, True)
    assert two[1] == (20.0, True)
    assert two[2:] == [(0.0, False)] * 4
    six = stage_loads(6, 60, True)
    assert six[2] == (100.0, True)
    assert six[3] == (60.0, True)
    assert six[5] == (0.0, False)
    assert stage_loads(1, 40, True)[0] == (40.0, True)
    assert stage_loads(1, 40, True)[1:] == [(0.0, False)] * 5
    assert stage_loads(4, 80, False) == [(0.0, False)] * 6


def test_existing_demo_gains_compressor_points():
    ensure_demo(1502)
    data = _load()
    found = next(site for site in data["sites"] if site["id"] == "demo")
    found["points"] = [point for point in found["points"] if not str(point["id"]).startswith("comp_")]
    found["bindings"] = {"supply_temp": "chw_supply"}
    _save(data)
    site = ensure_demo(1502)
    assert any(point["id"] == "comp_6_load" for point in site["points"])
    assert site["bindings"]["supply_temp"] == "chw_supply"
    assert site["bindings"]["comp_4_load"] == "comp_4_load"
    count = next(point for point in site["points"] if point["id"] == "compressor_count")
    assert count["writable"] is True
    assert count["write_min"] == 1
    assert count["write_max"] == 6


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

        count = monitor.snapshot()["values"].get("compressor_count")
        third = monitor.snapshot()["values"].get("comp_3_load")
        assert count["quality"] == "good"
        assert count["value"] == 2
        assert third["quality"] == "good"
        assert third["value"] == 0
        assert monitor.snapshot()["values"]["comp_1_load"]["value"] > 0

        await monitor.write("compressor_count", 6)
        widened = None
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            widened = monitor.snapshot()["values"]
            reported = widened.get("compressor_count")
            third = widened.get("comp_3_load")
            if reported and reported["value"] == 6 and third and third["value"] > 0:
                break
        assert widened["compressor_count"]["value"] == 6
        assert widened["comp_1_load"]["value"] > 0
        assert widened["comp_3_load"]["value"] > 0
        assert "comp_6_load" in widened

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


def test_sized_demos_report_fitted_compressors():
    asyncio.run(sized_demo_session())


async def sized_demo_session():
    monitor = Monitor()
    try:
        for count in (1, 2, 4, 6):
            started = await monitor.start_sized_demo(count)
            assert started["site_id"] == f"demo-{count}"
            assert started["simulator_running"] is True
            site = get_site(f"demo-{count}")
            fitted = next(point for point in site["points"] if point["id"] == "compressor_count")
            assert fitted["writable"] is False
            values = None
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                await asyncio.sleep(0.1)
                values = monitor.snapshot()["values"]
                reported = values.get("compressor_count")
                first = values.get("comp_1_load")
                if reported and reported["value"] == count and first and first["quality"] == "good" and first["value"] > 0:
                    break
            assert values["compressor_count"]["quality"] == "good"
            assert values["compressor_count"]["value"] == count
            assert values["comp_1_load"]["value"] > 0
            assert values["comp_1_run"]["value"] is True
            if count < 6:
                idle = values[f"comp_{count + 1}_load"]
                assert idle["quality"] == "good"
                assert idle["value"] == 0
                assert values[f"comp_{count + 1}_run"]["value"] is False
            name = values.get("chiller_name")
            assert name["quality"] == "good"
            expected = "1 compressor" if count == 1 else f"{count} compressors"
            assert name["value"] == expected

        with pytest.raises(ValueError):
            await monitor.start_sized_demo(3)

        classic = await monitor.start_demo()
        assert classic["site_id"] == "demo"
        count_point = next(point for point in get_site("demo")["points"] if point["id"] == "compressor_count")
        assert count_point["writable"] is True
        sized = next(point for point in get_site("demo-4")["points"] if point["id"] == "compressor_count")
        assert sized["writable"] is False
    finally:
        await monitor.shutdown()


def test_sized_demo_http_rejects_other_counts():
    from app.main import app

    with TestClient(app) as client:
        started = client.post("/api/demo/compressors/4")
        assert started.status_code == 200, started.text
        assert started.json()["site_id"] == "demo-4"
        reported = None
        for _ in range(40):
            time.sleep(0.1)
            live = client.get("/api/live").json()
            reported = live["values"].get("compressor_count")
            if reported and reported["quality"] == "good" and reported["value"] == 4:
                break
        assert reported["value"] == 4
        assert live["demo"] is True
        rejected = client.post("/api/demo/compressors/3")
        assert rejected.status_code == 400
        stopped = client.post("/api/demo/stop")
        assert stopped.status_code == 200
        assert stopped.json()["simulator_running"] is False


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
