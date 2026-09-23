"""Access controller management APIs."""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from frigate.access_controller_service import (
    poll_all_controllers,
    probe_device,
    probe_device_with_info,
)
from frigate.api.auth import require_role
from frigate.api.defs.request.access_controller_body import (
    AccessCardOwnerBody,
    AccessControllerBody,
    AccessControllerUpdateBody,
)
from frigate.api.defs.tags import Tags
from frigate.const import FACE_DIR
from frigate.models import AccessCardOwner, AccessControl, AccessEvent

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


def _default_device_info(device: AccessControl) -> dict[str, str | int | float | None]:
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
        "seconds_before": device.seconds_before,
        "seconds_after": device.seconds_after,
        "last_checked_at": device.last_checked_at,
    }


def _serialize_access_controller(device: AccessControl) -> dict:
    return _default_device_info(device)


@router.get(
    "/access-controllers",
    dependencies=[Depends(require_role(["admin"]))],
)
def get_access_controllers():
    """List saved access controllers and their latest connection results."""
    _ensure_access_control_table()
    devices = AccessControl.select().order_by(AccessControl.name, AccessControl.id)
    return JSONResponse(
        content=[_serialize_access_controller(device) for device in devices]
    )


@router.post(
    "/access-controllers",
    dependencies=[Depends(require_role(["admin"]))],
)
def create_access_controller(body: AccessControllerBody):
    """Save a Dahua controller and try its connection."""
    _ensure_access_control_table()
    device_id = str(body.id or "").strip()
    if not device_id:
        return JSONResponse(
            content={"success": False, "message": "Device id is required"},
            status_code=400,
        )

    ip_address = str(body.ip_address or "").strip()
    if not ip_address:
        return JSONResponse(
            content={"success": False, "message": "Device IP is required"},
            status_code=400,
        )

    if AccessControl.select().where(AccessControl.id == device_id).exists():
        return JSONResponse(
            content={
                "success": False,
                "message": f"Access controller {device_id} already exists",
            },
            status_code=409,
        )

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
        seconds_before=body.seconds_before,
        seconds_after=body.seconds_after,
    )

    probe_device(device)
    return JSONResponse(content=_serialize_access_controller(device))


@router.put(
    "/access-controllers/{device_id}",
    dependencies=[Depends(require_role(["admin"]))],
)
def update_access_controller(device_id: str, body: AccessControllerUpdateBody):
    """Update a controller and refresh its connection result."""
    _ensure_access_control_table()
    device = AccessControl.get_or_none(AccessControl.id == device_id)
    if device is None:
        return JSONResponse(
            content={
                "success": False,
                "message": f"Access controller {device_id} not found",
            },
            status_code=404,
        )

    if body.ip_address is not None:
        device.ip_address = str(body.ip_address).strip()
    if body.port is not None:
        device.port = int(body.port or device.port or 80)
    if body.clear_credentials:
        device.username = ""
        device.password = ""
    elif body.username is not None:
        device.username = str(body.username or "")
    if body.password is not None and not body.clear_credentials:
        device.password = str(body.password or "")
    if body.name is not None:
        device.name = str(body.name or device.id)
    if "associated_camera" in body.model_fields_set:
        device.associated_camera = body.associated_camera
    if body.seconds_before is not None:
        device.seconds_before = body.seconds_before
    if body.seconds_after is not None:
        device.seconds_after = body.seconds_after

    device.save()
    probe_device(device)
    return JSONResponse(content=_serialize_access_controller(device))


@router.delete(
    "/access-controllers/{device_id}",
    dependencies=[Depends(require_role(["admin"]))],
)
def delete_access_controller(device_id: str):
    """Delete a controller and its card-owner mappings."""
    _ensure_access_control_table()
    deleted = AccessControl.delete().where(AccessControl.id == device_id).execute()
    if deleted == 0:
        return JSONResponse(
            content={
                "success": False,
                "message": f"Access controller {device_id} not found",
            },
            status_code=404,
        )
    AccessCardOwner.delete().where(AccessCardOwner.device_id == device_id).execute()
    return JSONResponse(
        content={"success": True, "message": "Successfully deleted access controller"}
    )


@router.post(
    "/access-controllers/refresh-all",
    dependencies=[Depends(require_role(["admin"]))],
)
async def refresh_all_access_controllers():
    """Try all configured controllers and return each connection result."""
    devices = await poll_all_controllers()
    return JSONResponse(
        content=[_serialize_access_controller(device) for device in devices if device]
    )


@router.post(
    "/access-controllers/{device_id}/refresh",
    dependencies=[Depends(require_role(["admin"]))],
)
async def refresh_access_controller(device_id: str):
    """Retry one controller and return the actual connection status."""
    await asyncio.to_thread(_ensure_access_control_table)
    device = await asyncio.to_thread(
        AccessControl.get_or_none, AccessControl.id == device_id
    )
    if device is None:
        return JSONResponse(
            content={
                "success": False,
                "message": f"Access controller {device_id} not found",
            },
            status_code=404,
        )
    device = await asyncio.to_thread(probe_device, device)
    return JSONResponse(content=_serialize_access_controller(device))


@router.get("/access-controllers/events")
def get_access_controller_events(
    device_id: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    """Return stored controller records with their verification results."""
    _ensure_access_control_table()
    try:
        start_ts = (
            datetime.fromisoformat(start).timestamp() if start else time.time() - 86400
        )
        end_ts = datetime.fromisoformat(end).timestamp() if end else time.time()
    except ValueError:
        return JSONResponse(content={"message": "Invalid time range"}, status_code=400)
    query = AccessEvent.select().where(
        (AccessEvent.occurred_at >= start_ts) & (AccessEvent.occurred_at <= end_ts)
    )
    if device_id:
        query = query.where(AccessEvent.device_id == device_id)
    names = {
        device.id: device.name
        for device in AccessControl.select(AccessControl.id, AccessControl.name)
    }
    events = []
    for event in query.order_by(AccessEvent.occurred_at.desc()).limit(250):
        events.append(
            {
                **event.raw_record,
                "id": event.id,
                "device_id": event.device_id,
                "device_name": names.get(event.device_id, event.device_id),
                "timestamp": event.occurred_at,
                "card_number": event.card_number,
                "verification_status": event.verification_status,
                "people": event.people,
                "camera": event.camera,
                "clip_start": event.occurred_at - event.seconds_before,
                "clip_end": event.occurred_at + event.seconds_after,
            }
        )
    return JSONResponse(content=events)


@router.get("/access-controllers/{device_id}/events")
def get_access_controller_device_events(
    device_id: str,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
):
    """Return stored access events for one controller."""
    return get_access_controller_events(device_id=device_id, start=start, end=end)


@router.get("/access-controllers/{device_id}/live")
def access_controller_live_events(device_id: str):
    """Probe a controller and return its current system information."""
    _ensure_access_control_table()
    device = AccessControl.get_or_none(AccessControl.id == device_id)
    if device is None:
        return JSONResponse(
            content={
                "success": False,
                "message": f"Access controller {device_id} not found",
            },
            status_code=404,
        )

    device, info = probe_device_with_info(device)
    if device.status != "online":
        return JSONResponse(content={"error": device.status}, status_code=503)

    return JSONResponse(
        content={"device_id": device.id, "status": "online", "system_info": info}
    )


@router.get(
    "/access-controllers/{device_id}/cards",
    dependencies=[Depends(require_role(["admin"]))],
)
def get_access_card_owners(device_id: str):
    """List registered face names allowed to use each card."""
    if AccessControl.get_or_none(AccessControl.id == device_id) is None:
        return JSONResponse(
            content={"message": "Access controller not found"}, status_code=404
        )
    cards: dict[str, list[str]] = {}
    for owner in AccessCardOwner.select().where(AccessCardOwner.device_id == device_id):
        cards.setdefault(owner.card_number, []).append(owner.face_name)
    return JSONResponse(content=cards)


@router.put(
    "/access-controllers/{device_id}/cards",
    dependencies=[Depends(require_role(["admin"]))],
)
def save_access_card_owners(device_id: str, body: AccessCardOwnerBody):
    """Replace a card's allowed owners with registered Frigate faces."""
    if AccessControl.get_or_none(AccessControl.id == device_id) is None:
        return JSONResponse(
            content={"message": "Access controller not found"}, status_code=404
        )
    names = {name.strip() for name in body.face_names}
    card_number = body.card_number.strip()
    if not card_number:
        return JSONResponse(
            content={"message": "Card number is required"}, status_code=400
        )
    if any(
        not name
        or name.lower() in {".", "..", "train", "unknown"}
        or "/" in name
        or "\\" in name
        or not (Path(FACE_DIR) / name).is_dir()
        for name in names
    ):
        return JSONResponse(
            content={"message": "Choose registered face names"}, status_code=400
        )
    AccessCardOwner.delete().where(
        (AccessCardOwner.device_id == device_id)
        & (AccessCardOwner.card_number == card_number)
    ).execute()
    AccessCardOwner.insert_many(
        [
            {"device_id": device_id, "card_number": card_number, "face_name": name}
            for name in sorted(names)
        ]
    ).execute()
    return JSONResponse(
        content={"card_number": card_number, "face_names": sorted(names)}
    )


@router.delete(
    "/access-controllers/{device_id}/cards",
    dependencies=[Depends(require_role(["admin"]))],
)
def delete_access_card_owners(device_id: str, card_number: str = Query(min_length=1)):
    """Remove all owner mappings for one card."""
    if AccessControl.get_or_none(AccessControl.id == device_id) is None:
        return JSONResponse(
            content={"message": "Access controller not found"}, status_code=404
        )
    AccessCardOwner.delete().where(
        (AccessCardOwner.device_id == device_id)
        & (AccessCardOwner.card_number == card_number)
    ).execute()
    return JSONResponse(content={"success": True})
