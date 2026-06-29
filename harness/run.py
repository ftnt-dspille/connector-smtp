#!/usr/bin/env python3
"""Local runner for the SMTP connector — off-box, config from a .env file.

Only the FortiSOAR `Connector` base class is stubbed (the send path is pure
stdlib + pydantic and needs nothing else). Platform-coupled actions
(User/Team recipients, Email Template body, attachment IRIs) raise a clear
error locally.

    cp .env.example .env          # edit with your SMTP settings
    python harness/run.py --health
    python harness/run.py --to you@example.com --subject hi --body "<b>hi</b>"
    python harness/run.py --to you@example.com --plain --body "hi"

Zero-setup local sink (another terminal):
    python -m aiosmtpd -n -d -l localhost:1025
then HOST=localhost PORT=1025 USE_TLS=false in .env.
"""
import argparse
import os
import sys
import types
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")


def _stub_connector_base():
    pkg = types.ModuleType("connectors"); pkg.__path__ = []
    core = types.ModuleType("connectors.core"); core.__path__ = []
    conn = types.ModuleType("connectors.core.connector")

    class Connector:  # noqa
        pass

    import logging
    conn.Connector = Connector
    conn.get_logger = logging.getLogger
    sys.modules.update({"connectors": pkg, "connectors.core": core,
                        "connectors.core.connector": conn})


def build_config():
    b = lambda v: str(v).strip().lower() in ("1", "true", "yes", "on")
    if not os.environ.get("HOST"):
        sys.exit("ERROR: HOST not set — copy .env.example to .env and edit it.")
    return {
        "host": os.environ["HOST"],
        "port": os.environ.get("PORT", "25"),
        "username": os.environ.get("USERNAME", ""),
        "password": os.environ.get("PASSWORD", ""),
        "useTLS": b(os.environ.get("USE_TLS", "false")),
        "useSSL": b(os.environ.get("USE_SSL", "false")),
        "default_from": os.environ.get("DEFAULT_FROM", ""),
        "timeout": int(os.environ.get("TIMEOUT", "10")),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--health", action="store_true")
    ap.add_argument("--to"); ap.add_argument("--cc", default=""); ap.add_argument("--bcc", default="")
    ap.add_argument("--from", dest="from_", default="")
    ap.add_argument("--subject", default="SMTP connector local test")
    ap.add_argument("--body", default="<h3>It works</h3>")
    ap.add_argument("--plain", action="store_true")
    ap.add_argument("--op", choices=["send_email_new", "send_email"], default="send_email_new")
    args = ap.parse_args()

    _stub_connector_base()
    from smtp.connector import SMTP

    config = build_config()
    conn = SMTP()
    print(f"Config: host={config['host']} port={config['port']} "
          f"useTLS={config['useTLS']} useSSL={config['useSSL']} from={config['default_from'] or '(none)'}")

    print("\n== check_health ==")
    try:
        print("Health:", "OK" if conn.check_health(config) else "FAILED")
    except Exception as e:
        print("Health FAILED:", e)
        if args.health:
            sys.exit(1)
    if args.health:
        return

    if not args.to:
        sys.exit("ERROR: --to required (or use --health).")
    params = {
        "type": "Manual Input", "to": args.to, "cc": args.cc, "bcc": args.bcc,
        "from": args.from_, "subject": args.subject,
        "body_type": "Plain Text" if args.plain else "Rich Text", "content": args.body,
    }
    print(f"\n== {args.op} ==")
    import json
    print(json.dumps(conn.execute(config, args.op, params, env={}), indent=2))


if __name__ == "__main__":
    main()
