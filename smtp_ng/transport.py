# Copyright (C) 2025 Fortinet Inc. — MIT License
"""Django-free SMTP transport built on Python's stdlib `smtplib` + `email`.

`build_message()` turns normalized params + body parts into an EmailMessage
(plain text, HTML alternative, inline images, attachments). `SMTPTransport`
opens the connection (STARTTLS / implicit SSL / plain, with optional auth) and
sends or just verifies it."""

from __future__ import annotations

import base64
import re
import smtplib
import ssl
import uuid
from email.message import EmailMessage

from .config import SMTPConfig


def html_to_text(html: str) -> str:
    """Derive a plain-text alternative from HTML without GPL deps (bs4 is MIT)."""
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    except Exception:
        # Fallback: crude tag strip
        return re.sub(r"<[^>]+>", "", html).strip()


_DATA_IMG_RE = re.compile(r"data:image/(?P<subtype>[^;]+);base64,(?P<data>[^\"'\s>]+)")


def extract_inline_images(html: str):
    """Replace `data:image/...;base64,...` srcs with cid: references and return
    (rewritten_html, [(cid, subtype, raw_bytes), ...])."""
    images = []

    def repl(m):
        cid = uuid.uuid4().hex
        try:
            raw = base64.b64decode(m.group("data"))
        except Exception:
            return m.group(0)
        images.append((cid, m.group("subtype"), raw))
        return f"cid:{cid}"

    rewritten = _DATA_IMG_RE.sub(repl, html or "")
    return rewritten, images


def build_message(
    *,
    from_addr: str,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    content: str,
    is_html: bool,
    attachments: list[tuple[str, bytes]] | None = None,
) -> EmailMessage:
    """Construct an EmailMessage. attachments: list of (filename, raw_bytes)."""
    msg = EmailMessage()
    msg["From"] = from_addr
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        # send_message() reads + strips Bcc before transmitting.
        msg["Bcc"] = ", ".join(bcc)
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{uuid.uuid4().hex}@fortisoar-smtp>"

    inline = []
    if is_html:
        html, inline = extract_inline_images(content)
        msg.set_content(html_to_text(html))  # text/plain alternative
        msg.add_alternative(html, subtype="html")  # text/html
        html_part = msg.get_payload()[-1]
        for cid, subtype, raw in inline:
            html_part.add_related(raw, maintype="image", subtype=subtype, cid=f"<{cid}>")
    else:
        msg.set_content(content)

    for filename, raw in attachments or []:
        msg.add_attachment(raw, maintype="application", subtype="octet-stream", filename=filename)

    return msg


class SMTPTransport:
    def __init__(self, config: SMTPConfig):
        self.config = config

    def _connect(self) -> smtplib.SMTP:
        c = self.config
        if c.use_ssl:
            server = smtplib.SMTP_SSL(c.host, c.port, timeout=c.timeout, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(c.host, c.port, timeout=c.timeout)
            if c.use_tls:
                server.starttls(context=ssl.create_default_context())
        if c.username:
            server.login(c.username, c.password or "")
        return server

    def verify(self) -> bool:
        """Open a connection (and authenticate if creds given), NOOP, close."""
        server = self._connect()
        try:
            code, _ = server.noop()
            return code == 250
        finally:
            try:
                server.quit()
            except Exception:
                pass

    def send(self, msg: EmailMessage) -> None:
        server = self._connect()
        try:
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:
                pass
