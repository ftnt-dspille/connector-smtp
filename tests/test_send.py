"""Tests against a real in-process SMTP server (aiosmtpd) — exercises the full
stdlib transport, message building, and structured result."""
import asyncio
import threading

import pytest
from aiosmtpd.controller import Controller

from smtp import operations
from smtp.config import SMTPConfig
from smtp.models import SendEmailParams
from smtp.transport import build_message, extract_inline_images


class _Sink:
    def __init__(self):
        self.messages = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope)
        return "250 OK"


def _free_port():
    import socket
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


def _config(controller):
    return {"host": "127.0.0.1", "port": controller._real_port, "useTLS": False,
            "default_from": "from@local.test", "timeout": 10}


def test_send_email_new_returns_structured_result(smtp_server):
    controller, sink = smtp_server
    params = {"type": "Manual Input", "to": "a@local.test, b@local.test",
              "subject": "hi", "body_type": "Plain Text", "content": "hello"}
    result = operations.send_email_new(_config(controller), params)

    assert result["status"] == "sent"
    assert result["message_id"]
    assert result["from"] == "from@local.test"
    assert result["recipients"]["to"] == ["a@local.test", "b@local.test"]
    assert result["accepted_count"] == 2
    assert len(sink.messages) == 1
    assert sink.messages[0].rcpt_tos == ["a@local.test", "b@local.test"]


def test_bcc_is_delivered_but_stripped_from_headers(smtp_server):
    controller, sink = smtp_server
    params = {"to": "a@local.test", "bcc": "secret@local.test",
              "subject": "s", "body_type": "Plain Text", "content": "x"}
    result = operations.send_email_new(_config(controller), params)
    env = sink.messages[0]
    assert "secret@local.test" in env.rcpt_tos          # delivered
    assert b"secret@local.test" not in env.content      # not in headers
    assert result["accepted_count"] == 2


def test_requires_a_recipient(smtp_server):
    controller, _ = smtp_server
    with pytest.raises(ValueError, match="At least one recipient"):
        operations.send_email_new(_config(controller), {"subject": "s", "content": "x"})


def test_bare_attachment_iri_normalizes_to_list():
    p = SendEmailParams.from_params({"to": "a@b.com", "iri_list": "/api/3/attachments/abc"})
    assert p.iri_list == ["/api/3/attachments/abc"]


def test_config_coerces_string_port_and_rejects_tls_ssl_both():
    cfg = SMTPConfig.from_connector_config({"host": "h", "port": "465", "useSSL": True})
    assert cfg.port == 465 and cfg.use_ssl is True
    with pytest.raises(ValueError, match="mutually exclusive"):
        SMTPConfig.from_connector_config({"host": "h", "useTLS": True, "useSSL": True})


def test_inline_image_extraction():
    html = '<img src="data:image/png;base64,aGVsbG8=">'
    rewritten, images = extract_inline_images(html)
    assert "cid:" in rewritten and len(images) == 1
    assert images[0][1] == "png"


def test_check_health(smtp_server):
    controller, _ = smtp_server
    assert operations.check_health(_config(controller)) is True
