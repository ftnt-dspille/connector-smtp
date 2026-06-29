# connector-smtp

A reworked FortiSOAR **SMTP** connector: same actions as the stock connector, but
Django-free, **pydantic-validated**, and every send operation now returns a
**structured result** instead of `None`.

## Why this exists / what changed

The stock SMTP connector borrows `django.core.mail` (Django is on the appliance,
so it was "free") and its operations return nothing. This rewrite:

| Area | Stock connector | This connector |
|---|---|---|
| Transport | `django.core.mail` (full Django dep) | **stdlib `smtplib` + `email`** — zero third-party transport deps (PSF license) |
| Validation | ad-hoc dict access, `KeyError` on optional config | **pydantic v2** models (`SMTPConfig`, `SendEmailParams`) |
| Return value | `None` on success | **`SendResult`** dict: status, message_id, from, recipients, attachments, accepted_count |
| `check_health` | swallows logout errors, returns `None` | real connect + NOOP, returns `True`/raises; **`output_schema` populated** |
| Transport security | STARTTLS only | **STARTTLS *and* implicit SSL (port 465)**, mutually-exclusive validated |
| `port` | passed as string | coerced + validated to `int` |
| Attachment `@id` | bare string mis-iterates char-by-char on the legacy op | **normalized to a list in every op** — a bare `@id` works everywhere |
| Recipient validation | requires To+Subject+Body | requires **at least one** of To/CC/BCC; subject optional |
| Plain-text body | still runs bleach + BeautifulSoup | short-circuits HTML processing |
| HTML→text | `bleach` (Apache-2.0) | `beautifulsoup4` (MIT) with a regex fallback |

All dependencies are permissive: pydantic (MIT), beautifulsoup4 (MIT), Jinja2 (BSD).

## Layout

```
smtp/                 # the FortiSOAR connector package (FSR loads smtp.connector)
  info.json           # manifest: config fields (+ Use SSL), operations, output_schema
  connector.py        # thin Connector adapter (execute / check_health)
  operations.py       # action implementations, return SendResult
  config.py           # SMTPConfig pydantic model
  models.py           # SendEmailParams + SendResult pydantic models
  transport.py        # Django-free smtplib transport + EmailMessage builder
  platform.py         # lazy wrappers for the FSR-only calls (make_request, etc.)
  requirements.txt
harness/run.py        # off-box local runner (config from .env)
tests/                # pytest against an in-process aiosmtpd server
```

## Operations (full parity)

`send_email_new` (Send Email Advanced), `send_email`, `send_richtext_email`
(deprecated), `get_users`, `get_teams`, `get_email_templates`, plus `check_health`.

The platform-coupled paths (User/Team recipients, Email Template body, attachment
IRIs, and the get_* actions) call the FortiSOAR API and only run on-box; off-box
they raise a clear error. Email-address recipients, plain/rich text, local-file
attachments, and inline base64 images all run anywhere.

## Local testing (off-box)

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python -m pytest          # in-process SMTP server, no creds needed

cp .env.example .env                  # edit with your SMTP server
./.venv/bin/python harness/run.py --health
./.venv/bin/python harness/run.py --to you@example.com --subject hi --body "<b>hi</b>"
```

Zero-setup sink (another terminal): `python -m aiosmtpd -n -d -l localhost:1025`,
then set `HOST=localhost PORT=1025 USE_TLS=false` in `.env`.
