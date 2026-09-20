import os
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from frigate.models import Employee, Group
from frigate.test.http_api.base_http_test import AuthTestClient, BaseTestHttp


class TestHttpOrganization(BaseTestHttp):
    def setUp(self):
        super().setUp([Group, Employee])
        self.app = super().create_app()
        self.face_dir = tempfile.TemporaryDirectory()
        face_patch = patch("frigate.api.organization.FACE_DIR", self.face_dir.name)
        face_patch.start()
        self.addCleanup(face_patch.stop)
        self.addCleanup(self.face_dir.cleanup)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        super().tearDown()

    def test_admin_only_endpoints_reject_anonymous_requests(self):
        with TestClient(self.app) as client:
            response = client.get("/groups")

        assert response.status_code == 403

    def test_group_and_employee_crud(self):
        with AuthTestClient(self.app) as client:
            response = client.post(
                "/groups",
                json={"id": "ops", "group_name": "Operations"},
            )
            assert response.status_code == 200

            response = client.post(
                "/employees",
                json={
                    "id": "emp_1",
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                    "group_id": "ops",
                },
            )
            assert response.status_code == 200
            assert os.path.isdir(os.path.join(self.face_dir.name, "emp_1"))

            response = client.get("/employees")
            assert response.status_code == 200
            assert response.json() == [
                {
                    "id": "emp_1",
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                    "group_id": "ops",
                    "group_name": "Operations",
                }
            ]

            response = client.put(
                "/employees/emp_1",
                json={
                    "first_name": "Grace",
                    "last_name": "Hopper",
                    "group_id": "ops",
                },
            )
            assert response.status_code == 200

            response = client.put(
                "/groups/ops",
                json={"group_name": "Security"},
            )
            assert response.status_code == 200

            response = client.get("/employees")
            assert response.status_code == 200
            assert response.json() == [
                {
                    "id": "emp_1",
                    "first_name": "Grace",
                    "last_name": "Hopper",
                    "group_id": "ops",
                    "group_name": "Security",
                }
            ]

            response = client.delete("/groups/ops")
            assert response.status_code == 400

            response = client.delete("/employees/emp_1")
            assert response.status_code == 200
            assert not os.path.exists(os.path.join(self.face_dir.name, "emp_1"))

            response = client.delete("/groups/ops")
            assert response.status_code == 200
