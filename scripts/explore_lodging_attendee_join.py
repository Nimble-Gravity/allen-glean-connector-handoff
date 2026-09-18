"""Explore whether per-attendee lodging info can be added to conferenceAttendance.

Context
-------
v_Lodging (rpt) is confirmed as a room-inventory view (EventInstanceID grain, no AttendeeID).
The colleague proposal: enrich each event on the attendee document with lodging details.

For that to work we need a bridge view that maps:
    AttendeeID  →  EventInstanceAccommodationRoomID  (or AccommodationRoomID)

The strongest candidates visible in the API schema are:
    - v_CDC_Attendee_AccommodationRoom  (name reads "attendee → room assignment")
    - v_EventInstance_AccommodationRoom (conference-level; may or may not carry AttendeeID)
    - v_Accommodation_Room              (room master data — likely no AttendeeID)

This script:
1. Fetches columns + sample rows for each candidate via /metadata and /query.
2. Reports whether AttendeeID is present and what join keys exist.
3. Checks join cardinality (rows per attendee-event pair).
4. Confirms whether v_Lodging columns can be resolved via the bridge join key
   (EventInstanceAccommodationRoomID).
5. Writes evidence to .outputs/lodging_attendee_join_exploration.json.

Usage (API running, from repo root)::

    python scripts/explore_lodging_attendee_join.py
    python scripts/explore_lodging_attendee_join.py --port 8001
    python scripts/explore_lodging_attendee_join.py --email you@example.com

Token is read from CUSTOM_ACTION_API_KEY in .env (or the environment).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


# ── Views to probe ─────────────────────────────────────────────────────────────

BRIDGE_VIEWS = [
    {
        "schema": "rpt",
        "view": "v_CDC_Attendee_AccommodationRoom",
        "hypothesis": "Primary bridge: maps AttendeeID → room assignment (CDC = change-data-capture cross-ref)",
    },
    {
        "schema": "rpt",
        "view": "v_EventInstance_AccommodationRoom",
        "hypothesis": "Conference-level room assignments; may carry AttendeeID or only EventInstanceID",
    },
    {
        "schema": "rpt",
        "view": "v_Accommodation_Room",
        "hypothesis": "Room master data (no AttendeeID expected, but check join keys vs v_Lodging)",
    },
]

# Join keys we expect to find linking back to v_Lodging
LODGING_JOIN_CANDIDATES = (
    "EventInstanceAccommodationRoomID",
    "AccommodationRoomID",
    "AccommodationID",
    "EventInstanceID",
)

ATTENDEE_KEY = "AttendeeID"
EVENT_KEY = "EventInstanceID"

SAMPLE_ROWS = 10
DISTINCT_LIMIT = 40

# v_Lodging stats from existing exploration for cross-reference
V_LODGING_JOIN_KEYS = {"EventInstanceID", "AccommodationID", "EventInstanceAccommodationRoomID"}


# ── HTTP helpers ───────────────────────────────────────────────────────────────


def load_token(env_path: Path) -> str:
    token = os.environ.get("CUSTOM_ACTION_API_KEY", "")
    if token:
        return token
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            if key.strip() == "CUSTOM_ACTION_API_KEY":
                token = val.strip().strip('"').strip("'")
                if token and token != "your-custom-action-api-key":
                    return token
    sys.exit(
        "ERROR: CUSTOM_ACTION_API_KEY not found in environment or .env — "
        "set it before running this script."
    )


def api_get(base_url: str, token: str, path: str, params: dict, timeout: int = 90) -> dict:
    qs = urllib.parse.urlencode(
        {k: v for k, v in params.items() if v is not None},
        doseq=True,
    )
    url = f"{base_url}{path}?{qs}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        return {"_error": f"HTTP {exc.code}", "_detail": body[:800], "_url": url}
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc), "_url": url}


def ok(resp: dict) -> bool:
    return "_error" not in resp


def columns_from_metadata(resp: dict) -> list[str]:
    cols = resp.get("columns") or []
    names: list[str] = []
    for col in cols:
        if isinstance(col, dict):
            name = col.get("column_name") or col.get("name")
            if name:
                names.append(str(name))
        elif isinstance(col, str):
            names.append(col)
    return names


def fill_rates(rows: list[dict]) -> dict[str, float]:
    if not rows:
        return {}
    keys = list(rows[0].keys())
    n = len(rows)
    return {
        k: round(sum(1 for r in rows if r.get(k) not in (None, "", [])) / n, 3)
        for k in keys
    }


def present_keys(columns: list[str], candidates: tuple[str, ...]) -> list[str]:
    lower = {c.lower(): c for c in columns}
    return [lower[cand.lower()] for cand in candidates if cand.lower() in lower]


# ── Probe one view ─────────────────────────────────────────────────────────────


def probe_view(
    base_url: str,
    token: str,
    schema: str,
    view: str,
    hypothesis: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "hypothesis": hypothesis,
        "schema": schema,
        "columns_status": "pending",
        "columns": [],
        "has_attendee_id": False,
        "lodging_join_keys_present": [],
        "sample_rows": [],
        "fill_rates": {},
        "cardinality": {},
        "verdict": "",
    }

    # 1. Metadata / columns
    meta = api_get(base_url, token, "/metadata", {"view_name": view})
    if not ok(meta):
        result["columns_status"] = "error"
        result["columns_error"] = meta
        result["verdict"] = "BLOCKED — view not accessible via API"
        return result

    columns = columns_from_metadata(meta)
    result["columns_status"] = "ok"
    result["columns"] = columns
    result["has_attendee_id"] = any(c.lower() == ATTENDEE_KEY.lower() for c in columns)
    result["has_event_instance_id"] = any(c.lower() == EVENT_KEY.lower() for c in columns)
    result["lodging_join_keys_present"] = present_keys(columns, LODGING_JOIN_CANDIDATES)

    # 2. Sample rows
    sample_resp = api_get(
        base_url, token, "/query",
        {"view_name": view, "limit": SAMPLE_ROWS},
    )
    if ok(sample_resp):
        rows = sample_resp.get("rows") or []
        result["sample_rows"] = rows
        result["fill_rates"] = fill_rates(rows)

    # 3. Cardinality: rows per AttendeeID (if present)
    if result["has_attendee_id"]:
        agg = api_get(
            base_url, token, "/aggregate",
            {
                "view_name": view,
                "group_by": ATTENDEE_KEY,
                "aggregation": "count",
                "column_name": ATTENDEE_KEY,
                "sort_column": "count",
                "sort_order": "DESC",
                "limit": DISTINCT_LIMIT,
            },
        )
        if ok(agg):
            result["cardinality"]["rows_per_attendee"] = {
                "top_groups": (agg.get("rows") or [])[:10],
                "note": "count = number of lodging assignment rows per AttendeeID",
            }

    # 4. Cardinality: rows per (AttendeeID, EventInstanceID) if both present
    if result["has_attendee_id"] and result["has_event_instance_id"]:
        # Proxy: count per EventInstanceID to see conference sizes
        agg2 = api_get(
            base_url, token, "/aggregate",
            {
                "view_name": view,
                "group_by": EVENT_KEY,
                "aggregation": "count",
                "column_name": EVENT_KEY,
                "sort_column": "count",
                "sort_order": "DESC",
                "limit": 15,
            },
        )
        if ok(agg2):
            result["cardinality"]["rows_per_event"] = {
                "top_groups": (agg2.get("rows") or [])[:8],
            }

    # 5. Verdict
    has_attendee = result["has_attendee_id"]
    has_join_key = bool(result["lodging_join_keys_present"])

    if has_attendee and has_join_key:
        join_keys = ", ".join(result["lodging_join_keys_present"])
        result["verdict"] = (
            f"JOIN FEASIBLE — has AttendeeID and shared key(s) with v_Lodging: [{join_keys}]. "
            f"Can enrich conferenceAttendance.events[].lodging by joining on {join_keys}."
        )
    elif has_attendee and not has_join_key:
        result["verdict"] = (
            "PARTIAL — has AttendeeID but no direct join key to v_Lodging columns. "
            "Need an intermediate key or a different bridge view."
        )
    elif not has_attendee and has_join_key:
        result["verdict"] = (
            "CONFERENCE-LEVEL ONLY — no AttendeeID; links to v_Lodging but cannot "
            "resolve per-attendee room. Useful for conference-wide lodging inventory only."
        )
    else:
        result["verdict"] = (
            "NO JOIN — neither AttendeeID nor a recognized v_Lodging join key found. "
            "This view cannot bridge lodging to attendees."
        )

    return result


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--email", default="", help="Ignored; kept for parity with other scripts.")
    args = parser.parse_args()

    base_url = f"http://localhost:{args.port}"
    env_path = Path(__file__).parent.parent / ".env"
    token = load_token(env_path)

    print(f"API: {base_url}")
    print(f"Goal: find the bridge view that maps AttendeeID → lodging room\n")

    output: dict[str, Any] = {
        "goal": (
            "Determine whether v_Lodging lodging info can be added to the "
            "conferenceAttendance attendee document, and which bridge view makes that join."
        ),
        "v_lodging_summary": {
            "grain": "conference-level (EventInstanceID)",
            "has_attendee_id": False,
            "confirmed_join_keys": list(V_LODGING_JOIN_KEYS),
            "row_count": 26272,
            "note": "Full exploration already in document_candidate_exploration.json",
        },
        "bridge_view_results": {},
        "recommendation": "",
    }

    for spec in BRIDGE_VIEWS:
        view = spec["view"]
        print(f"Probing {spec['schema']}.{view} ...")
        result = probe_view(base_url, token, spec["schema"], view, spec["hypothesis"])
        output["bridge_view_results"][f"{spec['schema']}.{view}"] = result
        print(f"  → {result['verdict']}\n")

    # Overall recommendation
    feasible = [
        (k, v)
        for k, v in output["bridge_view_results"].items()
        if "JOIN FEASIBLE" in v.get("verdict", "")
    ]
    if feasible:
        bridge_key = feasible[0][0]
        bridge_result = feasible[0][1]
        join_keys = bridge_result.get("lodging_join_keys_present", [])
        output["recommendation"] = (
            f"FEASIBLE. Bridge view: {bridge_key}. "
            f"Join key(s) shared with v_Lodging: {join_keys}. "
            f"Implementation: in the indexer's document builder, for each event row, "
            f"LEFT JOIN {bridge_key} ON AttendeeID + EventInstanceID, then join to v_Lodging "
            f"on {join_keys[0] if join_keys else 'the shared key'} to pull room details "
            f"(Accommodation, RoomNumber, RoomType, BegBookingDate, EndBookingDate) "
            f"into body.events[].lodging."
        )
    else:
        partial = [
            (k, v)
            for k, v in output["bridge_view_results"].items()
            if "PARTIAL" in v.get("verdict", "") or "CONFERENCE-LEVEL" in v.get("verdict", "")
        ]
        if partial:
            output["recommendation"] = (
                "NOT DIRECTLY FEASIBLE with available views. "
                "No single view maps AttendeeID → lodging room via a key present in v_Lodging. "
                "Options: (a) request dbo.v_Lodging_Assignment from the client (it was listed "
                "in the original email but is not in the rpt schema); "
                "(b) query v_EventInstance_AccommodationRoom + a second join through AttendeeID "
                "if a room-assignment table is available in another schema."
            )
        else:
            output["recommendation"] = (
                "BLOCKED — none of the bridge candidates are accessible via the API. "
                "Check if these views exist in the rpt schema or ask the client for "
                "dbo.v_Lodging_Assignment which was in the original view list."
            )

    out_dir = Path(__file__).parent.parent / ".outputs"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "lodging_attendee_join_exploration.json"
    out_file.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")

    print("=" * 60)
    print(f"RECOMMENDATION: {output['recommendation']}")
    print(f"\nFull results → {out_file}")


if __name__ == "__main__":
    main()
