import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import requests
from fastapi.testclient import TestClient

from frigate.access_controller_service import verify_pending_events
from frigate.models import (
    AccessCardOwner,
    AccessControl,
    AccessEvent,
    Event,
    Recordings,
)
from frigate.test.http_api.base_http_test import AuthTestClient, BaseTestHttp


class TestHttpAccessController(BaseTestHttp):
    def setUp(self):
        super().setUp([AccessControl, AccessCardOwner, AccessEvent, Event, Recordings])
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

    def test_card_verification_uses_all_people_in_window(self):
        scan_time = time.time() - 30
        AccessEvent.create(
            id="scan-1",
            device_id="ac_1",
            occurred_at=scan_time,
            card_number="123",
            raw_record={"CardNo": "123"},
            verification_status="pending",
            people=[],
            camera="front_door",
        )
        AccessCardOwner.create(device_id="ac_1", card_number="123", face_name="Alice")
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
