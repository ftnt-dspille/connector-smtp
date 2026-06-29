"""Tests against a real in-process SMTP server (aiosmtpd) — exercises the full
stdlib transport, message building, and structured result. The smtp_server /
smtp_config fixtures live in conftest.py."""

import pytest

from smtp_ng import operations
from smtp_ng.config import SMTPConfig
from smtp_ng.models import SendEmailParams
from smtp_ng.transport import extract_inline_images


def test_send_email_new_returns_structured_result(smtp_server, smtp_config):
    _, sink = smtp_server
    params = {
        "type": "Manual Input",
        "to": "a@local.test, b@local.test",
        "subject": "hi",
        "body_type": "Plain Text",
        "content": "hello",
    }
    result = operations.send_email_new(smtp_config, params)

    assert result["status"] == "sent"
    assert result["message_id"]
    assert result["from"] == "from@local.test"
    assert result["recipients"]["to"] == ["a@local.test", "b@local.test"]
    assert result["accepted_count"] == 2
    assert len(sink.messages) == 1
    assert sink.messages[0].rcpt_tos == ["a@local.test", "b@local.test"]


def test_bcc_is_delivered_but_stripped_from_headers(smtp_server, smtp_config):
    _, sink = smtp_server
    params = {
        "to": "a@local.test",
        "bcc": "secret@local.test",
        "subject": "s",
        "body_type": "Plain Text",
        "content": "x",
    }
    result = operations.send_email_new(smtp_config, params)
    env = sink.messages[0]
    assert "secret@local.test" in env.rcpt_tos  # delivered
    assert b"secret@local.test" not in env.content  # not in headers
    assert result["accepted_count"] == 2


def test_requires_a_recipient(smtp_config):
    with pytest.raises(ValueError, match="At least one recipient"):
        operations.send_email_new(smtp_config, {"subject": "s", "content": "x"})


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


def test_check_health(smtp_config):
    assert operations.check_health(smtp_config) is True
