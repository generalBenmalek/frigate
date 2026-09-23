"""Poll access controllers and verify card scans against Frigate events."""

import asyncio
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

from frigate.const import FACE_DIR
from frigate.dahua_adapter import DahuaAccessController
from frigate.models import (
    AccessCardOwner,
    AccessControl,
    AccessEvent,
    Event,
    Recordings,
)

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 10
HISTORY_SECONDS = 24 * 60 * 60


def build_controller(device: AccessControl) -> DahuaAccessController:
    """Create a Dahua client for a saved controller."""
    username = (device.username or "").strip()
    password = (device.password or "").strip()
    return DahuaAccessController(
        ip=device.ip_address,
        username=username,
        password=password,
        port=int(device.port or 80),
        use_auth=bool(username and password),
    )


def probe_device_with_info(device: AccessControl) -> tuple[AccessControl, dict | None]:
    """Record a connection result and return the device's raw system info."""
    try:
        info = build_controller(device).get_system_info()
        if not info:
            raise ValueError("Empty system information")
        channel_count = int(info.get("channelNumber") or device.channel_count or 1)
    except (requests.RequestException, ValueError, AttributeError, TypeError) as err:
        device.status = (
            "offline" if isinstance(err, requests.RequestException) else "error"
        )
        logger.warning("Unable to reach access controller %s: %s", device.id, err)
        fields = [AccessControl.status, AccessControl.last_checked_at]
    else:
        device.name = (
            info.get("deviceName") or info.get("name") or device.name or device.id
        )
        device.type = info.get("deviceType") or device.type or "Dahua"
        device.model = (
            info.get("deviceType") or info.get("model") or device.model or "Unknown"
        )
        device.serial_number = (
            info.get("serialNumber") or info.get("serial") or device.serial_number or ""
        )
        device.channel_count = channel_count
        device.status = "online"
        fields = [
            AccessControl.name,
            AccessControl.type,
            AccessControl.model,
            AccessControl.serial_number,
            AccessControl.channel_count,
            AccessControl.status,
            AccessControl.last_checked_at,
        ]
    device.last_checked_at = time.time()
    device.save(only=fields)
    return device, info if device.status == "online" else None


def probe_device(device: AccessControl) -> AccessControl:
    """Record a fresh connection result, including failed attempts."""
    return probe_device_with_info(device)[0]


def _record_time(row: dict) -> float | None:
    value = (
        row.get("Time")
        or row.get("time")
        or row.get("datetime")
        or row.get("timestamp")
    )
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        # Dahua timestamps are local wall time, matching the server timezone.
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        logger.warning("Ignoring access record with invalid timestamp")
        return None


def _timestamp(value: datetime | float | None) -> float | None:
    if value is None:
        return None
    return value.timestamp() if isinstance(value, datetime) else float(value)


def _detected_names(person: dict) -> set[str]:
    return {name.strip() for name in str(person["name"]).split(",")}


def _store_record(device: AccessControl, row: dict) -> None:
    occurred_at = _record_time(row)
    if occurred_at is None:
        return
    card_number = str(row.get("CardNo") or row.get("card_number") or "").strip()
    fingerprint = hashlib.sha256(
        f"{device.id}:{json.dumps(row, sort_keys=True, default=str)}".encode()
    ).hexdigest()
    is_new_scan = bool(card_number) and occurred_at >= device.event_tracking_started_at
    AccessEvent.insert(
        id=fingerprint,
        device_id=device.id,
        occurred_at=occurred_at,
        card_number=card_number or None,
        raw_record=row,
        verification_status="pending" if is_new_scan else "unverified",
        people=[],
        camera=device.associated_camera,
        seconds_before=device.seconds_before,
        seconds_after=device.seconds_after,
    ).on_conflict_ignore().execute()


def poll_controller(device_id: str) -> AccessControl | None:
    """Check one device and ingest new records without repeating old scans."""
    device = AccessControl.get_or_none(AccessControl.id == device_id)
    if device is None:
        return None
    if device.event_tracking_started_at is None:
        device.event_tracking_started_at = int(time.time())
        device.save(only=[AccessControl.event_tracking_started_at])
    probe_device(device)
    if device.status != "online":
        return device
    poll_end = time.time()
    poll_start = device.last_event_poll or poll_end - HISTORY_SECONDS
    try:
        rows = build_controller(device).get_access_records(
            datetime.fromtimestamp(poll_start, UTC).astimezone(),
            datetime.fromtimestamp(poll_end, UTC).astimezone(),
        )
    except (requests.RequestException, ValueError) as err:
        logger.warning("Unable to fetch access events for %s: %s", device.id, err)
        return device
    for row in rows:
        _store_record(device, row)
    device.last_event_poll = poll_end
    device.save(only=[AccessControl.last_event_poll])
    return device


def _mark_poll_error(device_id: str) -> AccessControl | None:
    device = AccessControl.get_or_none(AccessControl.id == device_id)
    if device is not None:
        device.status = "error"
        device.last_checked_at = time.time()
        device.save(only=[AccessControl.status, AccessControl.last_checked_at])
    return device


def verify_pending_events() -> None:
    """Finalize scans once their camera window and recording grace have passed."""
    now = time.time()
    pending = AccessEvent.select().where(AccessEvent.verification_status == "pending")
    for access_event in pending:
        start = access_event.occurred_at - access_event.seconds_before
        end = access_event.occurred_at + access_event.seconds_after
        if now < end + 5:
            continue

        camera = access_event.camera
        people: list[dict[str, str | float | None]] = []
        if camera:
            detections = Event.select(
                Event.id, Event.sub_label, Event.start_time, Event.end_time
            ).where(
                (Event.camera == camera)
                & (Event.label == "person")
                & (Event.false_positive == False)
                & (Event.start_time <= end)
                & ((Event.end_time >= start) | Event.end_time.is_null())
            )
            for detection in detections:
                name = detection.sub_label or "unknown"
                people.append(
                    {
                        "event_id": detection.id,
                        "name": name,
                        "start_time": _timestamp(detection.start_time),
                        "end_time": _timestamp(detection.end_time),
                    }
                )

        access_event.people = people
        owners = {
            owner.face_name
            for owner in AccessCardOwner.select(AccessCardOwner.face_name).where(
                (AccessCardOwner.device_id == access_event.device_id)
                & (AccessCardOwner.card_number == access_event.card_number)
            )
        }
        registered_owners = {
            name for name in owners if (Path(FACE_DIR) / name).is_dir()
        }
        has_recording = (
            bool(camera)
            and Recordings.select()
            .where(
                (Recordings.camera == camera)
                & (Recordings.start_time <= end)
                & (Recordings.end_time >= start)
            )
            .exists()
        )

        if not owners or registered_owners != owners or not has_recording or not people:
            access_event.verification_status = "unknown"
        elif any(not _detected_names(person).issubset(owners) for person in people):
            access_event.verification_status = "warning"
        elif any(_detected_names(person).intersection(owners) for person in people):
            access_event.verification_status = "valid"
        else:
            access_event.verification_status = "unknown"
        access_event.save()


async def poll_all_controllers() -> list[AccessControl | None]:
    """Probe every device concurrently without unbounded network requests."""

    def device_ids() -> list[str]:
        return [device.id for device in AccessControl.select(AccessControl.id)]

    ids = await asyncio.to_thread(device_ids)
    semaphore = asyncio.Semaphore(8)

    async def poll(device_id: str) -> AccessControl | None:
        async with semaphore:
            try:
                return await asyncio.to_thread(poll_controller, device_id)
            except Exception:
                logger.exception("Unable to poll access controller %s", device_id)
                return await asyncio.to_thread(_mark_poll_error, device_id)

    return await asyncio.gather(*(poll(device_id) for device_id in ids))


async def run_controller_polling() -> None:
    """Refresh controller status and process scans throughout API uptime."""
    await asyncio.sleep(POLL_INTERVAL_SECONDS)
    while True:
        try:
            await poll_all_controllers()
            await asyncio.to_thread(verify_pending_events)
        except Exception:
            logger.exception("Access controller polling failed")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
