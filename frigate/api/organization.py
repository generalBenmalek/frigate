"""Employee and group management APIs."""

import logging
import os
import shutil

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from frigate.api.auth import require_role
from frigate.api.defs.request.organization_body import (
    EmployeeBody,
    EmployeeUpdateBody,
    GroupBody,
    GroupUpdateBody,
)
from frigate.api.defs.response.generic_response import GenericResponse
from frigate.api.defs.tags import Tags
from frigate.const import FACE_DIR
from frigate.models import Employee, Group
from frigate.util.path import safe_join, sanitize_path_component

logger = logging.getLogger(__name__)

router = APIRouter(tags=[Tags.organization])


def _success(message: str) -> JSONResponse:
    return JSONResponse(content={"success": True, "message": message}, status_code=200)


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(content={"success": False, "message": message}, status_code=status_code)


def _validate_identifier(identifier: str, label: str) -> str | None:
    sanitized = sanitize_path_component(identifier)
    if sanitized is None:
        logger.warning("Invalid %s provided: %s", label, identifier)
    return sanitized


def _employee_face_folder(employee_id: str) -> str | None:
    sanitized = _validate_identifier(employee_id, "employee id")
    if sanitized is None:
        return None

    return safe_join(FACE_DIR, sanitized)


def _serialize_group(group: Group) -> dict[str, str]:
    return {"id": group.id, "group_name": group.group_name}


def _serialize_employee(employee: Employee) -> dict[str, str]:
    group = employee.group
    return {
        "id": employee.id,
        "first_name": employee.first_name,
        "last_name": employee.last_name,
        "group_id": employee.group_id,
        "group_name": group.group_name if group else "",
    }


@router.get("/groups", dependencies=[Depends(require_role(["admin"]))])
def get_groups():
    groups = Group.select().order_by(Group.group_name, Group.id)
    return JSONResponse(content=[_serialize_group(group) for group in groups])


@router.post(
    "/groups",
    response_model=GenericResponse,
    dependencies=[Depends(require_role(["admin"]))],
)
def create_group(body: GroupBody):
    if _validate_identifier(body.id, "group id") is None:
        return _error("Invalid group id.", 400)

    if Group.select().where(Group.id == body.id).exists():
        return _error(f"Group {body.id} already exists.", 409)

    Group.create(id=body.id, group_name=body.group_name)
    return _success("Successfully created group.")


@router.put(
    "/groups/{group_id}",
    response_model=GenericResponse,
    dependencies=[Depends(require_role(["admin"]))],
)
def update_group(group_id: str, body: GroupUpdateBody):
    if Group.update(group_name=body.group_name).where(Group.id == group_id).execute() == 0:
        return _error(f"Group {group_id} not found.", 404)

    return _success("Successfully updated group.")


@router.delete(
    "/groups/{group_id}",
    response_model=GenericResponse,
    dependencies=[Depends(require_role(["admin"]))],
)
def delete_group(group_id: str):
    if Employee.select().where(Employee.group_id == group_id).exists():
        return _error(
            f"Group {group_id} still has employees assigned to it.", 400
        )

    if Group.delete().where(Group.id == group_id).execute() == 0:
        return _error(f"Group {group_id} not found.", 404)

    return _success("Successfully deleted group.")


@router.get("/employees", dependencies=[Depends(require_role(["admin"]))])
def get_employees():
    employees = (
        Employee.select(Employee, Group).join(Group).order_by(Employee.last_name, Employee.first_name, Employee.id)
    )
    return JSONResponse(content=[_serialize_employee(employee) for employee in employees])


@router.post(
    "/employees",
    response_model=GenericResponse,
    dependencies=[Depends(require_role(["admin"]))],
)
def create_employee(body: EmployeeBody):
    if _validate_identifier(body.id, "employee id") is None:
        return _error("Invalid employee id.", 400)

    if Employee.select().where(Employee.id == body.id).exists():
        return _error(f"Employee {body.id} already exists.", 409)

    group = Group.get_or_none(Group.id == body.group_id)
    if group is None:
        return _error(f"Group {body.group_id} not found.", 404)

    Employee.create(
        id=body.id,
        first_name=body.first_name,
        last_name=body.last_name,
        group=group.id,
    )

    face_folder = _employee_face_folder(body.id)
    if face_folder is None:
        Employee.delete().where(Employee.id == body.id).execute()
        return _error("Invalid employee id.", 400)

    try:
        os.makedirs(face_folder, exist_ok=True)
    except OSError:
        Employee.delete().where(Employee.id == body.id).execute()
        return _error("Unable to create face record for this employee.", 500)

    return _success("Successfully created employee.")


@router.put(
    "/employees/{employee_id}",
    response_model=GenericResponse,
    dependencies=[Depends(require_role(["admin"]))],
)
def update_employee(employee_id: str, body: EmployeeUpdateBody):
    employee = Employee.get_or_none(Employee.id == employee_id)
    if employee is None:
        return _error(f"Employee {employee_id} not found.", 404)

    group = Group.get_or_none(Group.id == body.group_id)
    if group is None:
        return _error(f"Group {body.group_id} not found.", 404)

    if (
        Employee.update(
            first_name=body.first_name,
            last_name=body.last_name,
            group=group.id,
        )
        .where(Employee.id == employee_id)
        .execute()
        == 0
    ):
        return _error(f"Employee {employee_id} not found.", 404)

    return _success("Successfully updated employee.")


@router.delete(
    "/employees/{employee_id}",
    response_model=GenericResponse,
    dependencies=[Depends(require_role(["admin"]))],
)
def delete_employee(employee_id: str):
    face_folder = _employee_face_folder(employee_id)
    if face_folder and os.path.isdir(face_folder):
        try:
            shutil.rmtree(face_folder)
        except OSError:
            return _error("Unable to delete employee face record.", 500)

    if Employee.delete().where(Employee.id == employee_id).execute() == 0:
        return _error(f"Employee {employee_id} not found.", 404)

    return _success("Successfully deleted employee.")
