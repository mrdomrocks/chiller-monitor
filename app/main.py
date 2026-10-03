"""HTTP API and the plant page."""

from __future__ import annotations

import asyncio
import logging
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.decode import engineering_from_raw, format_value
from app.monitor import Monitor, probe_site
from app.paths import ROOT
from app.store import (
    add_point,
    apply_template,
    clear_vpn_config,
    create_site,
    delete_point,
    delete_site,
    export_map,
    get_site,
    list_sites,
    move_point,
    public_site,
    replace_map,
    save_vpn_config,
    update_hmi,
    update_point,
    update_site,
    normalize_point,
)
from app.template import ROLES
from app.update import begin_install, describe_update, schedule_exit

log = logging.getLogger("chiller")
monitor = Monitor()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await monitor.shutdown()


app = FastAPI(title="RUT Chiller Monitor", version=__version__, lifespan=lifespan)


class _Static(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", _Static(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/update")
async def read_update():
    return await asyncio.to_thread(describe_update)


@app.post("/api/update/install")
async def install_update():
    try:
        result = await asyncio.to_thread(begin_install)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    schedule_exit()
    return result


@app.get("/api/meta")
def meta():
    return {
        "version": __version__,
        "roles": ROLES,
        "tools": {
            "wireguard": shutil.which("wg-quick") is not None,
            "openvpn": shutil.which("openvpn") is not None,
        },
    }


@app.get("/api/sites")
def sites():
    return list_sites()


@app.post("/api/sites")
def post_site(body: dict):
    try:
        return create_site(str(body.get("name", "")))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/sites/{site_id}")
def read_site(site_id: str):
    try:
        return public_site(get_site(site_id))
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc


@app.put("/api/sites/{site_id}")
def put_site(site_id: str, body: dict):
    try:
        return update_site(site_id, body)
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/sites/{site_id}")
def remove_site(site_id: str):
    try:
        delete_site(site_id)
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc
    return {"ok": True}


@app.post("/api/sites/{site_id}/vpn-config")
async def upload_vpn(site_id: str, file: UploadFile = File(...)):
    blob = await file.read()
    if len(blob) > 1_000_000:
        raise HTTPException(400, "VPN profile is larger than 1 MB")
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "VPN profile must be a text file") from exc
    try:
        return save_vpn_config(site_id, file.filename or "client.conf", text)
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/sites/{site_id}/vpn-config")
def remove_vpn(site_id: str):
    try:
        return clear_vpn_config(site_id)
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc


@app.post("/api/sites/{site_id}/points")
def post_point(site_id: str):
    try:
        site, point_id = add_point(site_id)
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"site": site, "point_id": point_id}


@app.put("/api/sites/{site_id}/points/{point_id}")
def put_point(site_id: str, point_id: str, body: dict):
    try:
        return update_point(site_id, point_id, body)
    except KeyError as exc:
        raise HTTPException(404, "Point not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/sites/{site_id}/points/{point_id}")
def remove_point(site_id: str, point_id: str):
    try:
        return delete_point(site_id, point_id)
    except KeyError as exc:
        raise HTTPException(404, "Point not found") from exc


@app.post("/api/sites/{site_id}/points/{point_id}/move")
def reorder_point(site_id: str, point_id: str, body: dict):
    try:
        return move_point(site_id, point_id, str(body.get("direction", "")))
    except KeyError as exc:
        raise HTTPException(404, "Point not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/sites/{site_id}/hmi")
def put_hmi(site_id: str, body: dict):
    try:
        return update_hmi(site_id, body)
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sites/{site_id}/template")
def post_template(site_id: str):
    try:
        return apply_template(site_id)
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc


@app.get("/api/sites/{site_id}/export")
def get_export(site_id: str):
    try:
        return export_map(site_id)
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc


@app.post("/api/sites/{site_id}/import")
def post_import(site_id: str, body: dict):
    try:
        return replace_map(site_id, body)
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/preview")
def preview(body: dict):
    try:
        point = normalize_point(body.get("point") or {})
        registers = [int(item) for item in body.get("registers") or []]
        value = engineering_from_raw(point, registers)
        if isinstance(value, float):
            value = round(value, point["decimals"])
        return {"value": value, "display": format_value(point, value)}
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sites/{site_id}/connect")
async def connect(site_id: str):
    try:
        return await monitor.connect(site_id)
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc
    except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/sites/{site_id}/disconnect")
async def disconnect(site_id: str):
    if monitor.site_id not in (None, site_id):
        await monitor.disconnect()
    elif monitor.site_id == site_id:
        await monitor.disconnect()
    return monitor.snapshot()


@app.post("/api/sites/{site_id}/test")
async def test_link(site_id: str):
    try:
        site = get_site(site_id)
    except KeyError as exc:
        raise HTTPException(404, "Site not found") from exc
    return await probe_site(site)


@app.post("/api/sites/{site_id}/write")
async def write_output(site_id: str, body: dict):
    if monitor.site_id != site_id:
        raise HTTPException(409, "Connect to this site before writing")
    try:
        return await monitor.write(str(body.get("point_id", "")), body.get("value"))
    except KeyError as exc:
        raise HTTPException(404, "Point not found") from exc
    except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        from app.modbus_tcp import ModbusError

        if isinstance(exc, ModbusError):
            raise HTTPException(400, str(exc)) from exc
        raise


@app.post("/api/demo/start")
async def demo_start():
    try:
        return await monitor.start_demo()
    except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/demo/stop")
async def demo_stop():
    return await monitor.stop_demo()


@app.get("/api/live")
def live():
    return monitor.snapshot()


@app.websocket("/ws")
async def live_socket(socket: WebSocket):
    await socket.accept()
    queue = monitor.subscribe()
    try:
        await socket.send_json(monitor.snapshot())
        while True:
            await socket.send_json(await queue.get())
    except WebSocketDisconnect:
        pass
    finally:
        monitor.unsubscribe(queue)
