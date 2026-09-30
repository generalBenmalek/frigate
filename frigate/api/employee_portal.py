"""Employee-only authentication and snapshot verification, on an isolated app."""

import asyncio
import hashlib
import hmac
import secrets
import time
from collections import deque
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from pydantic import BaseModel, ConfigDict, Field

from frigate.access_controller_service import build_controller
from frigate.api.auth import hash_password, verify_password
from frigate.dahua_adapter import DahuaOperationError
from frigate.employee_service import EmployeeAccessError, employee_doors, face_signature
from frigate.models import AccessControl, Employee, EmployeeAccessSettings

TOKEN_COOKIE = "frigate_employee_token"
CSRF_COOKIE = "frigate_employee_csrf"
COOKIE_PATH = "/api/employee/"
router = APIRouter(tags=["Employee portal"])


class EmployeeLoginBody(BaseModel):
    """Employee credentials, accepted only by the employee login endpoint."""

    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class ForgotCardBody(BaseModel):
    """A door selection, never a client-selected employee identity."""

    model_config = ConfigDict(extra="forbid")
    camera: str = Field(min_length=1, max_length=100)
    controller_id: str = Field(min_length=1, max_length=30)
    door_id: str = Field(min_length=1, max_length=100)
    request_id: UUID


class EmployeeLimits:
    """Bounded employee-specific limits, independent of main auth settings."""

    def __init__(self):
        self.events: dict[str, deque[float]] = {}

    def check(self, key: str, maximum: int, *, record: bool = True) -> None:
        """Enforce a sixty-second window without keeping credentials."""
        now = time.monotonic()
        if len(self.events) >= 10000:
            self.events = {key: values for key, values in self.events.items() if values and now - values[-1] < 60}
            if len(self.events) >= 10000:
                raise EmployeeAccessError("rate_limited", 429)
        values = self.events.setdefault(key, deque())
        while values and now - values[0] >= 60:
            values.popleft()
        if len(values) >= maximum:
            raise EmployeeAccessError("rate_limited", 429)
        if record:
            values.append(now)


async def employee_error(_request: Request, error: EmployeeAccessError):
    """Return stable failure codes without provider or biometric details."""
    return JSONResponse({"success": False, "reason": error.reason}, status_code=error.status,
                        headers={"Cache-Control": "no-store"})


def claims(request: Request, cookie: str, audience: str) -> dict | None:
    """Validate only this application's signed token and purpose."""
    encoded = request.cookies.get(cookie)
    if not encoded:
        return None
    try:
        token = jwt.decode(encoded, request.app.state.employee_key, algorithms=["HS256"])
        payload = token.claims
        if payload.get("aud") != audience or not isinstance(payload.get("exp"), int) or payload["exp"] <= time.time():
            return None
        return payload
    except (JoseError, ValueError, TypeError, KeyError):
        return None


async def authenticated_employee(request: Request) -> Employee | None:
    """Resolve a stable account ID and check revocation on every request."""
    payload = claims(request, TOKEN_COOKIE, "employee-portal")
    if payload is None or not isinstance(payload.get("sub"), str):
        return None
    employee = await asyncio.to_thread(Employee.get_or_none, Employee.id == payload["sub"])
    if employee is None or not employee.enabled or not employee.name or not employee.username or not employee.password_hash or payload.get("version") != employee.auth_version:
        return None
    return employee


async def require_employee(request: Request) -> Employee:
    """Require employee credentials even on Frigate's trusted internal port."""
    employee = await authenticated_employee(request)
    if employee is None:
        raise EmployeeAccessError("session_expired", 401)
    return employee


def check_employee_csrf(request: Request) -> None:
    """Require a signed same-origin token for all employee mutations."""
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get("x-csrf-token", "")
    if not cookie or not header or not secrets.compare_digest(cookie, header) or claims(request, CSRF_COOKIE, "employee-csrf") is None:
        raise EmployeeAccessError("invalid_csrf", 403)


def set_cookie(request: Request, response: Response, name: str, value: str, age: int) -> None:
    """Use a separate, strictly same-site cookie scoped to employee API paths."""
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(name, value, max_age=age, path=COOKIE_PATH,
                        httponly=True, secure=secure, samesite="strict")


@router.get("/session")
async def employee_session(request: Request, response: Response):
    """Bootstrap CSRF and return only the logged-in employee's own status."""
    token = request.cookies.get(CSRF_COOKIE)
    if claims(request, CSRF_COOKIE, "employee-csrf") is None:
        token = jwt.encode({"alg": "HS256"}, {
            "aud": "employee-csrf", "exp": int(time.time()) + 3600,
            "nonce": secrets.token_hex(32),
        }, request.app.state.employee_key)
        set_cookie(request, response, CSRF_COOKIE, token, 3600)
    employee = await authenticated_employee(request)
    data = {"authenticated": employee is not None, "csrf_token": token}
    if employee is not None:
        settings = await asyncio.to_thread(EmployeeAccessSettings.get_by_id, 1)
        data.update({"name": employee.name, "has_face": bool(await asyncio.to_thread(face_signature, employee.face_name)),
                     "enabled": settings.enabled})
    return data


@router.post("/login", dependencies=[Depends(check_employee_csrf)])
async def employee_login(request: Request, response: Response, body: EmployeeLoginBody):
    """Authenticate against local employee accounts, never Frigate users."""
    username = body.username.strip().casefold()
    address = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
    keys = [f"login-ip:{hashlib.sha256(address.encode()).hexdigest()}",
            f"login-user:{hashlib.sha256(username.encode()).hexdigest()}"]
    limits = request.app.state.employee_limits
    for key in keys:
        limits.check(key, 5)
    employee = await asyncio.to_thread(Employee.get_or_none, Employee.username == username)
    password_hash = employee.password_hash if employee and employee.password_hash else request.app.state.dummy_hash
    matches = await asyncio.to_thread(verify_password, body.password, password_hash)
    if not matches or employee is None or not employee.enabled or not employee.name or not employee.password_hash:
        raise EmployeeAccessError("login_failed", 401)
    age = request.app.state.employee_service.config.auth.session_length
    encoded = jwt.encode({"alg": "HS256"}, {
        "aud": "employee-portal", "sub": employee.id,
        "version": employee.auth_version, "iat": int(time.time()),
        "exp": int(time.time()) + age,
    }, request.app.state.employee_key)
    set_cookie(request, response, TOKEN_COOKIE, encoded, age)
    return {"success": True}


@router.post("/logout", dependencies=[Depends(check_employee_csrf)])
async def employee_logout(request: Request, response: Response, employee: Employee = Depends(require_employee)):
    """Revoke employee sessions and clear this portal's cookies."""
    async with request.app.state.employee_service.policy_lock:
        await asyncio.to_thread(Employee.update(auth_version=Employee.auth_version + 1).where(Employee.id == employee.id).execute)
    response.delete_cookie(TOKEN_COOKIE, path=COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE, path=COOKIE_PATH)
    return {"success": True}


@router.get("/options")
async def employee_options(request: Request, employee: Employee = Depends(require_employee)):
    """List only granted doors and their currently associated Frigate cameras."""
    service = request.app.state.employee_service
    devices = await asyncio.to_thread(lambda: list(AccessControl.select()))

    async def available(device: AccessControl):
        camera = service.config.cameras.get(device.associated_camera)
        if camera is None or not camera.enabled or not camera.detect.enabled or not camera.face_recognition.enabled or not service.config.face_recognition.enabled:
            return None
        allowed = await asyncio.to_thread(employee_doors, employee.id, device.id)
        if not allowed:
            return None
        try:
            async with service.sync_semaphore:
                doors = await asyncio.wait_for(build_controller(device).get_doors_async(), timeout=3)
        except (DahuaOperationError, TimeoutError):
            return None
        permitted = [{"id": str(door["id"]), "name": str(door["name"])} for door in doors if str(door["id"]) in allowed]
        if not permitted:
            return None
        return {"camera": device.associated_camera, "controller_id": device.id,
                "controller_name": device.name, "doors": permitted}

    options = await asyncio.gather(*(available(device) for device in devices))
    return [option for option in options if option is not None]


@router.post("/forgot-card", dependencies=[Depends(check_employee_csrf)])
async def forgot_card(request: Request, body: ForgotCardBody, employee: Employee = Depends(require_employee)):
    """Verify the authenticated employee and automatically request one unlock."""
    request.app.state.employee_limits.check(f"verify:{employee.id}", 3)
    return await request.app.state.employee_service.verify(
        employee, body.camera, body.controller_id, body.door_id, str(body.request_id)
    )


def create_employee_app(service, secret: str) -> FastAPI:
    """Mount employee auth independently of the main app's admin dependencies."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.employee_service = service
    key = hmac.digest(secret.encode(), b"frigate.employee-portal.v1", "sha256")
    app.state.employee_key = OctKey.import_key(key)
    app.state.employee_limits = EmployeeLimits()
    app.state.dummy_hash = hash_password(secrets.token_urlsafe(32), iterations=service.config.auth.hash_iterations)
    app.add_exception_handler(EmployeeAccessError, employee_error)

    @app.exception_handler(RequestValidationError)
    async def invalid_employee_request(_request: Request, _error: RequestValidationError):
        """Do not echo submitted credentials or identity fields in errors."""
        return JSONResponse({"success": False, "reason": "invalid_request"}, status_code=422)

    @app.middleware("http")
    async def employee_security(request: Request, call_next):
        origin = request.headers.get("origin")
        host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        if origin and origin != f"{scheme}://{host}":
            return JSONResponse({"success": False, "reason": "invalid_csrf"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(router)
    return app
