# Copyright (C) 2025 Fortinet Inc. — MIT License
"""FortiSOAR Connector adapter. Thin: maps operation names to functions in
operations.py and delegates. All real logic lives in the pydantic-typed,
Django-free modules."""

from connectors.core.connector import Connector, get_logger

from .operations import (
    check_health,
    get_email_templates,
    get_teams,
    get_users,
    send_email,
    send_email_new,
    send_richtext_email,
)

logger = get_logger("connectors.smtp")

OPERATIONS = {
    "send_email": send_email,
    "send_email_new": send_email_new,
    "send_richtext_email": send_richtext_email,
    "get_users": get_users,
    "get_teams": get_teams,
    "get_email_templates": get_email_templates,
}


class SMTP(Connector):
    def execute(self, config, operation, params, **kwargs):
        params = dict(params or {})
        params["env"] = kwargs.get("env", {})
        action = OPERATIONS.get(operation)
        if action is None:
            raise ValueError(f"Unsupported operation: {operation}")
        return action(config, params)

    def check_health(self, config):
        return check_health(config)
