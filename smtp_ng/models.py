# Copyright (C) 2025 Fortinet Inc. — MIT License
"""Pydantic models for operation params and results.

The public surface FortiSOAR calls is a flat `params` dict, so `SendEmailParams`
normalizes the various recipient/body/attachment shapes (comma- or
semicolon-separated strings, lists, single IRIs) into clean typed fields.

`SendResult` is the structured value every send operation now returns — this is
the headline improvement over the legacy connector, which returned None."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


def to_list(value) -> list[str]:
    """Normalize None / list / comma-or-semicolon string into a clean list."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        parts = re.split(r"[;,]", value)
        return [p.strip() for p in parts if p.strip()]
    return [str(value).strip()]


class RecipientType(str, Enum):
    manual = "Manual Input"
    user = "User"
    team = "Team"


class BodyType(str, Enum):
    plain = "Plain Text"
    rich = "Rich Text"
    template = "Email Template"


class SendEmailParams(BaseModel):
    """Normalized inputs for a send operation. Accepts the legacy field names
    (to_recipients/cc_recipients/bcc_recipients/body) as aliases."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    recipient_type: RecipientType = Field(default=RecipientType.manual, alias="type")
    body_type: BodyType = Field(default=BodyType.rich, alias="body_type")

    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)

    from_: str | None = Field(default=None, alias="from")
    subject: str = ""
    content: str = ""

    file_path: str | None = None
    file_name: str | None = None
    iri_list: list[str] = Field(default_factory=list)

    email_templates: str | None = None  # template name, when body_type == Email Template

    @field_validator("to", "cc", "bcc", "iri_list", mode="before")
    @classmethod
    def _listify(cls, v):
        return to_list(v)

    @field_validator("subject", "content", mode="before")
    @classmethod
    def _str(cls, v):
        return "" if v is None else str(v)

    @classmethod
    def from_params(cls, params: dict) -> SendEmailParams:
        """Build from the raw FortiSOAR params, honoring legacy aliases:
        to_recipients/cc_recipients/bcc_recipients -> to/cc/bcc, body -> content."""
        p = dict(params or {})
        if p.get("to_recipients") and not p.get("to"):
            p["to"] = p["to_recipients"]
        if p.get("cc_recipients") and not p.get("cc"):
            p["cc"] = p["cc_recipients"]
        if p.get("bcc_recipients") and not p.get("bcc"):
            p["bcc"] = p["bcc_recipients"]
        if p.get("body") and not p.get("content"):
            p["content"] = p["body"]
        return cls.model_validate(p)

    @property
    def is_html(self) -> bool:
        return self.body_type in (BodyType.rich, BodyType.template)


# --------------------------------------------------------------------------- #
# Inbound FortiSOAR API shapes (only the fields the connector reads). Validated
# against real responses captured from fsr130 in tests/fixtures/. Kept slim and
# local so the connector stays free of a pyfsr runtime dependency.
# --------------------------------------------------------------------------- #
class PersonRef(BaseModel):
    """A `/api/3/people` record (pyfsr calls this `User`)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id_iri: str | None = Field(default=None, alias="@id")
    uuid: str | None = None
    firstname: str | None = None
    lastname: str | None = None
    email: str | None = None

    @property
    def display(self) -> str:
        return f"{self.firstname or ''} {self.lastname or ''} {self.email or ''}".strip()


class TeamRef(BaseModel):
    """A `/api/3/teams` record. With `$relationships=true`, `actors` come back as
    expanded people dicts; without it they're IRI strings — both are handled."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id_iri: str | None = Field(default=None, alias="@id")
    uuid: str | None = None
    name: str | None = None
    actors: list = Field(default_factory=list)  # list[PersonRef | str(IRI)]

    @field_validator("actors", mode="before")
    @classmethod
    def _parse_actors(cls, v):
        out = []
        for a in v or []:
            out.append(PersonRef.model_validate(a) if isinstance(a, dict) else a)
        return out


class EmailTemplateRef(BaseModel):
    """An `/api/3/email_templates` record (pyfsr has no model for this)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id_iri: str | None = Field(default=None, alias="@id")
    uuid: str | None = None
    name: str | None = None
    subject: str = ""
    content: str = ""


class Recipients(BaseModel):
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)


class SendResult(BaseModel):
    """Structured return value for send operations."""

    model_config = ConfigDict(populate_by_name=True)

    status: str = "sent"
    message_id: str | None = None
    from_: str = Field(default="", alias="from")
    subject: str = ""
    recipients: Recipients = Field(default_factory=Recipients)
    attachments: list[str] = Field(default_factory=list)
    accepted_count: int = 0

    def as_output(self) -> dict:
        return self.model_dump(by_alias=True)
