"""Ingest controller streams and history and verify scans against camera events."""

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import requests

from frigate.const import FACE_DIR
from frigate.dahua_adapter import DahuaAccessController
from frigate.models import (
    AccessControl,
    AccessEvent,
    Event,
    Recordings,
)

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 10
HISTORY_SECONDS = 24 * 60 * 60
_publisher: Callable[[str, str], None] | None = None
_stream_states: dict[str, str] = {}
_history_locks: dict[str, asyncio.Lock] = {}
_record_locks: dict[str, threading.RLock] = {}


def build_controller(
    device: AccessControl, diagnostic: Callable[[dict], None] | None = None
) -> DahuaAccessController:
    """Create a Dahua client for a saved controller."""
    username = (device.username or "").strip()
    password = (device.password or "").strip()
    return DahuaAccessController(
        ip=device.ip_address,
        username=username,
        password=password,
        port=int(device.port or 80),
        use_auth=bool(username and password),
        provider=device.provider or "cgi",
        scheme="https" if device.use_https else "http",
        sdk_port=int(device.sdk_port or 37777),
        provider_options=device.provider_options or {},
        diagnostic=diagnostic,
    )


def controller_stream_state(device_id: str) -> str:
    """Return the upstream listener's current connection state."""
    return _stream_states.get(device_id, "connecting")


def _set_stream_state(device_id: str, state: str) -> None:
    _stream_states[device_id] = state
    if _publisher is not None:
        _publisher("access_controller_status", json.dumps({"device_id": device_id, "state": state}))


def serialize_access_event(event: AccessEvent, device_name: str | None = None) -> dict:
    """Share the same event representation between history and live messages."""
    raw = DahuaAccessController.sanitize_raw_event({
        key: value for key, value in event.raw_record.items() if not key.startswith("_")
    })
    normalized = DahuaAccessController.normalize_event(raw, event.device_id)
    return {
        **raw, **normalized,
        "id": event.id, "device_id": event.device_id,
        "device_name": device_name or event.device_id,
        "timestamp": event.occurred_at, "card_number": event.card_number,
        "owner_names": event.raw_record.get("_owner_names") or DahuaAccessController.record_names(raw),
        "verification_status": event.verification_status, "people": event.people,
        "camera": event.camera,
        "clip_start": event.occurred_at - event.seconds_before,
        "clip_end": event.occurred_at + event.seconds_after,
    }


def _publish_event(event: AccessEvent, device_name: str | None = None) -> None:
    if _publisher is not None:
        _publisher("access_controller_events", json.dumps(serialize_access_event(event, device_name)))


def probe_device_with_info(device: AccessControl) -> tuple[AccessControl, dict | None]:
    """Record a connection result and return the device's raw system info."""
    info = None
    try:
        info = build_controller(device).get_system_info()
        if not info:
            raise ValueError("Empty system information")
        channel_count = int(info.get("channelNumber") or device.channel_count or 1)
    except (requests.RequestException, ValueError, AttributeError, TypeError) as err:
        device.status = (
            "offline"
            if isinstance(err, requests.ConnectionError)
            or (hasattr(err, "status") and err.status is None)
            else "error"
        )
        diagnostics = (
            err.as_dict()
            if hasattr(err, "as_dict")
            else {
                "provider": device.provider,
                "operation": "get_system_info",
                "exception_type": type(err).__name__,
                "message": str(err),
            }
        )
        logger.warning(
            "Unable to reach access controller %s: %s", device.id, diagnostics
        )
        fields = [AccessControl.status, AccessControl.last_checked_at]
    else:
        device.name = (
            info.get("deviceName") or info.get("name") or device.name or device.id
        )
        device.type = info.get("deviceType") or device.type or "Dahua"
        device.model = (
            info.get("model") or info.get("deviceType") or device.model or "Unknown"
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


def _timestamp(value: datetime | float | None) -> float | None:
    if value is None:
        return None
    return value.timestamp() if isinstance(value, datetime) else float(value)


def _detected_names(person: dict) -> set[str]:
    return {name.strip().casefold() for name in str(person["name"]).split(",")}


def _access_granted_card_scan(row: dict) -> bool:
    """Select successful card scans, excluding denied and non-card events."""
    normalized = DahuaAccessController.normalize_event(row, "")
    if not normalized["card_number"]:
        return False
    method = normalized["authentication_method"]
    if method is not None and str(method).casefold() not in {"2", "10", "11", "card"}:
        return False
    if normalized["status"] == "Failed":
        return False
    if normalized["access_status"] is not None:
        return normalized["status"] == "OK"
    event_type = str(row.get("EventType") or row.get("event_code") or "").casefold()
    return event_type in {"accessgranted", "accessallowed"}


def _store_record(
    device: AccessControl, row: dict, owner_names: list[str], owners_complete: bool
) -> None:
    with _record_locks.setdefault(device.id, threading.RLock()):
        _store_record_locked(device, row, owner_names, owners_complete)


def _store_record_locked(
    device: AccessControl, row: dict, owner_names: list[str], owners_complete: bool
) -> None:
    row = DahuaAccessController.sanitize_raw_event(row)
    normalized = DahuaAccessController.normalize_event(row, device.id)
    occurred_at = normalized["timestamp"]
    if occurred_at is None:
        return
    card_number = normalized["card_number"] or ""
    is_new_scan = _access_granted_card_scan(row) and occurred_at >= (
        device.event_tracking_started_at or 0
    )
    identity = _event_identity(normalized)
    record_number = normalized["record_number"]
    candidates = AccessEvent.select().where(
        (AccessEvent.device_id == device.id) & (AccessEvent.occurred_at == occurred_at)
    )
    existing = None
    for candidate in candidates:
        candidate_normalized = DahuaAccessController.normalize_event(candidate.raw_record, device.id)
        candidate_number = candidate_normalized["record_number"]
        if record_number is not None and candidate_number is not None:
            if str(record_number) == str(candidate_number):
                existing = candidate
                break
        elif _event_identity(candidate_normalized) == identity:
            existing = candidate
            break
    fingerprint = existing.id if existing is not None else hashlib.sha256(
        json.dumps([device.id, occurred_at, identity, record_number], default=str).encode()
    ).hexdigest()
    record = {
        **row,
        **normalized,
        **(normalized.get("data") if isinstance(normalized.get("data"), dict) else {}),
        "_owner_names": owner_names,
        "_owner_names_complete": owners_complete,
    }
    if existing is not None:
        # Keep the live row's ID, verification result, and camera window when
        # a historical record later supplies a RecNo or more event details.
        merged = {
            **existing.raw_record,
            **{key: value for key, value in record.items() if value not in (None, "")},
        }
        if not owner_names:
            merged["_owner_names"] = existing.raw_record.get("_owner_names", [])
            merged["_owner_names_complete"] = existing.raw_record.get("_owner_names_complete", False)
        if existing.raw_record != merged:
            existing.raw_record = merged
            existing.save(only=[AccessEvent.raw_record])
            _publish_event(existing, device.name)
        return
    AccessEvent.insert(
        id=fingerprint,
        device_id=device.id,
        occurred_at=occurred_at,
        card_number=card_number or None,
        raw_record=record,
        verification_status="pending" if is_new_scan else "unverified",
        people=[],
        camera=device.associated_camera,
        seconds_before=device.seconds_before,
        seconds_after=device.seconds_after,
    ).on_conflict_ignore().execute()
    saved = AccessEvent.get_by_id(fingerprint)
    _publish_event(saved, device.name)


def _event_identity(normalized: dict) -> tuple[str, ...]:
    """Match live JSON and string-valued historical representations."""
    return tuple(str(normalized.get(key) if normalized.get(key) is not None else "").casefold()
                 for key in ("door_id", "reader_id", "card_number", "user_id",
                             "status", "authentication_method", "type"))


def _store_live_event(device_id: str, event: dict) -> None:
    """Normalize a provider event and store it in the existing event table."""
    device = AccessControl.get_or_none(AccessControl.id == device_id)
    if device is None:
        return
    normalized = DahuaAccessController.normalize_event(event, device_id)
    if normalized["event_code"] != "AccessControl":
        return
    if normalized["timestamp"] is None:
        normalized["timestamp"] = time.time()
        normalized["timestamp_source"] = "received_at"
    record = {
        **(event.get("raw") if isinstance(event.get("raw"), dict) else {}),
        **(normalized.get("data") if isinstance(normalized.get("data"), dict) else {}),
        **normalized,
        "live": True,
    }
    _store_record(
        device,
        record,
        DahuaAccessController.record_names(record),
        bool(DahuaAccessController.record_names(record)),
    )


async def synchronize_controller_history(
    device_id: str | None = None, start: datetime | None = None,
    end: datetime | None = None, count: int = 500,
) -> list[dict]:
    """Import history on demand, retaining stored events on device failures."""
    devices = await asyncio.to_thread(
        lambda: list(AccessControl.select().where(AccessControl.id == device_id))
        if device_id else list(AccessControl.select())
    )
    semaphore = asyncio.Semaphore(8)

    async def sync(device: AccessControl) -> dict:
        lock = _history_locks.setdefault(device.id, asyncio.Lock())
        async with semaphore, lock:
            controller = build_controller(device)
            try:
                records = await controller.get_access_history_async(start, end, count=count)
            except (requests.RequestException, ValueError) as err:
                logger.warning("Unable to synchronize history for %s: %s", device.id, err)
                return {"device_id": device.id, "success": False, "incomplete": False}
            await asyncio.to_thread(_ingest_history, device, records)
            incomplete = getattr(controller.provider, "history_incomplete", False) is True
            return {"device_id": device.id, "success": True, "count": len(records), "incomplete": incomplete}

    return await asyncio.gather(*(sync(device) for device in devices))


def _ingest_history(device: AccessControl, records: list[dict]) -> None:
    if device.event_tracking_started_at is None:
        device.event_tracking_started_at = time.time()
    for row in records:
        names = DahuaAccessController.record_names(row)
        _store_record(device, row, names, bool(names))
    device.last_event_poll = time.time()
    device.save(only=[AccessControl.last_event_poll, AccessControl.event_tracking_started_at])


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
    poll_start = max(0, (device.last_event_poll or poll_end - HISTORY_SECONDS) - 30)
    controller = build_controller(device)
    try:
        rows = controller.get_access_records(
            datetime.fromtimestamp(poll_start, UTC).astimezone(),
            datetime.fromtimestamp(poll_end, UTC).astimezone(),
        )
    except (requests.RequestException, ValueError) as err:
        diagnostics = (
            err.as_dict()
            if hasattr(err, "as_dict")
            else {
                "provider": device.provider,
                "operation": "get_access_records",
                "exception_type": type(err).__name__,
                "message": str(err),
            }
        )
        logger.warning(
            "Unable to fetch access events for %s: %s", device.id, diagnostics
        )
        return device
    owners_by_card: dict[str, list[str]] = {}
    for row in rows:
        card_number = str(row.get("CardNo") or row.get("card_number") or "").strip()
        event_names = DahuaAccessController.record_names(row)
        has_name_array = any(
            key.startswith(("CardName[", "CardNames[", "UserNames[", "Names["))
            or (
                key in {"CardName", "CardNames", "UserNames", "Names"}
                and (
                    isinstance(value, list)
                    or (isinstance(value, str) and value.strip().startswith("["))
                )
            )
            for key, value in row.items()
        )
        if (
            _access_granted_card_scan(row)
            and not has_name_array
            and card_number not in owners_by_card
        ):
            try:
                owners_by_card[card_number] = controller.get_card_owners(card_number)
            except (requests.RequestException, ValueError) as err:
                logger.warning(
                    "Unable to read card owners from controller %s: %s", device.id, err
                )
                owners_by_card[card_number] = []
        _store_record(
            device,
            row,
            event_names
            if has_name_array
            else owners_by_card.get(card_number) or event_names,
            bool(owners_by_card.get(card_number)) or has_name_array,
        )
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
        owner_names = access_event.raw_record.get(
            "_owner_names"
        ) or DahuaAccessController.record_names(access_event.raw_record)
        owners = {
            name.casefold()
            for name in owner_names
            if isinstance(name, str) and name.strip()
        }
        registered_faces = (
            {path.name.casefold() for path in Path(FACE_DIR).iterdir() if path.is_dir()}
            if Path(FACE_DIR).is_dir()
            else set()
        )
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

        if (
            not owners
            or access_event.raw_record.get("_owner_names_complete") is False
            or not owners.issubset(registered_faces)
            or not has_recording
            or not people
        ):
            access_event.verification_status = "unknown"
        elif any(not _detected_names(person).issubset(owners) for person in people):
            access_event.verification_status = "warning"
        elif any(_detected_names(person).intersection(owners) for person in people):
            access_event.verification_status = "valid"
        else:
            access_event.verification_status = "unknown"
        access_event.save()
        device = AccessControl.get_or_none(AccessControl.id == access_event.device_id)
        _publish_event(access_event, device.name if device else None)


async def poll_all_controllers() -> list[AccessControl | None]:
    """Probe every device concurrently without unbounded network requests."""

    def device_ids() -> list[str]:
        return [device.id for device in AccessControl.select(AccessControl.id)]

    ids = await asyncio.to_thread(device_ids)
    semaphore = asyncio.Semaphore(8)

    async def poll(device_id: str) -> AccessControl | None:
        async with semaphore:
            try:
                device = await asyncio.to_thread(AccessControl.get_or_none, AccessControl.id == device_id)
                return await asyncio.to_thread(probe_device, device) if device else None
            except Exception:
                logger.exception("Unable to poll access controller %s", device_id)
                return await asyncio.to_thread(_mark_poll_error, device_id)

    return await asyncio.gather(*(poll(device_id) for device_id in ids))


async def run_controller_polling(
    publisher: Callable[[str, str], None] | None = None,
) -> None:
    """Refresh controller status and process scans throughout API uptime."""
    global _publisher
    _publisher = publisher
    listener_tasks: dict[str, asyncio.Task] = {}
    signatures: dict[str, tuple] = {}
    try:
        while True:
            try:
                devices = await asyncio.to_thread(lambda: list(AccessControl.select()))
                current = {
                    device.id: (device.ip_address, device.port, device.username,
                                device.password, device.provider, device.sdk_port,
                                device.use_https, json.dumps(device.provider_options, sort_keys=True))
                    for device in devices
                }
                for device_id, task in list(listener_tasks.items()):
                    if task.done() or current.get(device_id) != signatures.get(device_id):
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        listener_tasks.pop(device_id)
                        signatures.pop(device_id, None)
                        _stream_states.pop(device_id, None)
                for device in devices:
                    if device.id not in listener_tasks:
                        if device.event_tracking_started_at is None:
                            device.event_tracking_started_at = time.time()
                            await asyncio.to_thread(device.save, only=[AccessControl.event_tracking_started_at])
                        signatures[device.id] = current[device.id]
                        listener_tasks[device.id] = asyncio.create_task(
                            _listen_to_controller(device.id)
                        )
                await poll_all_controllers()
                await asyncio.to_thread(verify_pending_events)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Access controller polling failed")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    finally:
        for task in listener_tasks.values():
            task.cancel()
        await asyncio.gather(*listener_tasks.values(), return_exceptions=True)
        _publisher = None
        _stream_states.clear()
        _history_locks.clear()


async def _listen_to_controller(device_id: str) -> None:
    """Keep the selected provider's live subscription active."""
    while True:
        device = await asyncio.to_thread(
            AccessControl.get_or_none, AccessControl.id == device_id
        )
        if device is None:
            return
        try:
            await asyncio.to_thread(_set_stream_state, device_id, "connecting")
            queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
            loop = asyncio.get_running_loop()

            def put_event(event: dict, current_queue=queue) -> None:
                try:
                    current_queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "Dropping live event for access controller %s because its queue is full",
                        device_id,
                    )

            def enqueue(event: dict, current_loop=loop, push_event=put_event) -> None:
                current_loop.call_soon_threadsafe(push_event, event)

            def observe(detail: dict) -> None:
                if detail.get("operation") == "listen_events" and detail.get("raw_response") == "<event stream connected>":
                    enqueue({"_connected": True})

            controller = build_controller(device, observe)

            listener = asyncio.create_task(controller.listen_events_async(enqueue))
            event_task: asyncio.Task | None = None
            history_task: asyncio.Task | None = None
            try:
                while True:
                    event_task = asyncio.create_task(queue.get())
                    completed, _ = await asyncio.wait(
                        {listener, event_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if listener in completed:
                        # Flush callbacks scheduled by the final stream chunk
                        # before deciding that no more queued events remain.
                        await asyncio.sleep(0)
                        if not event_task.done():
                            event_task.cancel()
                            await asyncio.gather(event_task, return_exceptions=True)
                            await listener
                            raise ConnectionError("Controller event stream ended")
                    event = event_task.result()
                    event_task = None
                    if controller_stream_state(device_id) != "live":
                        await asyncio.to_thread(_set_stream_state, device_id, "live")
                        # Reconcile the available archive after reconnecting,
                        # without assuming the device's wall-clock timezone.
                        history_task = asyncio.create_task(synchronize_controller_history(device_id))
                    if event.get("_connected"):
                        continue
                    await asyncio.to_thread(_store_live_event, device_id, event)
            finally:
                if event_task is not None:
                    event_task.cancel()
                listener.cancel()
                if history_task is not None:
                    history_task.cancel()
                await asyncio.gather(
                    listener, *(task for task in (event_task, history_task) if task is not None),
                    return_exceptions=True,
                )
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 - keep the background listener alive
            await asyncio.to_thread(_set_stream_state, device_id, "reconnecting")
            diagnostics = (
                err.as_dict()
                if hasattr(err, "as_dict")
                else {
                    "provider": getattr(device, "provider", "unknown"),
                    "operation": "listen_events",
                    "exception_type": type(err).__name__,
                    "message": str(err),
                }
            )
            logger.warning(
                "Live event subscription failed for %s: %s", device_id, diagnostics
            )
            await asyncio.sleep(3)
