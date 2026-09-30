from pydantic import Field, model_validator

from .base import FrigateBaseModel

__all__ = ["IPv6Config", "ListenConfig", "NetworkingConfig"]


def parse_listen_port(value: int | str) -> int:
    """Return the port number from a bare port or an "address:port" value."""
    if isinstance(value, str):
        return int(value.split(":")[-1])

    return value


class IPv6Config(FrigateBaseModel):
    enabled: bool = Field(
        default=False,
        title="Enable IPv6",
        description="Enable IPv6 support for Frigate services (API and UI) where applicable.",
    )


class ListenConfig(FrigateBaseModel):
    internal: int | str = Field(
        default=5000,
        title="Internal port",
        description="Internal listening port for Frigate (default 5000).",
    )
    external: int | str = Field(
        default=8971,
        title="External port",
        description="External listening port for Frigate (default 8971).",
    )
    employee: int | str = Field(
        default=8972,
        title="Employee portal port",
        description="Listening port for the isolated employee portal (default 8972). Restart required after changing this port.",
    )

    @property
    def employee_port(self) -> int:
        """Return the standalone employee website's listening port."""
        return parse_listen_port(self.employee)

    @property
    def internal_port(self) -> int:
        return parse_listen_port(self.internal)

    @property
    def external_port(self) -> int:
        return parse_listen_port(self.external)

    @model_validator(mode="after")
    def validate_distinct_ports(self) -> "ListenConfig":
        if len({self.internal_port, self.external_port, self.employee_port}) != 3:
            raise ValueError("internal, external, and employee must listen on different ports")

        return self


class NetworkingConfig(FrigateBaseModel):
    ipv6: IPv6Config = Field(
        default_factory=IPv6Config,
        title="IPv6 configuration",
        description="IPv6-specific settings for Frigate network services.",
    )
    listen: ListenConfig = Field(
        default_factory=ListenConfig,
        title="Listening ports configuration",
        description="Configuration for internal, external, and employee portal listening ports. This is for advanced users. For the majority of use cases it's recommended to change the ports section of your Docker compose file.",
    )
