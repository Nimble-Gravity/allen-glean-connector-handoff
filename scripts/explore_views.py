"""Explore the enabled EMS views via the Custom Action API.

Runs a battery of queries (sample rows, distinct values, row counts) against
every enabled view and writes a single JSON report to .outputs/view_exploration.json.

Usage (from repo root, with API running on localhost:8000):
    python scripts/explore_views.py --email you@example.com
    python scripts/explore_views.py --email you@example.com --port 8001

Token is read from CUSTOM_ACTION_API_KEY in .env (or the environment).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


# ── Config ────────────────────────────────────────────────────────────────────

VIEWS = [
    "v_EventInstance_Attendee",
    "v_Catering_TableAssignment",
    "v_Activity_Attendee_TimeRange",
    "v_TravelAir",
    "v_TravelGround",
]

SAMPLE_ROWS = 5  # rows per view for the column inspection

# For each view: which columns to use for distinct-value / cardinality probes
CARDINALITY_PROBES: dict[str, list[str]] = {
    "v_EventInstance_Attendee":    ["EventInstanceID", "AttendeeID"],
    "v_Catering_TableAssignment":  ["EventInstanceID", "AttendeeID", "Activity"],
    "v_Activity_Attendee_TimeRange": ["EventInstanceID", "AttendeeID"],
    "v_TravelAir":                 ["EventInstanceID", "AttendeeID", "TravelRecordTypeName"],
    "v_TravelGround":              ["EventInstanceID", "AttendeeID", "TravelRecordTypeName"],
}

# Pick one AttendeeID from the first view to do a cross-view join drill-down
DRILL_VIEW = "v_EventInstance_Attendee"
DRILL_COLUMN = "AttendeeID"


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_token(env_path: Path) -> str:
    """Read CUSTOM_ACTION_API_KEY from .env file or environment."""
    token = os.environ.get("CUSTOM_ACTION_API_KEY", "")
    if token:
        return token
    if env_path.exists():
        for line in env_path.read_text().splitlines():
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


def api_get(base_url: str, token: str, path: str, params: dict) -> dict:
    """GET {base_url}{path}?{params} with Bearer auth. Returns parsed JSON."""
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{base_url}{path}?{qs}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        return {"_error": f"HTTP {exc.code}", "_detail": body, "_url": url}
    except Exception as exc:
        return {"_error": str(exc), "_url": url}


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Your user email (for API auth)")
    parser.add_argument("--port", default=8000, type=int, help="API port (default 8000)")
    parser.add_argument("--host", default="localhost", help="API host (default localhost)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    token = load_token(repo_root / ".env")
    base_url = f"http://{args.host}:{args.port}"
    email = args.email

    report: dict = {"views": {}, "drill_down": {}}
    total_steps = len(VIEWS) * 3 + 1  # sample + distinct probes + count + drill
    step = 0

    def log(msg: str) -> None:
        nonlocal step
        step += 1
        print(f"[{step:02d}/{total_steps}] {msg}", flush=True)

    for view in VIEWS:
        print(f"\n── {view} ────────────────────────────────────────────")
        entry: dict = {}

        # 1. Sample rows (see all columns + data shape)
        log(f"sample rows ({SAMPLE_ROWS})")
        entry["sample_rows"] = api_get(base_url, token, "/query", {
            "user_email": email,
            "view_name": view,
            "limit": SAMPLE_ROWS,
        })

        # 2. Distinct values for cardinality columns
        distinct: dict = {}
        probes = CARDINALITY_PROBES.get(view, [])
        log(f"distinct probes: {probes}")
        for col in probes:
            distinct[col] = api_get(base_url, token, "/query", {
                "user_email": email,
                "view_name": view,
                "distinct_column": col,
                "limit": 200,
            })
        entry["distinct"] = distinct

        # 3. Row count via aggregate
        log(f"row count")
        # Use the first cardinality column or a generic one
        count_col = probes[0] if probes else "AttendeeID"
        entry["row_count"] = api_get(base_url, token, "/aggregate", {
            "user_email": email,
            "view_name": view,
            "agg_function": "count",
            "agg_column": count_col,
        })

        report["views"][view] = entry

    # 4. Drill-down: pick one AttendeeID and pull all their records across every view
    print(f"\n── Cross-view drill-down ────────────────────────────────────────────")
    log("pick sample AttendeeID for drill-down")

    sample_data = report["views"].get(DRILL_VIEW, {}).get("sample_rows", {})
    rows = sample_data.get("data", [])
    sample_id = rows[0].get(DRILL_COLUMN) if rows else None

    drill: dict = {"attendee_id": sample_id}
    if sample_id:
        for view in VIEWS:
            drill[view] = api_get(base_url, token, "/query", {
                "user_email": email,
                "view_name": view,
                "filter_by_column": "AttendeeID",
                "filter_value": str(sample_id),
                "limit": 50,
            })
    else:
        drill["_note"] = f"No sample {DRILL_COLUMN} found — skipping drill-down"

    report["drill_down"] = drill

    # ── Write output ─────────────────────────────────────────────────────────
    output_dir = repo_root / ".outputs"
    output_dir.mkdir(exist_ok=True)
    out_path = output_dir / "view_exploration.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))

    print(f"\n✓ Report saved to {out_path}")
    print(f"  Views explored : {len(VIEWS)}")
    for view in VIEWS:
        count_resp = report["views"][view].get("row_count", {})
        count_val = count_resp.get("result") or count_resp.get("_error", "?")
        sample_resp = report["views"][view].get("sample_rows", {})
        cols = list((sample_resp.get("data") or [{}])[0].keys()) if sample_resp.get("data") else []
        print(f"  {view}: {count_val} rows, columns: {cols}")


if __name__ == "__main__":
    main()
