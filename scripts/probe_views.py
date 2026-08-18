#!/usr/bin/env python
"""Probe views with ``SELECT TOP (1)`` to see which actually BIND on this instance.

The rpt report views are heavily layered and often join across sibling databases
(e.g. ``ConferenceImage.dbo.Attendee_Picture``). If a referenced database is not
present/accessible on this read replica, the view fails to bind (SQL error 4413 /
208 "Invalid object name") and a plain ``SELECT *`` raises — even though the view's
own definition looks self-contained (the missing reference is in a nested view).

This probe runs, on the VM, a real ``SELECT TOP (1) *`` against:
  1. every view in the connector catalog (VIEW_CATALOG), enabled or not; and
  2. a few Tier-1/Tier-2 candidate views worth comparing; and
  3. (optionally, with ``--all-rpt``) every ``rpt`` view,

reporting OK / FAIL per view plus, at the end, the set of **missing objects** the
failures name — the precise list to hand the client ("the replica needs read access
to these databases/objects"). Read-only; a per-query timeout bounds heavy views.

    python scripts/probe_views.py            # catalog + candidates
    python scripts/probe_views.py --all-rpt  # + every rpt view (client-facing tally)
"""

import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=ROOT / ".env", override=True)

import pyodbc  # noqa: E402

from allenco_connector.db_connection import get_connection  # noqa: E402
from allenco_connector.views.catalog import VIEW_CATALOG  # noqa: E402
from config.config import load_db_settings  # noqa: E402

# Tier-1 / Tier-2 alternates worth comparing when a primary view won't bind.
_CANDIDATES = (
    ("rpt", "v_Attendee"),
    ("rpt", "v_EventInstance_Attendee"),
    ("rpt", "v_Invitation_History"),
    ("rpt", "v_Attendee_Event_LocalStaff"),
    ("rpt", "v_Attendee_ContactInformation"),
)

_QUERY_TIMEOUT_S = 30  # bound heavy/complex views so the probe never hangs
_MISSING_OBJECT = re.compile(r"Invalid object name '([^']+)'", re.I)


def _missing_objects(err: str) -> list[str]:
    return _MISSING_OBJECT.findall(err)


def _db_part(object_name: str) -> str | None:
    """The database part of a 3-/4-part name (e.g. ConferenceImage.dbo.X -> ConferenceImage)."""
    parts = [p.strip("[]") for p in object_name.split(".")]
    return parts[0] if len(parts) >= 3 and parts[0] else None


def _probe_one(cur: "pyodbc.Cursor", schema: str, name: str) -> tuple[bool, str]:
    try:
        cur.execute(f"SELECT TOP (1) * FROM [{schema}].[{name}]")
        row = cur.fetchone()
        ncols = len(cur.description) if cur.description else 0
        return True, f"{ncols} cols, {'has rows' if row else 'empty'}"
    except Exception as exc:  # noqa: BLE001 - report every failure kind
        return False, str(exc).replace("\n", " ").strip()


def main() -> int:
    print("=== VIEW BIND PROBE ===")
    all_rpt = "--all-rpt" in sys.argv[1:]
    try:
        settings = load_db_settings()
    except Exception as exc:
        print("CONFIG ERROR:", exc)
        return 2
    try:
        # get_connection registers the DATETIMEOFFSET output converter, so the probe
        # reflects the real connector (a -155 column no longer shows a false FAIL).
        conn = get_connection(settings, connect_timeout=15, retry_attempts=1)
    except Exception as exc:
        print("RESULT: FAIL (could not connect):", str(exc)[:300])
        return 1
    conn.timeout = _QUERY_TIMEOUT_S
    cur = conn.cursor()

    # Build the target list: catalog views, then candidates, then (optional) all rpt.
    targets: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(schema: str, name: str, kind: str) -> None:
        key = (schema, name)
        if key not in seen:
            seen.add(key)
            targets.append((schema, name, kind))

    for e in VIEW_CATALOG:
        _add(
            e.schema or settings.schema,
            e.view_name,
            "catalog" + ("" if e.enabled else " (disabled)"),
        )
    for schema, name in _CANDIDATES:
        _add(schema, name, "candidate")

    if all_rpt:
        cur.execute(
            "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_SCHEMA = 'rpt' "
            "ORDER BY TABLE_NAME"
        )
        for (name,) in cur.fetchall():
            _add("rpt", name, "rpt")

    missing = collections.Counter()
    missing_dbs = collections.Counter()
    ok = bad = 0
    for schema, name, kind in targets:
        bound, info = _probe_one(cur, schema, name)
        if bound:
            ok += 1
            print(f"OK    {schema}.{name}  [{kind}]  — {info}")
        else:
            bad += 1
            print(f"FAIL  {schema}.{name}  [{kind}]  — {info[:220]}")
            for obj in _missing_objects(info):
                missing[obj] += 1
                db = _db_part(obj)
                if db:
                    missing_dbs[db] += 1

    conn.close()

    print(f"\n=== {ok} OK, {bad} FAIL (of {len(targets)} probed) ===")
    if missing_dbs:
        print("\nMissing DATABASES referenced by failing views (ask the client for read access):")
        for db, c in missing_dbs.most_common():
            print(f"    {db}  (named by {c} failing view(s))")
    if missing:
        print("\nMissing OBJECTS named in the errors:")
        for obj, c in missing.most_common():
            print(f"    {obj}  (×{c})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
