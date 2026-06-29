"""Shared fixtures: an in-process SMTP server (aiosmtpd) and a replay router
that serves real FortiSOAR API responses captured from a live appliance
(fsr130) into tests/fixtures/*.json."""
import json
import socket
from pathlib import Path

import pytest
from aiosmtpd.controller import Controller

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


class _Sink:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope)
        return "250 OK"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def smtp_server():
    sink = _Sink()
    port = _free_port()
    controller = Controller(sink, hostname="127.0.0.1", port=port)
    controller.start()
    controller._real_port = port
    yield controller, sink
    controller.stop()


@pytest.fixture
def smtp_config(smtp_server):
    controller, _ = smtp_server
    return {"host": "127.0.0.1", "port": controller._real_port, "useTLS": False,
            "default_from": "from@local.test", "timeout": 10}


@pytest.fixture
def fsr_api(monkeypatch):
    """Replace smtp.platform.make_request with a router over the captured
    fixtures. Routes by (method, endpoint-prefix), mirroring the real calls."""
    from smtp import platform

    def router(endpoint, method, **kwargs):
        m = method.upper()
        if m == "GET" and endpoint.startswith("/api/3/people"):
            return load_fixture("people.json")
        if m == "GET" and endpoint.startswith("/api/3/teams"):
            return load_fixture("teams_rel.json")
        if m == "GET" and endpoint.startswith("/api/3/email_templates"):
            return load_fixture("email_templates.json")
        if m == "POST" and endpoint.startswith("/api/query/people"):
            return load_fixture("query_people.json")
        if m == "POST" and endpoint.startswith("/api/query/teams"):
            return load_fixture("query_teams.json")
        if m == "POST" and endpoint.startswith("/api/query/email_templates"):
            return load_fixture("query_email_templates.json")
        raise AssertionError(f"unrouted API call: {method} {endpoint}")

    monkeypatch.setattr(platform, "make_request", router)
    return router
