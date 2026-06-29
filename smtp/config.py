# Copyright (C) 2025 Fortinet Inc. — MIT License
"""Pydantic model for the connector's configuration (the `config` dict FortiSOAR
passes to every operation). Accepts both the FortiSOAR field names (useTLS,
useSSL) and snake_case, coerces the string port to int, and validates that TLS
and SSL aren't both requested."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SMTPConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    host: str
    port: int = 25
    username: str | None = None
    password: str | None = None
    use_tls: bool = Field(default=False, alias="useTLS")
    use_ssl: bool = Field(default=False, alias="useSSL")
    default_from: str | None = None
    timeout: int = 10

    @field_validator("port", "timeout", mode="before")
    @classmethod
    def _coerce_int(cls, v):
        # info.json declares port as text ("25"); timeout as integer. Be liberal.
        if v is None or v == "":
            return None
        return int(v)

    @field_validator("host")
    @classmethod
    def _host_required(cls, v):
        if not v or not str(v).strip():
            raise ValueError("SMTP host is required")
        return str(v).strip()

    @model_validator(mode="after")
    def _tls_ssl_exclusive(self):
        if self.use_tls and self.use_ssl:
            raise ValueError("Use TLS (STARTTLS) and Use SSL (implicit TLS) are mutually exclusive")
        return self

    @classmethod
    def from_connector_config(cls, config: dict) -> SMTPConfig:
        """Build from the raw FortiSOAR config dict, defaulting timeout sanely."""
        data = dict(config or {})
        if not data.get("timeout"):
            data["timeout"] = 10
        return cls.model_validate(data)
