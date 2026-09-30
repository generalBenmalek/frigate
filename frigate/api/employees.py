"""Administrator-only local employee management APIs."""

import asyncio
import base64
import logging
from pathlib import Path
from uuid import uuid4

import regex
from fastapi import APIRouter, Depends, Request, Response, UploadFile
from peewee import IntegrityError
from pydantic import BaseModel, ConfigDict, Field

from frigate.api.auth import hash_password, require_role, validate_password_strength
from frigate.const import FACE_DIR
from frigate.dahua_adapter import DahuaOperationError
from frigate.employee_service import (
    UPLOAD_LIMIT, EmployeeAccessError, embedding_request, face_signature,
    serialize_employee,
)
from frigate.models import (
    AccessControl, Employee, EmployeeAccessAttempt, EmployeeAccessSettings,
    EmployeeControllerSync, EmployeeDoorOverride, EmployeeSource,
)
from frigate.access_controller_service import build_controller
from frigate.util.path import safe_join, sanitize_path_component

logger = logging.getLogger(__name__)


async def rename_face_library(request: Request, old_name: str, new_name: str) -> None:
    """Reuse face renaming without sharing the main thread's ZMQ socket."""
    await asyncio.to_thread(request.app.embeddings.rename_face, old_name, new_name, False)
    try:
        await asyncio.to_thread(embedding_request, "clear_face_classifier", {}, 3)
    except EmployeeAccessError:
        # The on-disk rename already succeeded. Employee verification checks
        # enrollment signatures independently of the all-label classifier.
        logger.warning("Face rename completed but classifier notification timed out")


def check_admin_employee_csrf(request: Request) -> None:
    """Apply Frigate's custom CSRF header requirement to employee mutations."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin is not None and "x-csrf-token" not in request.headers:
        raise EmployeeAccessError("invalid_csrf", 403)


def employee_admin_response_headers(response: Response) -> None:
    """Keep account, permission, and audit responses out of proxy caches."""
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(tags=["Employees"], dependencies=[
    Depends(require_role(["admin"])), Depends(check_admin_employee_csrf),
    Depends(employee_admin_response_headers),
])


class EmployeeBody(BaseModel):
    """Account details; passwords are accepted only when being changed."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=50)
    username: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, max_length=1024)
    enabled: bool = True


class EmployeePasswordBody(BaseModel):
    """An administrator-assigned password."""

    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=12, max_length=1024)


class EmployeeEnabledBody(BaseModel):
    """An explicit enable or disable operation."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool


class EmployeeDoorsBody(BaseModel):
    """A local replacement for imported door permissions."""

    model_config = ConfigDict(extra="forbid")
    doors: list[str] = Field(max_length=256)


class EmployeeFaceBody(BaseModel):
    """An existing face, explicitly renamed when its label differs."""

    model_config = ConfigDict(extra="forbid")
    face_name: str = Field(min_length=1, max_length=50)
    rename: bool = False


class EmployeeLinkBody(BaseModel):
    """Link controller records to the selected surviving account."""

    model_config = ConfigDict(extra="forbid")
    source_ids: list[str] = Field(min_length=1, max_length=256)


def valid_name(value: str) -> str:
    """Use the face library's safe name grammar, preserving entered spaces."""
    name = " ".join(value.split())
    if name == "train" or not regex.fullmatch(r"[\p{L}\p{N}\s'_-]{1,50}", name) or sanitize_path_component(name) != name:
        raise EmployeeAccessError("invalid_name")
    return name


async def get_employee(employee_id: str) -> Employee:
    """Find an employee without leaking credentials in a response."""
    employee = await asyncio.to_thread(Employee.get_or_none, Employee.id == employee_id)
    if employee is None:
        raise EmployeeAccessError("employee_not_found", 404)
    return employee


async def new_password(request: Request, password: str | None) -> str | None:
    """Hash passwords off the event loop with Frigate's existing policy."""
    if password is None:
        return None
    valid, _ = validate_password_strength(password)
    if not valid:
        raise EmployeeAccessError("invalid_password")
    return await asyncio.to_thread(hash_password, password, None, request.app.frigate_config.auth.hash_iterations)


async def rename_employee_face(request: Request, old_name: str, new_name: str) -> bool:
    """Keep a bound employee identity consistent with a face-library rename."""
    employee = await asyncio.to_thread(Employee.get_or_none, Employee.face_name == old_name)
    if employee is None:
        return False
    async with request.app.employee_service.policy_lock:
        employee = await get_employee(employee.id)
        await update_identity(request, employee, valid_name(new_name))
        await asyncio.to_thread(employee.save)
    return True


async def update_identity(request: Request, employee: Employee, name: str) -> None:
    """Check collisions before renaming a bound face or employee."""
    conflict = await asyncio.to_thread(lambda: Employee.select().where(
        (Employee.name_key == name.casefold()) & (Employee.id != employee.id)
    ).exists())
    if conflict:
        raise EmployeeAccessError("duplicate_name", 409)
    if employee.face_name and employee.face_name != name:
        destination = safe_join(FACE_DIR, name)
        if destination is None or await asyncio.to_thread(Path(destination).exists):
            raise EmployeeAccessError("face_name_conflict", 409)
        if request.app.embeddings is None:
            raise EmployeeAccessError("recognition_unavailable", 503)
        try:
            await rename_face_library(request, employee.face_name, name)
        except (ValueError, OSError) as err:
            raise EmployeeAccessError("face_rename_failed") from err
        employee.face_name = name
    employee.name = name
    employee.name_key = name.casefold()
    employee.auth_version += 1


@router.get("/employees")
async def list_employees():
    """List employees, enrollment status, and effective local permissions."""
    return await asyncio.to_thread(lambda: [serialize_employee(employee) for employee in Employee.select().order_by(Employee.name, Employee.id)])


@router.post("/employees")
async def create_employee(request: Request, body: EmployeeBody):
    """Create a local employee without writing to physical controllers."""
    name = valid_name(body.name)
    username = body.username.strip().casefold() if body.username else None
    if username is not None and not regex.fullmatch(r"[a-z0-9_.-]{3,64}", username):
        raise EmployeeAccessError("invalid_username")
    password_hash = await new_password(request, body.password)
    async with request.app.employee_service.policy_lock:
        try:
            employee = await asyncio.to_thread(Employee.create,
                id=uuid4().hex, name=name, name_key=name.casefold(), username=username,
                password_hash=password_hash, enabled=body.enabled,
                face_name=name if await asyncio.to_thread(face_signature, name) else None)
        except IntegrityError as err:
            raise EmployeeAccessError("duplicate_account", 409) from err
    return await asyncio.to_thread(serialize_employee, employee)


@router.put("/employees/{employee_id}")
async def update_employee(request: Request, employee_id: str, body: EmployeeBody):
    """Update an account, revoking sessions when its identity or credentials change."""
    name = valid_name(body.name)
    username = body.username.strip().casefold() if body.username else None
    if username is not None and not regex.fullmatch(r"[a-z0-9_.-]{3,64}", username):
        raise EmployeeAccessError("invalid_username")
    password_hash = await new_password(request, body.password)
    async with request.app.employee_service.policy_lock:
        employee = await get_employee(employee_id)
        if username is not None and await asyncio.to_thread(lambda: Employee.select().where(
            (Employee.username == username) & (Employee.id != employee_id)
        ).exists()):
            raise EmployeeAccessError("duplicate_account", 409)
        await update_identity(request, employee, name)
        employee.username = username
        employee.enabled = body.enabled
        if password_hash is not None:
            employee.password_hash = password_hash
        if employee.face_name is None and await asyncio.to_thread(face_signature, name):
            employee.face_name = name
        try:
            await asyncio.to_thread(employee.save)
        except IntegrityError as err:
            raise EmployeeAccessError("duplicate_account", 409) from err
    return await asyncio.to_thread(serialize_employee, employee)


@router.put("/employees/{employee_id}/enabled")
async def enable_employee(request: Request, employee_id: str, body: EmployeeEnabledBody):
    """Enable or disable portal access without changing card permissions."""
    async with request.app.employee_service.policy_lock:
        employee = await get_employee(employee_id)
        employee.enabled = body.enabled
        employee.auth_version += 1
        await asyncio.to_thread(employee.save)
    return {"success": True}


@router.put("/employees/{employee_id}/password")
async def change_employee_password(request: Request, employee_id: str, body: EmployeePasswordBody):
    """Reset an employee password and invalidate all existing employee sessions."""
    password_hash = await new_password(request, body.password)
    async with request.app.employee_service.policy_lock:
        employee = await get_employee(employee_id)
        employee.password_hash = password_hash
        employee.auth_version += 1
        await asyncio.to_thread(employee.save)
    return {"success": True}


@router.delete("/employees/{employee_id}")
async def delete_employee(request: Request, employee_id: str):
    """Delete the account, retaining faces and tombstoning its controller links."""
    async with request.app.employee_service.policy_lock:
        employee = await get_employee(employee_id)
        await asyncio.to_thread(Employee.update(enabled=False, auth_version=Employee.auth_version + 1).where(Employee.id == employee_id).execute)
        await asyncio.to_thread(EmployeeSource.update(suppressed=True, employee_id=None).where(EmployeeSource.employee_id == employee_id).execute)
        await asyncio.to_thread(EmployeeDoorOverride.delete().where(EmployeeDoorOverride.employee_id == employee_id).execute)
        await asyncio.to_thread(employee.delete_instance)
    return {"success": True}


@router.post("/employees/{employee_id}/face")
async def upload_employee_face(request: Request, employee_id: str, file: UploadFile):
    """Register exactly one face under the employee's assigned name."""
    image = await file.read(UPLOAD_LIMIT + 1)
    if not image or len(image) > UPLOAD_LIMIT:
        raise EmployeeAccessError("invalid_image")
    async with request.app.employee_service.policy_lock:
        employee = await get_employee(employee_id)
        if not employee.name:
            raise EmployeeAccessError("name_required")
        if not request.app.employee_service.config.face_recognition.enabled:
            raise EmployeeAccessError("recognition_unavailable", 503)
        result = await asyncio.to_thread(embedding_request, "register_face", {
            "face_name": employee.name, "image": base64.b64encode(image).decode("ascii"),
            "single_face": True,
        }, 8)
        if not result.get("success"):
            raise EmployeeAccessError(result.get("reason", "invalid_image"))
        employee.face_name = employee.name
        employee.auth_version += 1
        await asyncio.to_thread(employee.save)
    return {"success": True}


@router.put("/employees/{employee_id}/face")
async def link_employee_face(request: Request, employee_id: str, body: EmployeeFaceBody):
    """Link a registered face, explicitly renaming a differently named library."""
    label = valid_name(body.face_name)
    async with request.app.employee_service.policy_lock:
        employee = await get_employee(employee_id)
        if not employee.name:
            raise EmployeeAccessError("name_required")
        owner = await asyncio.to_thread(Employee.get_or_none, Employee.face_name == label)
        if owner is not None and owner.id != employee_id:
            raise EmployeeAccessError("face_name_conflict", 409)
        if not await asyncio.to_thread(face_signature, label):
            raise EmployeeAccessError("no_registered_face")
        if label != employee.name:
            destination = safe_join(FACE_DIR, employee.name)
            if not body.rename or destination is None or await asyncio.to_thread(Path(destination).exists):
                raise EmployeeAccessError("face_name_conflict", 409)
            if request.app.embeddings is None:
                raise EmployeeAccessError("recognition_unavailable", 503)
            try:
                await rename_face_library(request, label, employee.name)
            except (ValueError, OSError) as err:
                raise EmployeeAccessError("face_rename_failed") from err
        employee.face_name = employee.name
        employee.auth_version += 1
        await asyncio.to_thread(employee.save)
    return {"success": True}


@router.put("/employees/{employee_id}/controllers/{controller_id}/doors")
async def set_employee_doors(request: Request, employee_id: str, controller_id: str, body: EmployeeDoorsBody):
    """Replace one controller's imported grants with a local door list."""
    device = await asyncio.to_thread(AccessControl.get_or_none, AccessControl.id == controller_id)
    if device is None:
        raise EmployeeAccessError("controller_unavailable", 404)
    try:
        doors = await asyncio.wait_for(build_controller(device).get_doors_async(), timeout=3)
    except (DahuaOperationError, TimeoutError) as err:
        raise EmployeeAccessError("controller_unavailable", 503) from err
    allowed = {str(door["id"]) for door in doors}
    if not set(body.doors) <= allowed:
        raise EmployeeAccessError("invalid_doors")
    async with request.app.employee_service.policy_lock:
        await get_employee(employee_id)
        await asyncio.to_thread(lambda: EmployeeDoorOverride.insert(
            employee_id=employee_id, controller_id=controller_id, doors=sorted(set(body.doors))
        ).on_conflict(conflict_target=[EmployeeDoorOverride.employee_id, EmployeeDoorOverride.controller_id],
                      update={EmployeeDoorOverride.doors: sorted(set(body.doors))}).execute())
    return {"success": True}


@router.delete("/employees/{employee_id}/controllers/{controller_id}/doors")
async def restore_employee_doors(request: Request, employee_id: str, controller_id: str):
    """Resume synchronization for this employee and controller."""
    async with request.app.employee_service.policy_lock:
        await get_employee(employee_id)
        await asyncio.to_thread(EmployeeDoorOverride.delete().where(
            (EmployeeDoorOverride.employee_id == employee_id) & (EmployeeDoorOverride.controller_id == controller_id)
        ).execute)
    return {"success": True}


@router.post("/employees/{employee_id}/sources")
async def link_controller_sources(request: Request, employee_id: str, body: EmployeeLinkBody):
    """Explicitly link imported records to the surviving employee account."""
    async with request.app.employee_service.policy_lock:
        await get_employee(employee_id)
        sources = await asyncio.to_thread(lambda: list(EmployeeSource.select().where(EmployeeSource.id.in_(body.source_ids))))
        if len(sources) != len(set(body.source_ids)) or any(source.suppressed for source in sources):
            raise EmployeeAccessError("invalid_sources")
        retired = {source.employee_id for source in sources if source.employee_id and source.employee_id != employee_id}
        await asyncio.to_thread(EmployeeSource.update(employee_id=employee_id).where(EmployeeSource.id.in_(body.source_ids)).execute)
        for old_id in retired:
            await asyncio.to_thread(Employee.update(auth_version=Employee.auth_version + 1).where(Employee.id == old_id).execute)
            remaining = await asyncio.to_thread(lambda: EmployeeSource.select().where(EmployeeSource.employee_id == old_id).exists())
            if not remaining:
                await asyncio.to_thread(EmployeeDoorOverride.delete().where(EmployeeDoorOverride.employee_id == old_id).execute)
                await asyncio.to_thread(Employee.delete().where(Employee.id == old_id).execute)
    return {"success": True}


@router.get("/employee-access/settings")
async def get_employee_settings(request: Request):
    """Read the persisted switch and directory synchronization health."""
    settings = await asyncio.to_thread(EmployeeAccessSettings.get_by_id, 1)
    sync = await asyncio.to_thread(lambda: list(EmployeeControllerSync.select().dicts()))
    return {"enabled": settings.enabled, "sync": sync,
            "port": request.app.frigate_config.networking.listen.employee_port}


@router.put("/employee-access/settings")
async def set_employee_settings(request: Request, body: EmployeeEnabledBody):
    """Change only cardless access and invalidate pending verifications."""
    async with request.app.employee_service.policy_lock:
        await asyncio.to_thread(EmployeeAccessSettings.update(
            enabled=body.enabled, generation=EmployeeAccessSettings.generation + 1
        ).where(EmployeeAccessSettings.id == 1).execute)
    return {"success": True}


@router.post("/employee-access/sync")
async def synchronize_employees(request: Request):
    """Refresh controller directories without changing local overrides."""
    return {"results": await request.app.employee_service.synchronize()}


@router.get("/employee-access/audit")
async def employee_access_audit():
    """Return the latest cardless results to administrators only."""
    return await asyncio.to_thread(lambda: list(EmployeeAccessAttempt.select().order_by(EmployeeAccessAttempt.created_at.desc()).limit(500).dicts()))
