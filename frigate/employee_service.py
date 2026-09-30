"""Local employee permissions and snapshot-bound cardless verification."""

import asyncio
import base64
import hashlib
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
import zmq
from peewee import IntegrityError

from frigate.access_controller_service import build_controller
from frigate.comms.embeddings_updater import SOCKET_REP_REQ
from frigate.comms.object_detector_signaler import ObjectDetectorSubscriber
from frigate.const import FACE_DIR
from frigate.dahua_adapter import DahuaNotSupported, DahuaOperationError
from frigate.models import (
    AccessControl, Employee, EmployeeAccessAttempt, EmployeeAccessSettings,
    EmployeeControllerSync, EmployeeDoorOverride, EmployeeSource,
)
from frigate.util.image import UntrackedSharedMemory
from frigate.util.object import create_tensor_input
from frigate.util.path import safe_join, sanitize_path_component

logger = logging.getLogger(__name__)
DETECTOR_NAME = "frigate.employee-verification"
VERIFICATION_SECONDS = 10
UPLOAD_LIMIT = 10 * 1024 * 1024


class EmployeeAccessError(Exception):
    """A safe, translatable failure code for the employee API."""

    def __init__(self, reason: str, status: int = 400):
        self.reason = reason
        self.status = status
        super().__init__(reason)


def face_signature(name: str | None) -> str | None:
    """Identify current enrollment files, excluding empty folders and symlinks."""
    if not name or name == "train" or sanitize_path_component(name) != name:
        return None
    folder = safe_join(FACE_DIR, name)
    if folder is None:
        return None
    path = Path(folder)
    if path.is_symlink() or not path.is_dir():
        return None
    try:
        files = sorted(
            (item.name, item.stat().st_size, item.stat().st_mtime_ns)
            for item in path.iterdir()
            if item.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            and item.is_file() and not item.is_symlink() and item.stat().st_size > 0
        )
    except OSError:
        return None
    return hashlib.sha256(repr(files).encode()).hexdigest() if files else None


def source_id(controller_id: str, user_id: str) -> str:
    """Keep controller identity boundaries even when user IDs are reused."""
    return hashlib.sha256(f"{controller_id}\0{user_id}".encode()).hexdigest()


def employee_doors(employee_id: str, controller_id: str) -> list[str]:
    """Resolve an explicit override, otherwise union active linked records."""
    override = EmployeeDoorOverride.get_or_none(
        (EmployeeDoorOverride.employee_id == employee_id)
        & (EmployeeDoorOverride.controller_id == controller_id)
    )
    if override is not None:
        return override.doors
    sources = EmployeeSource.select().where(
        (EmployeeSource.employee_id == employee_id)
        & (EmployeeSource.controller_id == controller_id)
        & EmployeeSource.active & ~EmployeeSource.suppressed
    )
    return sorted({str(door) for source in sources for door in source.doors})


def serialize_employee(employee: Employee) -> dict[str, Any]:
    """Return administrative data without credential hashes."""
    sources = list(EmployeeSource.select().where(EmployeeSource.employee_id == employee.id))
    controllers = {source.controller_id for source in sources}
    overrides = list(EmployeeDoorOverride.select().where(EmployeeDoorOverride.employee_id == employee.id))
    controllers.update(item.controller_id for item in overrides)
    return {
        "id": employee.id, "name": employee.name,
        "display_name": employee.name or (sources[0].name if sources else ""),
        "username": employee.username, "enabled": employee.enabled,
        "pending": not bool(employee.name and employee.username and employee.password_hash),
        "has_face": bool(face_signature(employee.face_name)), "face_name": employee.face_name,
        "sources": [{"id": source.id, "controller_id": source.controller_id,
                     "user_id": source.user_id, "name": source.name, "active": source.active}
                    for source in sources],
        "permissions": [{"controller_id": controller, "doors": employee_doors(employee.id, controller),
                         "overridden": any(item.controller_id == controller for item in overrides)}
                        for controller in sorted(controllers)],
    }


def embedding_request(topic: str, data: dict[str, Any], timeout: float = 4) -> dict[str, Any]:
    """Use a private bounded socket so requests cannot steal another reply."""
    context = zmq.Context()
    try:
        with context.socket(zmq.REQ) as socket:
            socket.setsockopt(zmq.LINGER, 0)
            milliseconds = max(1, int(timeout * 1000))
            socket.setsockopt(zmq.SNDTIMEO, milliseconds)
            socket.setsockopt(zmq.RCVTIMEO, milliseconds)
            socket.connect(SOCKET_REP_REQ)
            socket.send_json((topic, data))
            result = socket.recv_json()
    except zmq.ZMQError as err:
        raise EmployeeAccessError("recognition_unavailable", 503) from err
    finally:
        context.destroy(linger=0)
    if not isinstance(result, dict):
        raise EmployeeAccessError("recognition_unavailable", 503)
    return result


class SnapshotDetector:
    """One detector lane, quarantined after a timeout until its reply arrives."""

    def __init__(self, config, detection_queue, stop_event):
        self.config = config
        self.queue = detection_queue
        self.stop_event = stop_event
        self.input_shm = UntrackedSharedMemory(name=DETECTOR_NAME, create=False)
        self.output_shm = UntrackedSharedMemory(name=f"out-{DETECTOR_NAME}", create=False)
        self.output = np.ndarray((20, 6), dtype=np.float32, buffer=self.output_shm.buf)
        self.subscriber = ObjectDetectorSubscriber(DETECTOR_NAME)
        self.pending = False

    def detect(self, frame: np.ndarray, min_score: float, deadline: float) -> list[tuple[int, int, int, int]]:
        """Detect persons across the complete snapshot, without motion masks."""
        if self.stop_event.is_set() or time.monotonic() >= deadline:
            raise EmployeeAccessError("detection_unavailable", 503)
        if self.pending:
            if self.subscriber.check_for_update(0) is None:
                raise EmployeeAccessError("detection_unavailable", 503)
            self.pending = False
        while self.subscriber.check_for_update(0) is not None:
            pass
        height = frame.shape[0] * 2 // 3
        width = frame.shape[1]
        side = (max(width, height) + 3) // 4 * 4
        tensor = create_tensor_input(frame, self.config.model, (0, 0, side, side))
        memory = np.ndarray(tensor.shape, dtype=np.uint8, buffer=self.input_shm.buf)
        memory[:] = tensor
        remaining = min(3, deadline - time.monotonic())
        if remaining <= 0:
            raise EmployeeAccessError("face_not_detected")
        self.output[:] = np.nan
        self.pending = True
        self.queue.put(DETECTOR_NAME)
        if self.subscriber.check_for_update(remaining) is None:
            raise EmployeeAccessError("detection_unavailable", 503)
        self.pending = False
        rows = self.output.copy()
        if not np.isfinite(rows).all() or rows[-1, 1] >= min_score:
            raise EmployeeAccessError("detection_unavailable", 503)
        people = []
        for label, score, ymin, xmin, ymax, xmax in rows:
            if score < min_score:
                continue
            if self.config.model.merged_labelmap.get(int(label)) != "person":
                continue
            box = (max(0, int(xmin * side)), max(0, int(ymin * side)),
                   min(width, int(xmax * side)), min(height, int(ymax * side)))
            if box[2] > box[0] and box[3] > box[1]:
                people.append(box)
        return people

    def close(self) -> None:
        """Close attachments; the parent app owns shared-memory deletion."""
        self.subscriber.stop()
        self.input_shm.close()
        self.output_shm.close()


class EmployeeService:
    """Coordinate local policy, directory imports, and single-use unlocks."""

    def __init__(self, app, detection_queue=None, stop_event=None):
        self.app = app
        self.policy_lock = asyncio.Lock()
        self.sync_lock = asyncio.Lock()
        self.active: set[str] = set()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="employee_detector")
        self.detector: SnapshotDetector | None = None
        self.detection_queue = detection_queue
        self.stop_event = stop_event
        self.sync_semaphore = asyncio.Semaphore(2)
        self.sync_requested = asyncio.Event()
        self.loop: asyncio.AbstractEventLoop | None = None

    @property
    def config(self):
        """Read the live config holder so camera removals fail closed."""
        holder = self.app.config_holder
        return holder.config if holder is not None else self.app.frigate_config

    async def start(self) -> None:
        """Recover command claims without ever replaying an unlock."""
        self.loop = asyncio.get_running_loop()
        await asyncio.to_thread(
            EmployeeAccessAttempt.update(status="interrupted", result={
                "success": False, "reason": "operation_interrupted", "door_command": "unknown",
            }).where(EmployeeAccessAttempt.status.in_(["verifying", "opening"])).execute
        )
        if self.detection_queue is not None:
            loop = asyncio.get_running_loop()
            self.detector = await loop.run_in_executor(
                self.executor, SnapshotDetector, self.config, self.detection_queue, self.stop_event
            )

    async def stop(self) -> None:
        """Close the dedicated lane on its owning thread."""
        if self.detector is not None:
            await asyncio.get_running_loop().run_in_executor(self.executor, self.detector.close)
        self.executor.shutdown(wait=False, cancel_futures=True)

    async def poll(self) -> None:
        """Refresh imports and retain audit metadata for thirty days."""
        while True:
            self.sync_requested.clear()
            try:
                await self.synchronize()
                await asyncio.to_thread(
                    EmployeeAccessAttempt.delete().where(
                        EmployeeAccessAttempt.created_at < time.time() - 30 * 86400
                    ).execute
                )
            except Exception:
                logger.exception("Employee import maintenance failed")
            try:
                await asyncio.wait_for(self.sync_requested.wait(), timeout=300)
            except TimeoutError:
                pass

    def request_sync(self) -> None:
        """Wake directory maintenance after a controller is saved."""
        if self.loop is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.sync_requested.set)

    async def synchronize(self) -> list[dict[str, Any]]:
        """Import complete directories without changing controller users."""
        async with self.sync_lock:
            devices = await asyncio.to_thread(lambda: list(AccessControl.select()))
            return await asyncio.gather(*(self._sync_controller(device) for device in devices))

    async def _sync_controller(self, device: AccessControl) -> dict[str, Any]:
        async with self.sync_semaphore:
            controller = build_controller(device)
            try:
                directory, doors = await asyncio.wait_for(asyncio.gather(
                    controller.get_users_async(), controller.get_doors_async()
                ), timeout=30)
                users = directory["users"]
                if not isinstance(users, list):
                    raise ValueError("Invalid user directory")
                door_ids = {str(door["id"]) for door in doors}
                for user in users:
                    if (not isinstance(user, dict)
                        or not isinstance(user.get("user_id"), str)
                        or not 0 < len(user["user_id"].strip()) <= 100
                        or not isinstance(user.get("active"), bool)
                        or not isinstance(user.get("doors"), list)
                        or any(not isinstance(door, (str, int)) or isinstance(door, bool) for door in user["doors"])):
                        raise ValueError("Invalid user record")
                if len({user["user_id"].strip() for user in users}) != len(users):
                    raise ValueError("Duplicate user record")
                async with self.policy_lock:
                    await asyncio.to_thread(self._apply_directory, device.id, users, door_ids)
                status = "limited" if directory.get("limited") else "ok"
            except DahuaNotSupported:
                status = "unsupported"
            except (DahuaOperationError, TimeoutError, ValueError, KeyError, TypeError):
                logger.warning("Unable to import users for controller %s", device.id)
                status = "failed"
            values = {"controller_id": device.id, "checked_at": time.time(), "status": status}
            if status in {"ok", "limited"}:
                values["last_success"] = time.time()
            await asyncio.to_thread(lambda: EmployeeControllerSync.insert(**values).on_conflict(
                conflict_target=[EmployeeControllerSync.controller_id], update=values
            ).execute())
            return {"controller_id": device.id, "status": status}

    def _apply_directory(self, controller_id: str, users: list[dict], door_ids: set[str]) -> None:
        seen = set()
        for user in users:
            user_id = str(user["user_id"]).strip()
            key = source_id(controller_id, user_id)
            seen.add(key)
            source = EmployeeSource.get_or_none(EmployeeSource.id == key)
            if source is not None and source.suppressed:
                continue
            if source is None:
                employee = Employee.create(id=uuid4().hex)
                source = EmployeeSource.create(
                    id=key, controller_id=controller_id, user_id=user_id,
                    employee_id=employee.id, name=str(user.get("name") or user_id)[:100],
                )
            source.name = str(user.get("name") or user_id)[:100]
            source.active = bool(user.get("active", False))
            source.doors = sorted({str(door) for door in user["doors"]} & door_ids) if source.active else []
            source.save()
        EmployeeSource.update(active=False, doors=[]).where(
            (EmployeeSource.controller_id == controller_id) & ~EmployeeSource.id.in_(seen)
        ).execute()

    def snapshot(self, camera: str, after: float) -> tuple[np.ndarray, float] | None:
        """Copy the current raw Frigate frame while holding its frame lock."""
        state = self.app.detected_frames_processor.camera_states.get(camera)
        if state is None:
            raise EmployeeAccessError("snapshot_failed")
        with state.current_frame_lock:
            timestamp = state.current_frame_time
            frame = state._current_frame
            if frame is None or abs(time.time() - timestamp) > 2:
                raise EmployeeAccessError("snapshot_failed")
            if timestamp <= after:
                return None
            return frame.copy(), timestamp

    @staticmethod
    def person_image(frame: np.ndarray, box: tuple[int, int, int, int]) -> str:
        """Encode the detected person off the event loop without saving it."""
        x1, y1, x2, y2 = box
        image = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)[y1:y2, x1:x2]
        encoded, jpeg = cv2.imencode(".jpg", image)
        if not encoded:
            raise EmployeeAccessError("snapshot_failed")
        return base64.b64encode(jpeg).decode("ascii")

    async def authorize(self, employee_id: str, version: int, camera: str,
                        controller_id: str, door_id: str) -> tuple[Employee, AccessControl, int, str]:
        """Enforce employee enrollment, camera association, and local door grants."""
        def policy():
            employee = Employee.get_or_none(Employee.id == employee_id)
            if employee is None or not employee.enabled or employee.auth_version != version:
                raise EmployeeAccessError("session_expired", 401)
            settings = EmployeeAccessSettings.get_by_id(1)
            if not settings.enabled:
                raise EmployeeAccessError("system_disabled", 403)
            signature = face_signature(employee.face_name)
            if not signature or employee.face_name != employee.name:
                raise EmployeeAccessError("no_registered_face", 403)
            device = AccessControl.get_or_none(AccessControl.id == controller_id)
            camera_config = self.config.cameras.get(camera)
            if device is None or device.associated_camera != camera or door_id not in employee_doors(employee_id, controller_id):
                raise EmployeeAccessError("access_denied", 403)
            if camera_config is None or not camera_config.enabled or not camera_config.detect.enabled:
                raise EmployeeAccessError("snapshot_failed")
            if not self.config.face_recognition.enabled or not camera_config.face_recognition.enabled:
                raise EmployeeAccessError("recognition_unavailable", 503)
            return employee, device, settings.generation, signature
        return await asyncio.to_thread(policy)

    async def verify(self, employee: Employee, camera: str, controller_id: str,
                     door_id: str, request_id: str) -> dict[str, Any]:
        """Bind a fresh snapshot, target face, and one unlock to the session."""
        async with self.policy_lock:
            previous = await asyncio.to_thread(EmployeeAccessAttempt.get_or_none, EmployeeAccessAttempt.id == request_id)
            if previous is not None:
                if (previous.employee_id, previous.camera, previous.controller_id, previous.door_id) != (employee.id, camera, controller_id, door_id):
                    raise EmployeeAccessError("request_conflict", 409)
                if previous.result:
                    return {**previous.result, "request_id": request_id}
                raise EmployeeAccessError("operation_in_progress", 409)
            if employee.id in self.active:
                raise EmployeeAccessError("operation_in_progress", 409)
            self.active.add(employee.id)
            try:
                await asyncio.to_thread(EmployeeAccessAttempt.create,
                    id=request_id, employee_id=employee.id, camera=camera,
                    controller_id=controller_id, door_id=door_id, created_at=time.time())
            except IntegrityError as err:
                self.active.discard(employee.id)
                raise EmployeeAccessError("request_conflict", 409) from err
        score = None
        result = {"success": False, "reason": "operation_interrupted", "door_command": "not_sent"}
        try:
            async with self.policy_lock:
                fresh, device, generation, signature = await self.authorize(
                    employee.id, employee.auth_version, camera, controller_id, door_id
                )
            if self.detector is None:
                raise EmployeeAccessError("detection_unavailable", 503)
            deadline = time.monotonic() + VERIFICATION_SECONDS
            after = time.time()
            controller = build_controller(device)
            # Door discovery is read-only and happens before any command claim.
            doors = await asyncio.wait_for(controller.get_doors_async(), timeout=3)
            if not any(str(door["id"]) == door_id for door in doors):
                raise EmployeeAccessError("access_denied", 403)
            while time.monotonic() < deadline:
                async with self.policy_lock:
                    current, _, current_generation, current_signature = await self.authorize(
                        employee.id, employee.auth_version, camera, controller_id, door_id
                    )
                    if current_generation != generation or current_signature != signature or current.face_name != fresh.face_name:
                        raise EmployeeAccessError("policy_changed", 403)
                snapshot = await asyncio.to_thread(self.snapshot, camera, after)
                if snapshot is None:
                    await asyncio.sleep(0.1)
                    continue
                frame, after = snapshot
                person_filter = self.config.cameras[camera].objects.filters.get("person")
                min_score = person_filter.min_score if person_filter is not None else 0.5
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    people = await asyncio.wait_for(
                        asyncio.get_running_loop().run_in_executor(
                            self.executor, self.detector.detect, frame, min_score, deadline
                        ), timeout=remaining,
                    )
                except TimeoutError as err:
                    raise EmployeeAccessError("face_not_detected") from err
                if time.monotonic() >= deadline:
                    break
                if not people:
                    raise EmployeeAccessError("no_person")
                if len(people) != 1:
                    raise EmployeeAccessError("multiple_persons")
                image = await asyncio.to_thread(self.person_image, frame, people[0])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    response = await asyncio.wait_for(asyncio.to_thread(
                        embedding_request, "verify_employee_face", {
                            "camera": camera, "face_name": fresh.face_name,
                            "enrollment_signature": signature, "image": image,
                        }, min(remaining, 3),
                    ), timeout=remaining)
                except TimeoutError as err:
                    raise EmployeeAccessError("face_not_detected") from err
                if time.monotonic() >= deadline:
                    break
                if response.get("retry"):
                    await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
                    continue
                score = response.get("score")
                if not response.get("success"):
                    raise EmployeeAccessError(response.get("reason", "identity_not_verified"))
                if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score) or score < self.config.face_recognition.recognition_threshold:
                    raise EmployeeAccessError("identity_not_verified")
                async with self.policy_lock:
                    current, current_device, current_generation, current_signature = await self.authorize(
                        employee.id, employee.auth_version, camera, controller_id, door_id
                    )
                    if (generation, signature, fresh.face_name) != (current_generation, current_signature, current.face_name):
                        raise EmployeeAccessError("policy_changed", 403)
                    connection_fields = ("ip_address", "port", "provider", "associated_camera",
                                         "sdk_port", "use_https", "provider_options", "username", "password")
                    if any(getattr(device, field) != getattr(current_device, field) for field in connection_fields):
                        raise EmployeeAccessError("policy_changed", 403)
                    if score < self.config.face_recognition.recognition_threshold:
                        raise EmployeeAccessError("identity_not_verified")
                    if time.monotonic() >= deadline:
                        raise EmployeeAccessError("face_not_detected")
                    claimed = await asyncio.to_thread(EmployeeAccessAttempt.update(status="opening", score=score).where(
                        (EmployeeAccessAttempt.id == request_id) & (EmployeeAccessAttempt.status == "verifying")
                    ).execute)
                    if not claimed:
                        raise EmployeeAccessError("operation_interrupted", 409)
                    if time.monotonic() >= deadline:
                        raise EmployeeAccessError("face_not_detected")
                    result = {"success": False, "identity_verified": True, "reason": "door_outcome_unknown", "door_command": "unknown"}
                    # Keep policy mutations serialized until command completion.
                    command = await asyncio.wait_for(controller.open_door_async(door_id), timeout=5)
                    if command.get("accepted") is not True:
                        raise EmployeeAccessError("door_command_failed", 502)
                    result = {"success": True, "identity_verified": True, "reason": "verified", "door_command": "accepted"}
                break
            else:
                raise EmployeeAccessError("face_not_detected")
            if not result.get("identity_verified"):
                raise EmployeeAccessError("face_not_detected")
        except EmployeeAccessError as err:
            result = {**result, "success": False, "reason": err.reason}
        except (TimeoutError, DahuaOperationError):
            reason = "door_outcome_unknown" if result.get("identity_verified") else "controller_unavailable"
            result = {**result, "success": False, "reason": reason}
        except (cv2.error, ValueError, KeyError, OSError):
            logger.exception("Employee snapshot verification failed")
            result = {**result, "success": False, "reason": "verification_failed"}
        finally:
            self.active.discard(employee.id)
            await asyncio.shield(asyncio.to_thread(EmployeeAccessAttempt.update(
                status="complete", result=result, score=score,
            ).where(EmployeeAccessAttempt.id == request_id).execute))
        return {**result, "request_id": request_id}
