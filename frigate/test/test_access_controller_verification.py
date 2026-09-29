"""Regression coverage for camera evidence and identity classification."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from frigate.access_controller_verification import (
    CameraEvidence,
    classify_people,
    identity_name,
    merge_people,
)


class TestAccessControllerEvidence(unittest.TestCase):
    def test_matching_owner_and_unknown_bystander_are_not_a_mismatch(self):
        status, reason = classify_people([" Alice "], [
            {"event_id": "a", "name": "alice"},
            {"event_id": "b", "name": "unknown"},
        ])
        self.assertEqual((status, reason), ("valid", "owner_matched"))

    def test_recognized_non_owner_is_a_warning(self):
        self.assertEqual(classify_people(["Alice"], [
            {"event_id": "a", "name": "Alice"},
            {"event_id": "b", "name": "Bob"},
        ]), ("warning", "identity_mismatch"))

    def test_presence_without_identity_is_inconclusive(self):
        self.assertEqual(classify_people(["Alice"], [{"name": "unknown"}]),
                         ("unknown", "unrecognized_person"))
        self.assertEqual(classify_people([], [{"name": "Alice"}]),
                         ("unknown", "missing_owner"))

    def test_live_tuple_sub_label_is_unwrapped(self):
        self.assertEqual(identity_name(("Alice", 0.98)), "Alice")
        self.assertEqual(identity_name(["Alice", 0.98]), "Alice")

    def test_named_history_replaces_unknown_live_object(self):
        merged = merge_people(
            [{"event_id": "a", "name": "unknown", "source": "live"}],
            [{"event_id": "a", "name": "Alice", "source": "history"}],
        )
        self.assertEqual([person["name"] for person in merged], ["Alice"])

    def test_conflicting_known_names_are_retained(self):
        merged = merge_people(
            [{"event_id": "a", "name": "Alice"}],
            [{"event_id": "a", "name": "Bob"}],
        )
        self.assertEqual(classify_people(["Alice"], merged)[0], "warning")

    def test_stale_live_frame_cannot_verify_a_historical_scan(self):
        state = SimpleNamespace(
            current_frame_lock=threading.Lock(), current_frame_time=100,
            tracked_objects={}, _current_frame=np.zeros((6, 4), dtype=np.uint8),
        )
        evidence = CameraEvidence(SimpleNamespace(camera_states={"door": state}), Mock())
        with patch("frigate.access_controller_verification.time.time", return_value=1000):
            self.assertEqual(evidence.sample("door", 90, 110), {})

    def test_fresh_live_object_identity_is_captured_without_saved_media(self):
        obj = Mock()
        obj.to_dict.return_value = {
            "id": "person-1", "label": "person", "false_positive": False,
            "frame_time": 100, "start_time": 98, "end_time": None,
            "sub_label": ("Alice", 0.95), "box": (0, 0, 4, 4),
        }
        state = SimpleNamespace(
            current_frame_lock=threading.Lock(), current_frame_time=100,
            tracked_objects={"person-1": obj}, _current_frame=np.zeros((6, 4), dtype=np.uint8),
        )
        evidence = CameraEvidence(SimpleNamespace(camera_states={"door": state}), Mock())
        with patch("frigate.access_controller_verification.time.time", return_value=101):
            sample = evidence.sample("door", 95, 105)
        self.assertEqual(sample["people"][0]["name"], "Alice")
        self.assertEqual(sample["people"][0]["source"], "live")
        self.assertTrue(sample["image"])
