import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import requests
from fastapi.testclient import TestClient

from frigate.access_controller_service import (
    _access_granted_card_scan,
    _store_live_event,
    _store_record,
    poll_controller,
    verify_pending_events,
)
from frigate.models import (
    AccessControl,
    AccessEvent,
    Event,
    Recordings,
)
from frigate.test.http_api.base_http_test import AuthTestClient, BaseTestHttp


class TestHttpAccessController(BaseTestHttp):
    def setUp(self):
        super().setUp([AccessControl, AccessEvent, Event, Recordings])
        self.app = self.create_app()

    def tearDown(self):
        self.app.dependency_overrides.clear()
        super().tearDown()

    def test_admin_only_endpoints_reject_anonymous_requests(self):
        with TestClient(self.app) as client:
            response = client.get("/access-controllers")

        assert response.status_code == 403

    def test_access_controller_crud_and_event_history(self):
        with AuthTestClient(self.app) as client:
            with patch(
                "frigate.access_controller_service.DahuaAccessController.get_system_info",
                return_value={
                    "deviceName": "Door-1",
                    "deviceType": "Dahua",
                    "serialNumber": "AC-001",
                    "channelNumber": "2",
                },
            ):
                response = client.post(
                    "/access-controllers",
                    json={
                        "id": "ac_1",
                        "name": "Door 1",
                        "username": "admin",
                        "password": "secret",
                        "ip_address": "127.0.0.1",
                        "port": 80,
                        "associated_camera": "front_door",
                    },
                )
                assert response.status_code == 200
                body = response.json()
                assert body["id"] == "ac_1"
                assert body["name"] == "Door-1"
                assert body["status"] == "online"
                assert body["associated_camera"] == "front_door"

            response = client.get("/access-controllers")
            assert response.status_code == 200
            assert response.json()[0]["id"] == "ac_1"

            with patch(
                "frigate.access_controller_service.DahuaAccessController.get_system_info",
                side_effect=requests.ConnectionError("offline"),
            ):
                response = client.put(
                    "/access-controllers/ac_1",
                    json={
                        "ip_address": "10.0.0.2",
                        "port": 81,
                        "username": "",
                        "password": "",
                        "associated_camera": "garage",
                    },
                )
            assert response.status_code == 200
            result = response.json()
            assert result["ip_address"] == "10.0.0.2"
            assert result["port"] == 81
            assert result["associated_camera"] == "garage"

            with patch(
                "frigate.access_controller_service.DahuaAccessController.get_system_info",
                side_effect=requests.ConnectionError("offline"),
            ):
                response = client.put(
                    "/access-controllers/ac_1",
                    json={"associated_camera": None},
                )
            assert response.status_code == 200
            assert response.json()["associated_camera"] is None

            AccessEvent.create(
                id="access-event-1",
                device_id="ac_1",
                occurred_at=time.time() - 1,
                card_number="123",
                raw_record={"CardNo": "123", "EventType": "AccessGranted"},
                verification_status="unverified",
                people=[],
                camera="front_door",
            )
            response = client.get("/access-controllers/events?device_id=ac_1")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["device_id"] == "ac_1"
            assert data[0]["EventType"] == "AccessGranted"

            response = client.delete("/access-controllers/ac_1")
            assert response.status_code == 200

    def test_retry_reports_offline_when_probe_fails(self):
        with AuthTestClient(self.app) as client:
            with patch(
                "frigate.access_controller_service.DahuaAccessController.get_system_info",
                return_value={"deviceName": "Door-1"},
            ):
                client.post(
                    "/access-controllers",
                    json={"id": "ac_1", "ip_address": "127.0.0.1"},
                )
            with patch(
                "frigate.access_controller_service.DahuaAccessController.get_system_info",
                side_effect=requests.ConnectionError("offline"),
            ):
                response = client.post("/access-controllers/ac_1/refresh")

        assert response.status_code == 200
        assert response.json()["status"] == "offline"
        assert response.json()["last_checked_at"] is not None

    def test_granted_card_records_use_controller_names(self):
        scan_time = int(time.time()) - 1
        AccessControl.create(
            id="ac_1",
            name="Door 1",
            ip_address="127.0.0.1",
            type="Dahua",
            model="Unknown",
            port=80,
            channel_count=1,
            serial_number="",
            username="",
            password="",
            event_tracking_started_at=scan_time - 1,
        )
        records = [
            {
                "CreateTime": str(scan_time),
                "CardNo": "123",
                "CardName": "Alice",
                "Status": "1",
                "Method": "2",
            },
            {
                "CreateTime": str(scan_time),
                "CardNo": "456",
                "CardName": "Bob",
                "Status": "0",
                "Method": "2",
            },
        ]
        with (
            patch(
                "frigate.access_controller_service.DahuaAccessController.get_system_info",
                return_value={"deviceName": "Door 1"},
            ),
            patch(
                "frigate.access_controller_service.DahuaAccessController.get_access_records",
                return_value=records,
            ),
            patch(
                "frigate.access_controller_service.DahuaAccessController.get_card_owners",
                return_value=["Alice", "Alex"],
            ) as card_owners,
        ):
            poll_controller("ac_1")

        assert card_owners.call_count == 1
        granted = AccessEvent.get(AccessEvent.card_number == "123")
        assert granted.verification_status == "pending"
        assert granted.raw_record["_owner_names"] == ["Alice", "Alex"]
        assert granted.raw_record["_owner_names_complete"] is True
        assert (
            AccessEvent.get(AccessEvent.card_number == "456").verification_status
            == "unverified"
        )

    def test_live_and_history_merge_without_resetting_verification(self):
        device = AccessControl.create(
            id="ac_1", name="Door 1", ip_address="127.0.0.1", type="Dahua",
            model="ASI", serial_number="", username="", password="",
            event_tracking_started_at=1790665388,
        )
        data = {"CreateTime": 1790665389, "Door": 0, "ReaderID": "1",
                "CardNo": "000ABC", "CardName": "Alice", "UserID": "001",
                "Status": 1, "Method": 11, "ErrorCode": 0, "Type": "Entry"}
        _store_live_event(device.id, {"code": "AccessControl", "data": data})
        event = AccessEvent.get()
        original_id = event.id
        event.verification_status = "valid"
        event.save()
        history = {key: str(value) for key, value in data.items()}
        _store_record(device, {**history, "RecNo": "42"}, ["Alice"], True)
        self.assertEqual(AccessEvent.select().count(), 1)
        event = AccessEvent.get()
        self.assertEqual(event.id, original_id)
        self.assertEqual(event.verification_status, "valid")
        self.assertEqual(event.raw_record["record_number"], "42")
        _store_record(device, {**history, "RecNo": "42", "CardName": ""}, [], False)
        event = AccessEvent.get()
        self.assertEqual(event.raw_record["user_name"], "Alice")
        self.assertEqual(event.verification_status, "valid")
        _store_record(device, {**history, "RecNo": "43"}, ["Alice"], True)
        self.assertEqual(AccessEvent.select().count(), 2)

    def test_non_access_events_do_not_create_attendance_rows(self):
        device = AccessControl.create(
            id="ac_1", name="Door 1", ip_address="127.0.0.1", type="Dahua",
            model="ASI", serial_number="", username="", password="",
        )
        _store_live_event(device.id, {"code": "DoorStatus", "data": {"Status": "Open", "UTC": 1790665389}})
        self.assertEqual(AccessEvent.select().count(), 0)

    def test_card_methods_include_multicard_and_exclude_fingerprint(self):
        row = {"CardNo": "000ABC", "Status": 1, "ErrorCode": 0}
        for method in (2, 10, 11):
            self.assertTrue(_access_granted_card_scan({**row, "Method": method}))
        self.assertFalse(_access_granted_card_scan({**row, "Method": 1}))
        self.assertFalse(_access_granted_card_scan({**row, "Method": 11, "ErrorCode": 16}))

    def test_history_filters_before_limit_and_includes_older_records(self):
        for index, name in enumerate(("Alice", "Bob", "Charlie")):
            AccessEvent.create(
                id=f"event-{index}", device_id="ac_1", occurred_at=1000 + index,
                card_number=f"000{index}", raw_record={"CardName": name, "UserID": "0", "Status": "1"},
            )
        with AuthTestClient(self.app) as client:
            response = client.get("/access-controllers/events?name=AL&user_id=0&status=OK&count=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([event["user_name"] for event in response.json()], ["Alice"])

    def test_history_sync_preserves_ui_timezone_for_cgi_search(self):
        with AuthTestClient(self.app) as client:
            with patch("frigate.api.access_controller.synchronize_controller_history", new=AsyncMock(return_value=[])) as sync:
                response = client.post("/access-controllers/events/sync", json={
                    "start": "2026-09-29T08:00:00Z", "timezone": "Africa/Algiers",
                })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sync.call_args.args[1].hour, 9)
        self.assertEqual(sync.call_args.args[1].timestamp(), 1790668800)

    def test_card_verification_uses_all_people_in_window(self):
        scan_time = time.time() - 30
        AccessEvent.create(
            id="scan-1",
            device_id="ac_1",
            occurred_at=scan_time,
            card_number="123",
            raw_record={"CardNo": "123", "_owner_names": ["Alice"]},
            verification_status="pending",
            people=[],
            camera="front_door",
        )
        self.insert_mock_event("person-1", scan_time - 2, scan_time + 2)
        Event.update(label="person", sub_label="Alice").where(
            Event.id == "person-1"
        ).execute()
        self.insert_mock_recording("recording-1", scan_time - 15, scan_time + 15)

        with tempfile.TemporaryDirectory() as face_dir:
            (Path(face_dir) / "Alice").mkdir()
            with patch("frigate.access_controller_service.FACE_DIR", face_dir):
                verify_pending_events()
                result = AccessEvent.get_by_id("scan-1")
                assert result.verification_status == "valid"
                assert [person["name"] for person in result.people] == ["Alice"]

                self.insert_mock_event("person-2", scan_time - 1, scan_time + 3)
                Event.update(label="person", sub_label="Bob").where(
                    Event.id == "person-2"
                ).execute()
                result.verification_status = "pending"
                result.save()
                verify_pending_events()
                assert AccessEvent.get_by_id("scan-1").verification_status == "warning"

                (Path(face_dir) / "Alice").rmdir()
                result.verification_status = "pending"
                result.save()
                verify_pending_events()
                assert AccessEvent.get_by_id("scan-1").verification_status == "unknown"
