# Copyright (C) 2025 Fortinet Inc. — MIT License
"""Thin lazy wrappers around the FortiSOAR runtime calls that only exist on the
appliance. Imported lazily so the send path works off-box (local tests) with
zero FortiSOAR dependencies; only the platform-coupled actions (User/Team
recipients, Email Template body, attachment-IRI downloads, get_users/get_teams/
get_email_templates) touch these."""

from __future__ import annotations


def make_request(endpoint: str, method: str, **kwargs):
    from integrations.crudhub import make_request as _mr  # noqa: platform-only

    return _mr(endpoint, method, **kwargs)


def download_file_from_cyops(file_iri: str, env: dict | None = None):
    from connectors.cyops_utilities.builtins import download_file_from_cyops as _dl  # noqa

    return _dl(file_iri, env=env or {})


def expand(env: dict, value: str):
    try:
        from connectors.environment import expand as _expand  # noqa

        return _expand(env, value)
    except Exception:
        return value
