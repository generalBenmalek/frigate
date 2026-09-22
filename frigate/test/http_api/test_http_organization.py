from unittest.mock import patch

from fastapi.testclient import TestClient

from frigate.models import AccessControl
from frigate.test.http_api.base_http_test import AuthTestClient, BaseTestHttp


class TestHttpAccessController(BaseTestHttp):
    def setUp(self):
        super().setUp([AccessControl])
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
                "frigate.api.access_controller.DahuaAccessController.get_system_info",
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
                    },
                )
                assert response.status_code == 200
                body = response.json()
                assert body["id"] == "ac_1"
                assert body["name"] == "Door-1"
                assert body["status"] == "online"

            response = client.get("/access-controllers")
            assert response.status_code == 200
            assert response.json()[0]["id"] == "ac_1"

            response = client.put(
                "/access-controllers/ac_1",
                json={
                    "ip_address": "10.0.0.2",
                    "port": 81,
                    "username": "",
                    "password": "",
                },
            )
            assert response.status_code == 200
            result = response.json()
            assert result["ip_address"] == "10.0.0.2"
            assert result["port"] == 81

            with patch(
                "frigate.api.access_controller.DahuaAccessController.get_access_records",
                return_value=[
                    {
                        "Time": "2024-01-01 12:00:00",
                        "CardNo": "123",
                        "EventType": "AccessGranted",
                    }
                ],
            ):
                response = client.get("/access-controllers/events?device_id=ac_1")
                assert response.status_code == 200
                data = response.json()
                assert len(data) == 1
                assert data[0]["device_id"] == "ac_1"
                assert data[0]["EventType"] == "AccessGranted"

            response = client.delete("/access-controllers/ac_1")
            assert response.status_code == 200
