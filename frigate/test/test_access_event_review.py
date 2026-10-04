"""Portal ingestion, shared review, API filtering, and migration regressions."""

import asyncio
import importlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playhouse.sqlite_ext import SqliteExtDatabase
from playhouse.sqliteq import SqliteQueueDatabase

from frigate.access_controller_service import (
    _persist_portal_grant,
    _verify_event,
    serialize_access_event,
)
from frigate.access_event_review import AccessReviewError, submit_access_review
from frigate.api.access_controller import router
from frigate.employee_service import EmployeeService
from frigate.models import (
    AccessControl,
    AccessEvent,
    AccessEventReview,
    Employee,
    EmployeeAccessAttempt,
    EmployeeSource,
)

MODELS = (
    AccessControl,
    AccessEvent,
    AccessEventReview,
    Employee,
    EmployeeAccessAttempt,
    EmployeeSource,
)


class TestAccessReview(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "access.db")
        self.db = SqliteExtDatabase(self.path, pragmas={"journal_mode": "wal"})
        self.original_databases = {model: model._meta.database for model in MODELS}
        self.db.bind(MODELS)
        self.db.create_tables(MODELS)
        self.addCleanup(self.restore_bindings)
        captures = patch("frigate.access_controller_service._capture_tasks", {})
        captures.start()
        self.addCleanup(captures.stop)
        self.device = AccessControl.create(
            id="controller",
            name="Gate",
            ip_address="127.0.0.1",
            type="Dahua",
            model="test",
            serial_number="",
            username="",
            password="",
            associated_camera="gate",
        )
        self.employee = Employee.create(
            id="local-id", name="Mohamed", face_name="Mohamed"
        )
        self.attempt = EmployeeAccessAttempt.create(
            id="request",
            employee_id=self.employee.id,
            controller_id=self.device.id,
            door_id="0",
            camera="gate",
            created_at=100,
        )
        app = FastAPI()
        app.frigate_config = SimpleNamespace(
            proxy=SimpleNamespace(separator=","),
            auth=SimpleNamespace(roles={"admin": [], "viewer": []}),
        )
        app.include_router(router)
        self.client = TestClient(app)
        self.headers = {"remote-user": "reviewer", "remote-role": "admin"}

    def restore_bindings(self):
        self.db.close()
        for model, database in self.original_databases.items():
            model.bind(database)

    def grant(self, event_id="event", machine_status="valid", **raw):
        return AccessEvent.create(
            id=event_id,
            device_id="controller",
            occurred_at=100,
            camera="gate",
            verification_status=machine_status,
            card_number=raw.get("card_number", "1200"),
            raw_record={
                "event_code": "AccessControl",
                "status": "OK",
                "timestamp": 100,
                "user_name": "Mohamed",
                "user_id": "1",
                "door_id": "0",
                "card_number": "1200",
                **raw,
            },
        )

    def list_reviews(self, **params):
        return self.client.get(
            "/access-controllers/events/review", headers=self.headers, params=params
        )

    def test_portal_identity_selected_door_and_no_card(self):
        EmployeeSource.create(
            id="source",
            controller_id="controller",
            user_id="1",
            employee_id=self.employee.id,
            name="Mohamed",
        )
        result = {"success": True, "door_command": "accepted"}
        event_id = _persist_portal_grant(
            self.employee, self.device, "2", "request", 200, result, 0.99
        )
        event = AccessEvent.get_by_id(event_id)
        serialized = serialize_access_event(event)
        self.assertEqual(serialized["user_id"], "1")
        self.assertEqual(serialized["user_name"], "Mohamed")
        self.assertEqual(serialized["door_id"], "2")
        self.assertEqual(serialized["timestamp"], 200)
        self.assertEqual(serialized["status"], "OK")
        self.assertEqual(serialized["type"], "Entry")
        self.assertEqual(serialized["verify_mode"], "Camera")
        self.assertIsNone(serialized["card_number"])
        self.assertIsNone(serialized["reader_id"])
        self.assertEqual(serialized["machine_status"], "pending")
        self.assertEqual(serialized["source"], "employee_portal")
        self.assertEqual(serialized["employee_id"], "local-id")
        self.assertEqual(EmployeeAccessAttempt.get_by_id("request").result, result)

    def test_portal_fallback_and_duplicate_request(self):
        first = _persist_portal_grant(
            self.employee, self.device, "0", "request", 200, {"success": True}, 0.99
        )
        second = _persist_portal_grant(
            self.employee, self.device, "0", "request", 201, {"success": True}, 0.99
        )
        self.assertEqual(first, second)
        self.assertEqual(AccessEvent.select().count(), 1)
        self.assertEqual(
            serialize_access_event(AccessEvent.get_by_id(first))["user_id"], "local-id"
        )
        self.assertEqual(AccessEvent.get_by_id(first).occurred_at, 200)
        for number in ("1", "2"):
            EmployeeSource.create(
                id=number,
                controller_id="controller",
                user_id=number,
                employee_id=self.employee.id,
                name="Mohamed",
            )
        self.attempt.id = "ambiguous"
        self.attempt.save(force_insert=True)
        third = _persist_portal_grant(
            self.employee, self.device, "0", "ambiguous", 202, {"success": True}, 0.99
        )
        self.assertEqual(
            serialize_access_event(AccessEvent.get_by_id(third))["user_id"], "local-id"
        )

    def test_missing_attempt_rolls_back_portal_event(self):
        with self.assertRaises(EmployeeAccessAttempt.DoesNotExist):
            _persist_portal_grant(
                self.employee, self.device, "0", "missing", 200, {"success": True}, 0.99
            )
        self.assertEqual(AccessEvent.select().count(), 0)

    def test_portal_uses_existing_classifier(self):
        event_id = _persist_portal_grant(
            self.employee, self.device, "0", "request", 200, {"success": True}, 0.99
        )
        for people, expected in (
            ([{"event_id": "person", "name": "Mohamed"}], "valid"),
            ([{"event_id": "person", "name": "Other"}], "warning"),
            ([], "unknown"),
        ):
            with (
                self.subTest(expected=expected),
                patch(
                    "frigate.access_controller_service.history_people",
                    return_value=people,
                ),
            ):
                _verify_event(event_id, now=1000)
                self.assertEqual(
                    AccessEvent.get_by_id(event_id).verification_status, expected
                )

    def test_confirmation_correction_history_and_classifier_retry(self):
        event = self.grant(_owner_names=["Mohamed"])
        submit_access_review(event.id, "first", "confirm", None, 0)
        submit_access_review(event.id, "second", "correct", "warning", 1)
        self.assertEqual(AccessEventReview.select().count(), 2)
        with patch("frigate.access_controller_service.history_people", return_value=[]):
            _verify_event(event.id, now=1000)
        data = serialize_access_event(AccessEvent.get_by_id(event.id))
        self.assertEqual(data["machine_status"], "unknown")
        self.assertEqual(data["effective_status"], "warning")
        self.assertTrue(data["reviewed"])
        self.assertEqual(data["reviewed_by"], "second")
        self.assertEqual(data["review_revision"], 2)
        history = self.client.get(
            f"/access-controllers/events/{event.id}/reviews", headers=self.headers
        ).json()
        self.assertEqual([item["action"] for item in history], ["correct", "confirm"])
        self.assertEqual(history[0]["previous_status"], "valid")

    def test_stale_revision_does_not_append_history(self):
        self.grant()
        submit_access_review("event", "first", "correct", "unknown", 0)
        with self.assertRaises(AccessReviewError) as failure:
            submit_access_review("event", "second", "correct", "warning", 0)
        self.assertEqual(failure.exception.reason, "review_conflict")
        self.assertEqual(AccessEventReview.select().count(), 1)

    def test_review_failure_rolls_back_status(self):
        self.grant()
        with (
            patch.object(
                AccessEventReview, "insert", side_effect=RuntimeError("audit failure")
            ),
            self.assertRaises(RuntimeError),
        ):
            submit_access_review("event", "reviewer", "confirm", None, 0)
        self.assertIsNone(AccessEvent.get_by_id("event").review_status)
        self.assertEqual(AccessEvent.get_by_id("event").review_revision, 0)

    def test_api_confirmation_validation_authorization_and_conflict(self):
        self.grant()
        path = "/access-controllers/events/event/review"
        body = {"action": "confirm", "expected_revision": 0}
        self.assertEqual(self.client.post(path, json=body).status_code, 403)
        self.assertEqual(
            self.client.post(
                path,
                json=body,
                headers={"remote-user": "viewer", "remote-role": "viewer"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                path, json=body, headers={"remote-role": "admin"}
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                path, json={**body, "reviewer": "spoofed"}, headers=self.headers
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                path,
                json={"action": "correct", "expected_revision": 0},
                headers=self.headers,
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                path,
                json={
                    "action": "correct",
                    "classification": "pending",
                    "expected_revision": 0,
                },
                headers=self.headers,
            ).status_code,
            422,
        )
        response = self.client.post(path, json=body, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reviewed_by"], "reviewer")
        self.assertEqual(
            self.client.post(path, json=body, headers=self.headers).status_code, 409
        )
        self.assertEqual(
            self.client.post(
                path.replace("event/review", "missing/review"),
                json=body,
                headers=self.headers,
            ).status_code,
            404,
        )

    def test_pending_denied_and_door_events_cannot_be_reviewed(self):
        for event in (
            self.grant("pending", "pending"),
            self.grant("denied", status="Failed"),
            self.grant("door", event_code="DoorOpen"),
        ):
            with self.subTest(event=event.id), self.assertRaises(AccessReviewError):
                submit_access_review(event.id, "reviewer", "confirm", None, 0)

    def test_counts_are_unpaginated_and_ignore_classification_only(self):
        for index in range(55):
            self.grant(str(index))
        self.grant("warning", "warning")
        self.grant("pending", "pending")
        self.grant("denied", status="Failed")
        self.grant("door", event_code="DoorOpen")
        submit_access_review("0", "reviewer", "correct", "unknown", 0)
        data = self.list_reviews(classification="valid").json()
        self.assertEqual(data["total"], 54)
        self.assertEqual(len(data["events"]), 50)
        self.assertEqual(
            data["counts"],
            {"valid": 54, "warning": 1, "unknown": 0, "pending": 1, "all": 56},
        )
        self.assertEqual(
            len(self.list_reviews(classification="valid", page=2).json()["events"]), 4
        )
        self.assertEqual(
            self.list_reviews(reviewed="reviewed").json()["counts"]["unknown"], 1
        )
        self.assertEqual(self.list_reviews(reviewed="all").json()["total"], 57)
        self.assertEqual(self.list_reviews(classification="pending").json()["total"], 1)

    def test_each_search_filter(self):
        self.grant()
        self.grant(
            "portal",
            "warning",
            _source="employee_portal",
            user_name="Alice",
            user_id="7",
            door_id="2",
            card_number=None,
        )
        for filters, expected in (
            ({"name": "moha"}, 1),
            ({"user_id": "1"}, 1),
            ({"card_no": "120"}, 1),
            ({"door_id": "0"}, 1),
            ({"camera": "gate"}, 2),
            ({"camera": "missing"}, 0),
            ({"device_id": "controller"}, 2),
            ({"device_id": "missing"}, 0),
            ({"source": "controller"}, 1),
            ({"source": "employee_portal"}, 1),
            ({"name": "%"}, 0),
            ({"name": "Alice", "door_id": "0"}, 0),
        ):
            with self.subTest(filters=filters):
                self.assertEqual(self.list_reviews(**filters).json()["total"], expected)

    def test_timezones_boundaries_and_bad_ranges(self):
        self.grant()
        bounds = {"start": "1970-01-01T01:01:40+01:00", "end": "1970-01-01T00:01:40Z"}
        self.assertEqual(self.list_reviews(**bounds).json()["total"], 1)
        self.assertEqual(
            self.list_reviews(start="1970-01-01T00:01:41Z").json()["total"], 0
        )
        self.assertEqual(
            self.list_reviews(start="1970-01-01T00:00:00").status_code, 400
        )
        self.assertEqual(
            self.list_reviews(
                start="1970-01-02T00:00:00Z", end="1970-01-01T00:00:00Z"
            ).status_code,
            400,
        )

    def test_existing_events_filters_and_array_response(self):
        self.grant()
        self.grant("denied", status="Failed", user_name="Other")
        for params, count in (
            ({"name": "Mohamed"}, 1),
            ({"user_id": "missing"}, 0),
            ({"card_no": "1200"}, 2),
            ({"status": "Failed"}, 1),
        ):
            response = self.client.get(
                "/access-controllers/events", headers=self.headers, params=params
            )
            self.assertIsInstance(response.json(), list)
            self.assertEqual(len(response.json()), count)

    def test_queued_database_transactions_and_persistence(self):
        self.db.close()
        queue = SqliteQueueDatabase(self.path)
        queue.bind(MODELS)
        try:
            event_id = _persist_portal_grant(
                self.employee, self.device, "0", "request", 200, {"success": True}, 0.99
            )
            AccessEvent.update(verification_status="valid").where(
                AccessEvent.id == event_id
            ).execute()
            submit_access_review(event_id, "reviewer", "correct", "warning", 0)
            self.assertEqual(AccessEvent.get_by_id(event_id).review_status, "warning")
            self.assertEqual(AccessEventReview.select().count(), 1)
        finally:
            queue.stop()
            queue.close()
            self.db.bind(MODELS)
        self.assertEqual(AccessEvent.get_by_id(event_id).review_status, "warning")

    def test_review_migration_preserves_old_events_and_rolls_back(self):
        legacy = SqliteExtDatabase(":memory:")
        legacy.execute_sql("CREATE TABLE access_event (id TEXT PRIMARY KEY)")
        legacy.execute_sql("INSERT INTO access_event (id) VALUES ('old')")
        migrator = SimpleNamespace(sql=legacy.execute_sql)
        migration = importlib.import_module("migrations.042_access_event_review")
        migration.migrate(migrator, legacy)
        self.assertEqual(
            legacy.execute_sql(
                "SELECT review_status, review_revision FROM access_event"
            ).fetchone(),
            (None, 0),
        )
        migration.rollback(migrator, legacy)
        self.assertEqual(
            legacy.execute_sql("SELECT id FROM access_event").fetchone(), ("old",)
        )
        legacy.close()

    def test_success_publishes_captures_and_retry_does_not_unlock_again(self):
        async def exercise():
            service = EmployeeService(
                SimpleNamespace(
                    config_holder=None,
                    frigate_config=SimpleNamespace(
                        cameras={
                            "gate": SimpleNamespace(objects=SimpleNamespace(filters={}))
                        },
                        face_recognition=SimpleNamespace(recognition_threshold=0.8),
                    ),
                )
            )
            self.addCleanup(service.executor.shutdown, wait=True)
            service.detector = Mock()
            service.detector.detect.return_value = [(0, 0, 10, 10)]
            service.authorize = AsyncMock(
                return_value=(self.employee, self.device, 1, "signature")
            )
            service.snapshot = Mock(return_value=(Mock(), time.time()))
            service.person_image = Mock(return_value="image")
            controller = SimpleNamespace(
                get_doors_async=AsyncMock(return_value=[{"id": "0", "name": "Door 1"}]),
                open_door_async=AsyncMock(return_value={"accepted": True}),
            )
            EmployeeAccessAttempt.delete().execute()
            with (
                patch(
                    "frigate.employee_service.build_controller", return_value=controller
                ),
                patch(
                    "frigate.employee_service.embedding_request",
                    return_value={"success": True, "score": 0.99},
                ),
                patch(
                    "frigate.access_controller_service._enrich_live_scan",
                    new_callable=AsyncMock,
                ) as capture,
                patch(
                    "frigate.access_controller_service._publisher",
                ) as publisher,
            ):
                first = await service.verify(
                    self.employee, "gate", "controller", "0", "request"
                )
                await asyncio.sleep(0)
                second = await service.verify(
                    self.employee, "gate", "controller", "0", "request"
                )
                self.assertTrue(first["success"])
                self.assertEqual(first, second)
                controller.open_door_async.assert_awaited_once()
                capture.assert_awaited_once()
                self.assertEqual(AccessEvent.select().count(), 1)
                self.assertEqual(publisher.call_args[0][0], "access_controller_events")
                self.assertEqual(
                    json.loads(publisher.call_args[0][1])["source"], "employee_portal"
                )

        asyncio.run(exercise())

    def test_failed_and_uncertain_unlocks_never_create_grants(self):
        async def exercise():
            service = EmployeeService(
                SimpleNamespace(
                    config_holder=None,
                    frigate_config=SimpleNamespace(
                        cameras={
                            "gate": SimpleNamespace(objects=SimpleNamespace(filters={}))
                        },
                        face_recognition=SimpleNamespace(recognition_threshold=0.8),
                    ),
                )
            )
            self.addCleanup(service.executor.shutdown, wait=True)
            service.detector = Mock()
            service.detector.detect.return_value = [(0, 0, 10, 10)]
            service.authorize = AsyncMock(
                return_value=(self.employee, self.device, 1, "signature")
            )
            service.snapshot = Mock(return_value=(Mock(), time.time()))
            service.person_image = Mock(return_value="image")
            controller = SimpleNamespace(
                get_doors_async=AsyncMock(return_value=[{"id": "0"}])
            )
            for index, outcome in enumerate(({"accepted": False}, TimeoutError())):
                controller.open_door_async = AsyncMock(
                    return_value=outcome if isinstance(outcome, dict) else None,
                    side_effect=outcome if isinstance(outcome, Exception) else None,
                )
                with (
                    patch(
                        "frigate.employee_service.build_controller",
                        return_value=controller,
                    ),
                    patch(
                        "frigate.employee_service.embedding_request",
                        return_value={"success": True, "score": 0.99},
                    ),
                ):
                    result = await service.verify(
                        self.employee, "gate", "controller", "0", f"failed-{index}"
                    )
                    self.assertFalse(result["success"])
                    self.assertEqual(AccessEvent.select().count(), 0)

        asyncio.run(exercise())
