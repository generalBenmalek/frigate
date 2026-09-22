"""Access controller management APIs."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from frigate.api.auth import require_role
from frigate.api.defs.request.access_controller_body import AccessControllerBody, AccessControllerUpdateBody
from frigate.api.defs.tags import Tags
from frigate.dahua_adapter import DahuaAccessController
from frigate.models import AccessControl

logger = logging.getLogger(__name__)

router = APIRouter(tags=[Tags.access_controller])



def _ensure_access_control_table() -> None:
    """Create the access-control table if the migration has not run yet."""
    try:
        AccessControl.select().limit(1).scalar()
    except Exception as err:
        msg = str(err).lower()
        if "no such table" not in msg and "does not exist" not in msg:
            raise

        logger.warning("Creating missing access_control table")
        AccessControl.create_table(safe=True)


def _default_device_info(device: AccessControl) -> dict[str, str | int | None]:
    return {
        "id": device.id,
        "name": device.name or device.id,
        "ip_address": device.ip_address,
        "port": int(device.port or 80),
        "type": device.type or "Dahua",
        "model": device.model or "Unknown",
        "channel_count": int(device.channel_count or 1),
        "serial_number": device.serial_number or "",
        "status": device.status or "offline",
        "associated_camera": device.associated_camera,
    }


def _serialize_access_controller(
    device: AccessControl, include_credentials: bool = False
) -> dict:
    payload = _default_device_info(device)
    if include_credentials:
        payload["username"] = device.username or ""
        payload["password"] = device.password or ""
    return payload


def _build_controller(device: AccessControl) -> DahuaAccessController:
    username = (device.username or "").strip()
    password = (device.password or "").strip()

    return DahuaAccessController(
        ip=device.ip_address,
        username=username,
        password=password,
        port=int(device.port or 80),
        use_auth=bool(username and password),
    )


def _probe_device(device: AccessControl) -> AccessControl:
    controller = _build_controller(device)

    try:
        info = controller.get_system_info()
    except Exception as e:
        device.status = "offline"
        device.save()
        logger.warning(f"Unable to reach access controller %s {e}", device.id)
        return device

    device.name = info.get("deviceName") or info.get("name") or device.name or device.id
    device.type = info.get("deviceType") or device.type or "Dahua"
    device.model = info.get("deviceType") or info.get("model") or device.model or "Unknown"
    device.serial_number = info.get("serialNumber") or info.get("serial") or device.serial_number or ""
    device.channel_count = int(info.get("channelNumber") or device.channel_count or 1)
    device.status = "online"
    device.save()
    return device


@router.get(
    "/access-controllers",
    dependencies=[Depends(require_role(["admin"]))],
)
def get_access_controllers():
    _ensure_access_control_table()
    devices = AccessControl.select().order_by(AccessControl.name, AccessControl.id)
    return JSONResponse(content=[_serialize_access_controller(device) for device in devices])


@router.post(
    "/access-controllers",
    dependencies=[Depends(require_role(["admin"]))],
)
def create_access_controller(body: AccessControllerBody):
    _ensure_access_control_table()
    device_id = str(body.id or "").strip()
    if not device_id:
        return JSONResponse(content={"success": False, "message": "Device id is required"}, status_code=400)

    ip_address = str(body.ip_address or "").strip()
    if not ip_address:
        return JSONResponse(content={"success": False, "message": "Device IP is required"}, status_code=400)

    if AccessControl.select().where(AccessControl.id == device_id).exists():
        return JSONResponse(content={"success": False, "message": f"Access controller {device_id} already exists"}, status_code=409)

    device = AccessControl.create(
        id=device_id,
        name=str(body.name or device_id),
        ip_address=ip_address,
        type="Dahua",
        model="Unknown",
        port=int(body.port or 80),
        channel_count=1,
        serial_number="",
        username=str(body.username or ""),
        password=str(body.password or ""),
        status="offline",
        associated_camera=body.associated_camera,
    )

    _probe_device(device)
    return JSONResponse(content=_serialize_access_controller(device, include_credentials=True))


@router.put(
    "/access-controllers/{device_id}",
    dependencies=[Depends(require_role(["admin"]))],
)
def update_access_controller(device_id: str, body: AccessControllerUpdateBody):
    _ensure_access_control_table()
    device = AccessControl.get_or_none(AccessControl.id == device_id)
    if device is None:
        return JSONResponse(content={"success": False, "message": f"Access controller {device_id} not found"}, status_code=404)

    if body.ip_address is not None:
        device.ip_address = str(body.ip_address).strip()
    if body.port is not None:
        device.port = int(body.port or device.port or 80)
    if body.username is not None:
        device.username = str(body.username or "")
    if body.password is not None:
        device.password = str(body.password or "")
    if body.name is not None:
        device.name = str(body.name or device.id)
    if body.associated_camera is not None:
        device.associated_camera = body.associated_camera

    device.save()
    _probe_device(device)
    return JSONResponse(content=_serialize_access_controller(device, include_credentials=True))


@router.delete(
    "/access-controllers/{device_id}",
    dependencies=[Depends(require_role(["admin"]))],
)
def delete_access_controller(device_id: str):
    _ensure_access_control_table()
    deleted = AccessControl.delete().where(AccessControl.id == device_id).execute()
    if deleted == 0:
        return JSONResponse(content={"success": False, "message": f"Access controller {device_id} not found"}, status_code=404)
    return JSONResponse(content={"success": True, "message": "Successfully deleted access controller"})


@router.post(
    "/access-controllers/{device_id}/refresh",
    dependencies=[Depends(require_role(["admin"]))],
)
def refresh_access_controller(device_id: str):
    _ensure_access_control_table()
    device = AccessControl.get_or_none(AccessControl.id == device_id)
    if device is None:
        return JSONResponse(content={"success": False, "message": f"Access controller {device_id} not found"}, status_code=404)
    _probe_device(device)
    return JSONResponse(content=_serialize_access_controller(device, include_credentials=True))


@router.get("/access-controllers/events")
def get_access_controller_events(
    device_id: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    _ensure_access_control_table()
    start_time = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else datetime.utcnow() - timedelta(hours=24)
    end_time = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else datetime.utcnow()

    if device_id:
        devices = AccessControl.select().where(AccessControl.id == device_id)
    else:
        devices = AccessControl.select().order_by(AccessControl.name, AccessControl.id)

    events: list[dict] = []
    for device in devices:
        if device.status != "online":
            continue
        controller = _build_controller(device)
        try:
            rows = controller.get_access_records(start_time, end_time)
        except Exception:
            logger.warning("Unable to fetch access events for %s", device.id)
            continue

        for row in rows:
            row["device_id"] = device.id
            row["device_name"] = device.name or device.id
            events.append(row)

    events.sort(key=lambda item: str(item.get("Time") or item.get("timestamp") or ""), reverse=True)
    return JSONResponse(content=events[:250])


@router.get("/access-controllers/{device_id}/events")
def get_access_controller_device_events(
    device_id: str,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    return get_access_controller_events(device_id=device_id, start=start, end=end)


@router.get("/access-controllers/{device_id}/live")
def access_controller_live_events(device_id: str):
    _ensure_access_control_table()
    device = AccessControl.get_or_none(AccessControl.id == device_id)
    if device is None:
        return JSONResponse(content={"success": False, "message": f"Access controller {device_id} not found"}, status_code=404)

    controller = _build_controller(device)
    if device.status != "online":
        _probe_device(device)

    try:
        payload = controller.get_system_info()
    except Exception:
        return JSONResponse(content={"error": "offline"}, status_code=503)

    return JSONResponse(content={"device_id": device.id, "status": "online", "system_info": payload})
