"""All-door portal privileges preserve enrollment and safety checks."""

import asyncio
import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from playhouse.sqlite_ext import SqliteExtDatabase
from pydantic import ValidationError

from frigate.api.employee_portal import employee_error, employee_options
from frigate.api.employees import EmployeeBody, create_employee, router, update_employee
from frigate.employee_service import (
    EmployeeAccessError,
    EmployeeService,
    employee_doors,
    serialize_employee,
)
from frigate.models import (
    AccessControl,
    Employee,
    EmployeeAccessSettings,
    EmployeeDoorOverride,
    EmployeeSource,
)

MODELS = (
    AccessControl,
    Employee,
    EmployeeAccessSettings,
    EmployeeDoorOverride,
    EmployeeSource,
)


class TestSuperEmployee(unittest.TestCase):
    def test_only_admin_can_change_super_employee(self):
        app = FastAPI()
        app.frigate_config = SimpleNamespace(
            proxy=SimpleNamespace(separator=","),
            auth=SimpleNamespace(roles={"admin": [], "viewer": []}),
        )
        app.employee_service = self.service
        app.add_exception_handler(EmployeeAccessError, employee_error)
        app.include_router(router)
        body = {"name": "Mohamed", "username": "mohamed", "super_employee": True}
        with TestClient(app) as client:
            for headers in ({}, {"remote-role": "viewer"}):
                self.assertEqual(
                    client.put(
                        "/employees/employee",
                        json=body,
                        headers=headers,
                    ).status_code,
                    403,
                )
            self.assertEqual(
                client.put(
                    "/employees/employee",
                    json=body,
                    headers={"remote-role": "admin", "origin": "http://testserver"},
                ).status_code,
                403,
            )
            response = client.put(
                "/employees/employee",
                json=body,
                headers={
                    "remote-role": "admin",
                    "origin": "http://testserver",
                    "x-csrf-token": "token",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["super_employee"])
        with self.assertRaises(EmployeeAccessError):
            self.authorize()
        self.assertTrue(self.authorize(version=1)[0].super_employee)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = SqliteExtDatabase(str(Path(directory.name) / "employees.db"))
        self.original = {model: model._meta.database for model in MODELS}
        self.db.bind(MODELS)
        self.db.create_tables(MODELS)
        self.addCleanup(self.restore_bindings)
        camera = SimpleNamespace(
            enabled=True,
            detect=SimpleNamespace(enabled=True),
            face_recognition=SimpleNamespace(enabled=True),
        )
        self.config = SimpleNamespace(
            cameras={"gate": camera},
            face_recognition=SimpleNamespace(enabled=True),
        )
        self.service = EmployeeService(
            SimpleNamespace(
                config_holder=None,
                frigate_config=self.config,
            )
        )
        self.addCleanup(self.service.executor.shutdown)
        EmployeeAccessSettings.create(id=1, enabled=True)
        self.employee = Employee.create(
            id="employee",
            name="Mohamed",
            username="mohamed",
            name_key="mohamed",
            face_name="Mohamed",
        )
        for controller in ("entry", "exit"):
            AccessControl.create(
                id=controller,
                name=controller,
                ip_address="127.0.0.1",
                type="Dahua",
                model="test",
                serial_number="",
                username="",
                password="",
                associated_camera="gate",
            )
        signature = patch(
            "frigate.employee_service.face_signature", return_value="face"
        )
        signature.start()
        self.addCleanup(signature.stop)

    def restore_bindings(self):
        self.db.close()
        for model, database in self.original.items():
            model._meta.set_database(database)

    def authorize(self, controller="entry", door="0", version=0, camera="gate"):
        return asyncio.run(
            self.service.authorize(
                self.employee.id,
                version,
                camera,
                controller,
                door,
            )
        )

    def test_super_grants_every_controller_without_assignments(self):
        self.employee.super_employee = True
        self.employee.save()
        for controller in ("entry", "exit"):
            for door in ("0", "1", "2"):
                self.assertEqual(self.authorize(controller, door)[0].id, "employee")
        self.assertEqual(employee_doors("employee", "entry"), [])

    def test_regular_employee_requires_assignment_and_revocation_preserves_it(self):
        with self.assertRaises(EmployeeAccessError):
            self.authorize()
        EmployeeDoorOverride.create(
            employee_id="employee",
            controller_id="entry",
            doors=["0"],
        )
        self.authorize()
        with self.assertRaises(EmployeeAccessError):
            self.authorize(door="1")
        self.employee.super_employee = True
        self.employee.save()
        self.authorize(door="1")
        self.employee.super_employee = False
        self.employee.save()
        self.assertEqual(employee_doors("employee", "entry"), ["0"])
        with self.assertRaises(EmployeeAccessError):
            self.authorize(door="1")

    def test_super_does_not_bypass_safety_checks(self):
        self.employee.super_employee = True
        self.employee.save()
        for target in ("missing",):
            with self.assertRaises(EmployeeAccessError):
                self.authorize(controller=target)
        with self.assertRaises(EmployeeAccessError):
            self.authorize(camera="other")
        with self.assertRaises(EmployeeAccessError):
            self.authorize(version=1)
        self.employee.enabled = False
        self.employee.save()
        with self.assertRaises(EmployeeAccessError):
            self.authorize()
        self.employee.enabled = True
        self.employee.save()
        EmployeeAccessSettings.update(enabled=False).execute()
        with self.assertRaises(EmployeeAccessError):
            self.authorize()
        EmployeeAccessSettings.update(enabled=True).execute()
        with (
            patch("frigate.employee_service.face_signature", return_value=None),
            self.assertRaises(EmployeeAccessError),
        ):
            self.authorize()
        self.config.face_recognition.enabled = False
        with self.assertRaises(EmployeeAccessError):
            self.authorize()

    def options(self):
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(employee_service=self.service),
            )
        )
        controller = SimpleNamespace(
            get_doors_async=AsyncMock(
                return_value=[
                    {"id": 0, "name": "Door 1"},
                    {"id": 1, "name": "Door 2"},
                ]
            )
        )
        with patch(
            "frigate.api.employee_portal.build_controller", return_value=controller
        ):
            return asyncio.run(employee_options(request, self.employee))

    def test_portal_lists_all_discovered_doors_and_future_controllers(self):
        self.assertEqual(self.options(), [])
        self.employee.super_employee = True
        self.employee.save()
        self.assertEqual(len(self.options()), 2)
        for option in self.options():
            self.assertEqual([door["id"] for door in option["doors"]], ["0", "1"])
        AccessControl.create(
            id="new",
            name="New gate",
            ip_address="127.0.0.1",
            type="Dahua",
            model="test",
            serial_number="",
            username="",
            password="",
            associated_camera="gate",
        )
        self.assertEqual(len(self.options()), 3)
        self.config.cameras["gate"].enabled = False
        self.assertEqual(self.options(), [])

    def test_portal_regular_employee_only_sees_assigned_doors(self):
        EmployeeDoorOverride.create(
            employee_id="employee",
            controller_id="entry",
            doors=["1"],
        )
        options = self.options()
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["doors"], [{"id": "1", "name": "Door 2"}])

    def test_admin_create_update_and_omitted_flag_preserve_privilege(self):
        request = SimpleNamespace(app=SimpleNamespace(employee_service=self.service))
        with (
            patch(
                "frigate.api.employees.new_password", new=AsyncMock(return_value=None)
            ),
            patch(
                "frigate.api.employees.face_signature",
                return_value="face",
            ),
        ):
            created = asyncio.run(
                create_employee(
                    request,
                    EmployeeBody(
                        name="Sara",
                        username="sara",
                        super_employee=True,
                    ),
                )
            )
            self.assertTrue(created["super_employee"])
            result = asyncio.run(
                update_employee(
                    request,
                    created["id"],
                    EmployeeBody(
                        name="Sara",
                        username="sara",
                    ),
                )
            )
            self.assertTrue(result["super_employee"])
            self.assertEqual(Employee.get_by_id(created["id"]).auth_version, 1)
            result = asyncio.run(
                update_employee(
                    request,
                    created["id"],
                    EmployeeBody(
                        name="Sara",
                        username="sara",
                        super_employee=False,
                    ),
                )
            )
            self.assertFalse(result["super_employee"])
            self.assertEqual(Employee.get_by_id(created["id"]).auth_version, 2)

    def test_default_false_serialization_and_strict_boolean(self):
        self.assertFalse(serialize_employee(self.employee)["super_employee"])
        self.assertFalse(EmployeeBody(name="Sara").super_employee)
        for value in ("true", 1, None):
            with self.assertRaises(ValidationError):
                EmployeeBody(name="Sara", super_employee=value)

    def test_migration_existing_employees_default_false_and_rollback(self):
        self.db.execute_sql("CREATE TABLE legacy_employee (id TEXT PRIMARY KEY)")
        self.db.execute_sql("INSERT INTO legacy_employee VALUES ('existing')")
        migration = importlib.import_module("migrations.043_super_employee")
        migrator = Mock()
        migrator.sql.side_effect = lambda sql: self.db.execute_sql(
            sql.replace("TABLE employee ", "TABLE legacy_employee "),
        )
        migration.migrate(migrator, self.db)
        self.assertEqual(
            self.db.execute_sql(
                "SELECT super_employee FROM legacy_employee",
            ).fetchone()[0],
            0,
        )
        migration.rollback(migrator, self.db)
        self.assertEqual(
            self.db.execute_sql(
                "SELECT * FROM legacy_employee",
            ).fetchone(),
            ("existing",),
        )
