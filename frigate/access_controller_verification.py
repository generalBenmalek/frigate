"""Collect camera identity evidence for controller scans without requiring media."""

import base64
import hashlib
import logging
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import zmq

from frigate.comms.embeddings_updater import SOCKET_REP_REQ
from frigate.const import CACHE_DIR
from frigate.models import Event, Recordings, Timeline
from frigate.util.file import get_event_snapshot_bytes
from frigate.util.image import run_ffmpeg_snapshot

logger = logging.getLogger(__name__)
SNAPSHOT_COUNT = 3
SNAPSHOT_INTERVAL = 2
SNAPSHOT_RETENTION = 24 * 60 * 60


def evidence_timestamp(event) -> float:
    """Use receipt time for live scans whose controller clock is incorrect."""
    return float(event.raw_record.get("_verification_time", event.occurred_at))


def identity_name(value: Any) -> str:
    """Unwrap Frigate's (name, score) live and timeline sub-labels."""
    if isinstance(value, (tuple, list)):
        value = value[0] if value else None
    return str(value).strip() if value else "unknown"


def known_names(value: Any) -> set[str]:
    """Normalize identities, excluding labels that do not identify a person."""
    return {
        " ".join(name.split()).casefold()
        for name in identity_name(value).split(",")
        if name.strip().casefold() not in {"", "unknown", "person", "none"}
    }


def merge_people(*collections: list[dict]) -> list[dict]:
    """Prefer a recognized identity over an earlier unknown for the same object."""
    result: dict[tuple[str, str], dict] = {}
    for collection in collections:
        for person in collection:
            object_id = str(person["event_id"])
            name = identity_name(person.get("name"))
            if known_names(name):
                result.pop((object_id, "unknown"), None)
            elif any(key[0] == object_id for key in result):
                continue
            result[(object_id, name.casefold())] = {**person, "name": name}
    return list(result.values())


def classify_people(owners: list[str], people: list[dict]) -> tuple[str, str]:
    """Require an identified owner; an unidentified bystander is inconclusive."""
    expected = set().union(*(known_names(name) for name in owners))
    observed = set().union(*(known_names(person.get("name")) for person in people))
    if not expected:
        return "unknown", "missing_owner"
    if observed - expected:
        return "warning", "identity_mismatch"
    if expected & observed:
        return "valid", "owner_matched"
    return "unknown", "unrecognized_person" if people else "no_person"


def _timestamp(value) -> float:
    return value.timestamp() if isinstance(value, datetime) else float(value)


def history_people(camera: str, start: float, end: float) -> list[dict]:
    """Read overlapping object events and detection timeline identities."""
    people = []
    detections = Event.select().where(
        (Event.camera == camera)
        & (Event.label == "person")
        & (Event.false_positive == False)
        & (Event.start_time <= end)
        & ((Event.end_time >= start) | Event.end_time.is_null())
    )
    for detection in detections:
        people.append({
            "event_id": detection.id, "name": identity_name(detection.sub_label),
            "start_time": _timestamp(detection.start_time),
            "end_time": _timestamp(detection.end_time) if detection.end_time else None,
            "source": "history", "has_clip": detection.has_clip,
            "has_snapshot": detection.has_snapshot,
        })
    entries = Timeline.select().where(
        (Timeline.camera == camera) & (Timeline.source == "tracked_object")
        & (Timeline.timestamp >= start) & (Timeline.timestamp <= end)
    )
    for entry in entries:
        if entry.data.get("label") != "person":
            continue
        people.append({
            "event_id": entry.source_id,
            "name": identity_name(entry.data.get("sub_label")),
            "start_time": _timestamp(entry.timestamp), "end_time": None,
            "source": "timeline",
        })
    return merge_people(people)


def snapshot_path(event_id: str, index: int) -> Path:
    """Resolve a bounded cache filename without accepting a filesystem path."""
    digest = hashlib.sha256(event_id.encode()).hexdigest()
    return Path(CACHE_DIR) / "access_snapshots" / f"{digest}-{index}.jpg"


def save_snapshot(event_id: str, index: int, image: bytes) -> None:
    """Cache a scan-time screenshot for recognition and the footage fallback."""
    path = snapshot_path(event_id, index)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image)


def cleanup_snapshots() -> None:
    """Keep access screenshots for at most one day without growing indefinitely."""
    directory = Path(CACHE_DIR) / "access_snapshots"
    for path in directory.glob("*.jpg"):
        try:
            if path.stat().st_mtime < time.time() - SNAPSHOT_RETENTION:
                path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Unable to remove an expired access screenshot")


class CameraEvidence:
    """Read active objects and use Frigate's existing face recognizer as fallback."""

    def __init__(self, processor, config) -> None:
        self.processor = processor
        self.config = config

    def live_people(self, camera: str, start: float, end: float) -> list[dict]:
        """Read identities that arrive after the initial three screenshots."""
        if self.processor is None:
            return []
        state = self.processor.camera_states.get(camera)
        if state is None:
            return []
        with state.current_frame_lock:
            frame_time = state.current_frame_time
            objects = [obj.to_dict() for obj in state.tracked_objects.values()]
        if not start <= frame_time <= end or abs(time.time() - frame_time) > 5:
            return []
        return [{
            "event_id": obj["id"], "name": identity_name(obj.get("sub_label")),
            "start_time": obj["start_time"], "end_time": obj.get("end_time"),
            "source": "live", "has_snapshot": obj.get("has_snapshot", False),
            "has_clip": obj.get("has_clip", False),
        } for obj in objects if obj["label"] == "person" and not obj["false_positive"]
                and abs(obj["frame_time"] - frame_time) <= 2 and not obj.get("end_time")]

    def sample(self, camera: str, start: float, end: float) -> dict:
        """Capture a fresh frame and current person objects from the same camera."""
        if self.processor is None:
            return {}
        state = self.processor.camera_states.get(camera)
        if state is None:
            return {}
        with state.current_frame_lock:
            frame_time = state.current_frame_time
            objects = [obj.to_dict() for obj in state.tracked_objects.values()]
            frame = state._current_frame.copy()
        if not start <= frame_time <= end or abs(time.time() - frame_time) > 5:
            return {}
        frame = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_I420)
        people, images = [], []
        for obj in objects:
            if obj["label"] != "person" or obj["false_positive"]:
                continue
            if abs(obj["frame_time"] - frame_time) > 2 or obj.get("end_time"):
                continue
            people.append({
                "event_id": obj["id"], "name": identity_name(obj.get("sub_label")),
                "start_time": obj["start_time"], "end_time": obj.get("end_time"),
                "source": "live", "has_snapshot": obj.get("has_snapshot", False),
                "has_clip": obj.get("has_clip", False),
            })
            if not known_names(obj.get("sub_label")) and len(images) < 4:
                x1, y1, x2, y2 = (int(value) for value in obj["box"])
                crop = frame[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
                if crop.size:
                    success, image = cv2.imencode(".jpg", crop)
                    if success:
                        images.append((obj["id"], image.tobytes(), frame_time))
        success, image = cv2.imencode(".jpg", frame)
        if not success:
            return {"people": people}
        screenshot = image.tobytes()
        if not people:
            images.append((f"frame-{frame_time}", screenshot, frame_time))
        return {"people": people, "images": images, "image": screenshot, "time": frame_time}

    def recognition_enabled(self, camera: str) -> bool:
        """Respect global and per-camera face recognition settings."""
        camera_config = self.config.cameras.get(camera)
        return bool(self.config.face_recognition.enabled and camera_config
                    and camera_config.face_recognition.enabled)

    def recognize(self, camera: str, images: list[tuple[str, bytes, float]]) -> list[dict]:
        """Use an isolated, timeout-bounded ZMQ socket in this worker thread."""
        if not images or not self.recognition_enabled(camera):
            return []
        people = []
        context = zmq.Context()
        try:
            for object_id, image, timestamp in images[:4]:
                # A timed-out REQ socket cannot be reused. Each image gets one
                # socket, avoiding interference with UI recognition requests.
                with context.socket(zmq.REQ) as socket:
                    socket.setsockopt(zmq.LINGER, 0)
                    socket.setsockopt(zmq.SNDTIMEO, 4000)
                    socket.setsockopt(zmq.RCVTIMEO, 4000)
                    socket.connect(SOCKET_REP_REQ)
                    try:
                        socket.send_json(("recognize_face", {
                            "image": base64.b64encode(image).decode("ASCII"),
                        }))
                        result = socket.recv_json()
                    except zmq.ZMQError:
                        logger.debug("Face recognition unavailable for access camera %s", camera)
                        break
                if not isinstance(result, dict) or not result.get("success"):
                    continue
                score = result.get("score")
                name = result.get("face_name")
                if not isinstance(score, (int, float)) or not math.isfinite(score) or score < self.config.face_recognition.recognition_threshold:
                    continue
                if known_names(name):
                    people.append({
                        "event_id": object_id, "name": identity_name(name),
                        "start_time": timestamp, "end_time": timestamp,
                        "source": "snapshot", "score": score,
                    })
        finally:
            context.destroy(linger=0)
        return people

    def historical_images(self, camera: str, start: float, end: float, people: list[dict]) -> list[tuple[str, bytes, float]]:
        """Read saved person snapshots captured inside the verification window."""
        images = []
        for person in people:
            if known_names(person.get("name")):
                continue
            event = Event.get_or_none(Event.id == person["event_id"], Event.camera == camera)
            if event is None or not event.has_snapshot:
                continue
            image, timestamp = get_event_snapshot_bytes(event, ext="jpg", crop=True)
            if image and start <= timestamp <= end:
                images.append((event.id, image, timestamp))
            if len(images) >= SNAPSHOT_COUNT:
                return images
        return images

    def recording_images(self, camera: str, start: float, end: float) -> list[tuple[str, bytes, float]]:
        """Extract at most three timeout-bounded frames from saved recording clips."""
        images = []
        camera_config = self.config.cameras.get(camera)
        if camera_config is None:
            return []
        for timestamp in (start, (start + end) / 2, end):
            recording = Recordings.select().where(
                (Recordings.camera == camera) & (Recordings.start_time <= timestamp)
                & (Recordings.end_time >= timestamp)
            ).first()
            if recording is None:
                continue
            image, _ = run_ffmpeg_snapshot(
                camera_config.ffmpeg, recording.path, "mjpeg",
                seek_time=max(0, timestamp - _timestamp(recording.start_time)), timeout=8,
            )
            if image:
                images.append((f"recording-{timestamp}", image, timestamp))
        return images

    def cached_images(self, event) -> list[tuple[str, bytes, float]]:
        """Reuse scan-time screenshots on a manual retry while the cache is fresh."""
        images = []
        for sample in event.raw_record.get("_snapshots", [])[:SNAPSHOT_COUNT]:
            path = snapshot_path(event.id, sample["index"])
            try:
                if path.stat().st_mtime >= time.time() - SNAPSHOT_RETENTION:
                    images.append((f"frame-{sample['timestamp']}", path.read_bytes(), sample["timestamp"]))
            except OSError:
                continue
        return images
