# Copyright (C) 2025 Fortinet Inc. — MIT License
"""Operation implementations. Each send op returns a SendResult.as_output()
dict — the structured return value the legacy connector lacked."""

from __future__ import annotations

import logging
import os
import re
from os.path import basename, join

from . import platform
from .config import SMTPConfig
from .models import (
    BodyType,
    EmailTemplateRef,
    PersonRef,
    Recipients,
    RecipientType,
    SendEmailParams,
    SendResult,
    TeamRef,
)
from .transport import SMTPTransport, build_message

logger = logging.getLogger("connectors.smtp")

EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
TMP_ROOT = os.environ.get("SMTP_TMP_ROOT", "/tmp")


# --------------------------------------------------------------------------- #
# Recipient resolution
# --------------------------------------------------------------------------- #
def _resolve_recipients(p: SendEmailParams) -> tuple[list[str], list[str], list[str]]:
    if p.recipient_type == RecipientType.user:
        # UI sends "First Last email@x" strings; take the last token (email).
        def pick(lst):
            return [u.split()[-1] for u in lst if u.split()]

        return pick(p.to), pick(p.cc), pick(p.bcc)
    if p.recipient_type == RecipientType.team:
        return (_emails_for_teams(p.to), _emails_for_teams(p.cc), _emails_for_teams(p.bcc))
    # Manual Input: each entry is an email, a /api/3/people IRI, or a /api/3/teams IRI.
    return (_resolve_manual(p.to), _resolve_manual(p.cc), _resolve_manual(p.bcc))


def _resolve_manual(entries: list[str]) -> list[str]:
    emails, people_iris, team_iris = [], [], []
    for e in entries:
        if "/api/3/people" in e:
            people_iris.append(e.rsplit("/", 1)[-1])
        elif "/api/3/teams" in e:
            team_iris.append(e.rsplit("/", 1)[-1])
        elif EMAIL_RE.match(e):
            emails.append(e)
    if people_iris:
        emails += _emails_for_people_uuids(people_iris)
    if team_iris:
        emails += _emails_for_team_uuids(team_iris)
    return sorted(set(emails))


def _emails_for_people_uuids(uuids: list[str]) -> list[str]:
    body = {"logic": "OR", "filters": [{"field": "uuid", "operator": "eq", "value": u} for u in uuids]}
    resp = platform.make_request("/api/query/people", "POST", body=body)["hydra:member"]
    people = [PersonRef.model_validate(p) for p in resp]
    return [p.email for p in people if p.email]


def _emails_for_team_uuids(uuids: list[str]) -> list[str]:
    body = {"logic": "OR", "filters": [{"field": "uuid", "operator": "eq", "value": u} for u in uuids]}
    resp = platform.make_request("/api/query/teams?$relationships=true", "POST", body=body)["hydra:member"]
    return _emails_from_team_records([TeamRef.model_validate(t) for t in resp])


def _emails_for_teams(team_names: list[str]) -> list[str]:
    if not team_names:
        return []
    resp = platform.make_request("/api/3/teams?$relationships=true", "GET")["hydra:member"]
    teams = [TeamRef.model_validate(t) for t in resp]
    wanted = [t for t in teams if t.name in set(team_names)]
    return _emails_from_team_records(wanted)


def _emails_from_team_records(teams: list[TeamRef]) -> list[str]:
    emails, uuids = set(), []
    for team in teams:
        for actor in team.actors:
            if isinstance(actor, str):  # IRI string -> needs a follow-up lookup
                uuids.append(actor.rsplit("/", 1)[-1])
            elif actor.email:  # expanded PersonRef (from $relationships=true)
                emails.add(actor.email)
    if uuids:
        emails.update(_emails_for_people_uuids(uuids))
    return sorted(emails)


# --------------------------------------------------------------------------- #
# Attachments
# --------------------------------------------------------------------------- #
def _collect_attachments(p: SendEmailParams, env: dict) -> list[tuple[str, bytes]]:
    out = []
    if p.file_path:
        path = p.file_path.strip()
        if path.startswith(TMP_ROOT):
            path = path[len(TMP_ROOT) :].lstrip("/")
        full = join(TMP_ROOT, path)
        _check_traversal(full)
        name = p.file_name or basename(full)
        with open(full, "rb") as fh:
            out.append((name, fh.read()))
    for iri in p.iri_list:  # already a list (bare @id works in every op now)
        path, name = _download_iri(iri, env)
        with open(path, "rb") as fh:
            out.append((name, fh.read()))
    return out


def _check_traversal(full_path: str) -> None:
    root = os.path.abspath(TMP_ROOT)
    if os.path.commonprefix([os.path.abspath(full_path), root]) != root:
        raise ValueError("File traversal attempted")


def _download_iri(iri: str, env: dict) -> tuple[str, str]:
    file_iri = iri
    if iri.startswith("/api/3/attachments/"):
        file_iri = platform.make_request(iri, "GET")["file"]["@id"]
    resp = platform.download_file_from_cyops(file_iri, env=env)
    return join(TMP_ROOT, resp["cyops_file_path"]), resp["filename"]


# --------------------------------------------------------------------------- #
# Email templates
# --------------------------------------------------------------------------- #
def _apply_template(p: SendEmailParams, env: dict) -> tuple[str, str]:
    body = {"logic": "OR", "filters": [{"field": "name", "operator": "eq", "value": p.email_templates}]}
    resp = platform.make_request("/api/query/email_templates", "POST", body=body)["hydra:member"]
    if not resp:
        raise ValueError(f"Email template not found: {p.email_templates}")
    tpl = EmailTemplateRef.model_validate(resp[0])
    return platform.expand(env, tpl.subject), platform.expand(env, tpl.content)


# --------------------------------------------------------------------------- #
# Public operations
# --------------------------------------------------------------------------- #
def _send(config: dict, params: SendEmailParams, env: dict) -> dict:
    cfg = SMTPConfig.from_connector_config(config)

    to, cc, bcc = _resolve_recipients(params)
    if not (to or cc or bcc):
        raise ValueError("At least one recipient (To, CC, or BCC) is required")

    subject, content = params.subject, params.content
    if params.body_type == BodyType.template:
        subject, content = _apply_template(params, env)

    from_addr = params.from_
    if not from_addr or not EMAIL_RE.match(from_addr):
        from_addr = cfg.default_from
    if not from_addr:
        raise ValueError("No 'From' address: set a valid From or configure Default From")

    attachments = _collect_attachments(params, env)
    msg = build_message(
        from_addr=from_addr,
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        content=content,
        is_html=params.is_html,
        attachments=attachments,
    )
    try:
        SMTPTransport(cfg).send(msg)
    except Exception as e:
        logger.exception("Error sending email")
        raise ValueError(f"Error sending email: {e}") from e

    return SendResult(
        status="sent",
        message_id=msg["Message-ID"],
        **{"from": from_addr},
        subject=subject,
        recipients=Recipients(to=to, cc=cc, bcc=bcc),
        attachments=[name for name, _ in attachments],
        accepted_count=len(to) + len(cc) + len(bcc),
    ).as_output()


def send_email_new(config: dict, params: dict) -> dict:
    env = params.get("env", {}) or {}
    return _send(config, SendEmailParams.from_params(params), env)


def send_email(config: dict, params: dict) -> dict:
    # Legacy op: same unified, schema-aligned implementation.
    return send_email_new(config, params)


def send_richtext_email(config: dict, params: dict) -> dict:
    params = dict(params)
    params["body_type"] = BodyType.rich.value
    return send_email_new(config, params)


def check_health(config: dict, params: dict | None = None) -> bool:
    cfg = SMTPConfig.from_connector_config(config)
    return SMTPTransport(cfg).verify()


def get_users(config: dict, params: dict) -> list[str]:
    resp = platform.make_request("/api/3/people?$limit=1000", "GET")["hydra:member"]
    return [PersonRef.model_validate(u).display for u in resp]


def get_teams(config: dict, params: dict) -> list[str]:
    resp = platform.make_request("/api/3/teams?$limit=1000", "GET")["hydra:member"]
    return [TeamRef.model_validate(t).name for t in resp]


def get_email_templates(config: dict, params: dict) -> list[str]:
    resp = platform.make_request("/api/3/email_templates", "GET")["hydra:member"]
    return [t["name"] for t in resp]
