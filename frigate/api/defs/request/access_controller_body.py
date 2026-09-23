from pydantic import BaseModel, Field


class AccessControllerBody(BaseModel):
    id: str = Field(min_length=1, max_length=30)
    name: str | None = Field(default=None, max_length=100)
    ip_address: str = Field(min_length=1, max_length=45)
    port: int = Field(default=80, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, max_length=255)
    associated_camera: str | None = Field(default=None, max_length=100)
    seconds_before: int = Field(default=10, ge=0, le=300)
    seconds_after: int = Field(default=10, ge=0, le=300)


class AccessControllerUpdateBody(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    ip_address: str | None = Field(default=None, max_length=45)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=100)
    password: str | None = Field(default=None, max_length=255)
    clear_credentials: bool = False
    associated_camera: str | None = Field(default=None, max_length=100)
    seconds_before: int | None = Field(default=None, ge=0, le=300)
    seconds_after: int | None = Field(default=None, ge=0, le=300)
