#!/usr/bin/env python
"""One-shot DB connection diagnostic for the dev workstation.

Run from the repo root with the venv active:

    python scripts/check_db.py

Reads the shared .env, prints the effective TLS/driver config and the (password-
masked) connection string, then attempts a real connection (SELECT 1) and the four
EMS views. Output is a handful of short lines on purpose — designed for a locked-down
workstation with no copy/paste, so you can read the result back easily.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

# override=True: the .env file is authoritative for this diagnostic, so a stale
# shell variable can't mask what you actually set in the file.
load_dotenv(dotenv_path=ROOT / ".env", override=True)

import pyodbc  # noqa: E402

from config.config import load_db_settings  # noqa: E402
from allenco_connector.db_connection import build_connection_string  # noqa: E402

VIEWS = ["v_Attendee", "v_Attendee_Event", "v_Company", "v_Participation"]


def main() -> int:
    print("=== DB CHECK ===")
    print("installed drivers :", pyodbc.drivers())
    print("DB_DRIVER         :", repr(os.environ.get("DB_DRIVER")))
    print("DB_SERVER         :", repr(os.environ.get("DB_SERVER")))
    print("DB_NAME           :", repr(os.environ.get("DB_NAME")))
    print("DB_AUTH_MODE      :", repr(os.environ.get("DB_AUTH_MODE")))
    print("TRUST_SERVER_CERT :", repr(os.environ.get("DB_TRUST_SERVER_CERTIFICATE")))

    try:
        settings = load_db_settings()
    except Exception as exc:  # missing/invalid config
        print("CONFIG ERROR      :", exc)
        return 2

    conn_str = build_connection_string(settings, connect_timeout=5)
    masked = conn_str.replace(settings.password, "***") if settings.password else conn_str
    print("CONN STRING       :", masked)

    try:
        conn = pyodbc.connect(conn_str, timeout=5)
    except Exception as exc:
        print("RESULT: FAIL (could not connect)")
        print("ERROR             :", str(exc)[:400])
        return 1

    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        print("CONNECT           : PASS (SELECT 1 ->", cur.fetchone()[0], ")")
        for view in VIEWS:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {view}")
                print(f"  {view:<20}: {cur.fetchone()[0]} rows")
            except Exception as exc:
                print(f"  {view:<20}: ERROR {str(exc)[:120]}")
    finally:
        conn.close()

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
