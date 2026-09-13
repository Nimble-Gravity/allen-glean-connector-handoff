"""Discover which client-listed EMS views can become new Glean document types.

Purpose
-------
The indexer already builds one document kind — ``conferenceAttendance`` — a
person-centric profile aggregated from five ``rpt`` views. The client has now
named a larger set of views (lodging, invitations, vendors, event identity,
etc.). This script asks the **same Custom Action API** a Glean agent would use
(``/metadata``, ``/query``, ``/aggregate``) to answer, per view:

  * Does it bind and return rows through the API's configured schema?
  * What is the grain (conference / attendee / company) and join keys?
  * Which columns would make a human title and which look like PII?
  * Is the data already inside ``conferenceAttendance``, or is it a new entity?
  * What agent questions would a dedicated document (or an enrichment) unlock?

It does **not** index anything. It writes evidence to
``.outputs/document_candidate_exploration.json`` so document-type decisions are
driven by real columns and cardinalities, not the view name alone.

Limitation
----------
The Custom Action API qualifies every view as ``[DB_SCHEMA].[view]`` (typically
``rpt``). Views the client listed under ``dbo`` will 404 unless they also exist
in that schema. The report flags those as ``not_in_api_schema`` so you can
follow up (temporarily point the API at ``dbo``, or add a schema parameter).

Usage (API running, from repo root)::

    python scripts/explore_document_candidates.py --email you@example.com
    python scripts/explore_document_candidates.py --email you@example.com --port 8001
    python scripts/explore_document_candidates.py --email you@example.com --skip-drill

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


# ── Client view list (from the EMS views email) ────────────────────────────────
# grouping: 1 = conference, 2 = attendee (global), 1,2 = per guest at a conference,
# 1,3 = vendor/company at a conference, 3 = company.

CLIENT_VIEWS: tuple[dict[str, Any], ...] = (
    # Lodging
    {"schema": "dbo", "view": "v_Lodging_Assignment", "category": "lodging", "grouping": "1,2"},
    {"schema": "rpt", "view": "v_Lodging", "category": "lodging", "grouping": "1"},
    # Travel
    {"schema": "rpt", "view": "v_Travel", "category": "travel", "grouping": "1,2"},
    {"schema": "rpt", "view": "v_TravelAir", "category": "travel", "grouping": "1,2"},
    {"schema": "rpt", "view": "v_TravelGround", "category": "travel", "grouping": "1,2"},
    {"schema": "rpt", "view": "v_Travel_CarService", "category": "travel", "grouping": "1,2"},
    # Activities
    {"schema": "dbo", "view": "v_Activity_Event", "category": "activities", "grouping": "1"},
    {"schema": "dbo", "view": "v_Activity_Attendee", "category": "activities", "grouping": "1,2"},
    {"schema": "dbo", "view": "v_Activity_Atttendee", "category": "activities", "grouping": "1,2",
     "note": "Spelling from the client email (three t's); probed in case it is the real name."},
    # Catering
    {"schema": "rpt", "view": "v_Catering_Meal", "category": "catering", "grouping": "1"},
    {"schema": "rpt", "view": "v_Catering_TableAssignment", "category": "catering", "grouping": "1,2"},
    # Child care
    {"schema": "dbo", "view": "v_Children_ChildCare", "category": "childcare", "grouping": "1,2"},
    # Invitations
    {"schema": "rpt", "view": "v_Invitation_History", "category": "invitations", "grouping": "1,2"},
    {"schema": "rpt", "view": "v_Invitation_CurrentStatus", "category": "invitations", "grouping": "1,2"},
    # Vendors
    {"schema": "rpt", "view": "v_Vendor_Admin_Summary", "category": "vendors", "grouping": "1,3"},
    {"schema": "rpt", "view": "v_Vendor_Requirements", "category": "vendors", "grouping": "1,3"},
    {"schema": "rpt", "view": "v_Vendor_RequirementStatus_Company", "category": "vendors", "grouping": "1,3"},
    {"schema": "rpt", "view": "v_Vendor_RequirmentsStatus_Employee", "category": "vendors", "grouping": "1,2",
     "note": "Spelling from the client email (Requirments)."},
    {"schema": "rpt", "view": "v_Vendor_RequirementsStatus_Employee", "category": "vendors", "grouping": "1,2",
     "note": "Corrected spelling probe."},
    # Guest
    {"schema": "rpt", "view": "v_Attendee", "category": "guest", "grouping": "2"},
    {"schema": "rpt", "view": "v_EventInstance_Attendee", "category": "guest", "grouping": "1,2"},
    {"schema": "rpt", "view": "v_Attendee_ContactInformation", "category": "guest", "grouping": "2"},
    {"schema": "rpt", "view": "v_Attendee_GarmentTypeGroup", "category": "guest", "grouping": "1,2"},
    {"schema": "dbo", "view": "v_Attendee_Note", "category": "guest", "grouping": "1,2"},
    {"schema": "dbo", "view": "v_Attendee_Host_List", "category": "guest", "grouping": "2"},
    {"schema": "dbo", "view": "v_Attendee_Suggestor_List", "category": "guest", "grouping": "1,2"},
    # Event information
    {"schema": "dbo", "view": "v_EventInstance", "category": "event", "grouping": "1"},
    {"schema": "dbo", "view": "v_EventInstance_Current", "category": "event", "grouping": "1"},
)

# Already folded into conferenceAttendance (see document_builder.py).
INGESTED_INTO_ATTENDANCE: frozenset[str] = frozenset(
    {
        "v_EventInstance_Attendee",
        "v_Catering_TableAssignment",
        "v_Activity_Attendee_TimeRange",
        "v_TravelAir",
        "v_TravelGround",
    }
)

EXISTING_KIND = "conferenceAttendance"
EXISTING_GRAIN = "one document per AttendeeID (all EventInstanceID rows nested in body.events)"

SAMPLE_ROWS = 8
DISTINCT_LIMIT = 80
DRILL_LIMIT = 25

_KEY_CANDIDATES = (
    "EventInstanceID",
    "AttendeeID",
    "CompanyID",
    "VendorID",
    "VendorCompanyID",
    "ActivityID",
    "EventInstanceActivityID",
    "RecordID",
    "InvitationID",
    "LodgingAssignmentID",
    "AccommodationID",
    "ChildID",
    "EmployeeID",
)

_TITLE_HINTS = (
    "formalname",
    "preferredname",
    "firstname",
    "lastname",
    "displayname",
    "eventinstanceshort",
    "eventinstance",
    "eventyear",
    "eventname",
    "companyname",
    "vendorname",
    "activity",
    "session",
    "airline",
    "flight",
    "hotel",
    "propertyname",
    "accommodation",
    "status",
    "invitationstatus",
)

_PII_HINTS = (
    "email",
    "phone",
    "mobile",
    "fax",
    "address",
    "street",
    "city",
    "zip",
    "postal",
    "ssn",
    "passport",
    "dob",
    "birth",
    "picture",
    "photo",
    "note",
    "comment",
    "allergy",
    "dietary",
)

_CURRENT_CONF_VIEWS = ("v_EventInstance_Current", "v_EventInstance")


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
    except Exception as exc:  # noqa: BLE001 — report every transport failure
        return {"_error": str(exc), "_url": url}


def _ok(resp: dict) -> bool:
    return "_error" not in resp


def _http_code(resp: dict) -> int | None:
    err = str(resp.get("_error") or "")
    if err.startswith("HTTP "):
        try:
            return int(err.split()[1])
        except (IndexError, ValueError):
            return None
    return None


def _columns_from_metadata(resp: dict) -> list[str]:
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


def _pick(columns: list[str], *candidates: str) -> str | None:
    lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None


def _present_keys(columns: list[str]) -> list[str]:
    lower = {c.lower(): c for c in columns}
    found = []
    for cand in _KEY_CANDIDATES:
        if cand.lower() in lower:
            found.append(lower[cand.lower()])
    return found


def _title_like(columns: list[str]) -> list[str]:
    hits = [c for c in columns if any(h in c.lower() for h in _TITLE_HINTS)]
    return hits[:12]


def _pii_like(columns: list[str]) -> list[str]:
    return [c for c in columns if any(h in c.lower() for h in _PII_HINTS)]


def _fill_rates(rows: list[dict]) -> dict[str, float]:
    if not rows:
        return {}
    keys = list(rows[0].keys())
    rates: dict[str, float] = {}
    n = len(rows)
    for key in keys:
        filled = sum(1 for r in rows if r.get(key) not in (None, "", []))
        rates[key] = round(filled / n, 3)
    return rates


def _status(resp: dict, client_schema: str, api_views: set[str], view: str) -> str:
    if _ok(resp):
        return "ok"
    code = _http_code(resp)
    if code == 404 or view not in api_views:
        if client_schema != "rpt":
            return "not_in_api_schema"
        return "not_found"
    if code == 403:
        return "forbidden"
    if code == 500:
        return "bind_or_query_error"
    return "error"


def _relation_to_existing(view: str, grouping: str, status: str) -> str:
    if status != "ok":
        return "unknown_until_queryable"
    if view in INGESTED_INTO_ATTENDANCE:
        return (
            "already_in_conferenceAttendance — only add a new kind if this view "
            "has fields the current builder drops, or a different grain is needed"
        )
    if grouping == "2":
        return "new_entity — global attendee facts (not conference-scoped)"
    if grouping == "1":
        return "new_entity — conference-level (not nested under a guest)"
    if grouping == "1,3":
        return "new_entity — vendor/company at a conference"
    if grouping == "1,2":
        return (
            "candidate_enrichment_or_kind — same guest×conference grain as "
            "conferenceAttendance body.events; prefer enriching that profile "
            "unless the topic is a first-class entity (lodging stay, invitation)"
        )
    return "review"


def _agent_questions(category: str, grouping: str) -> list[str]:
    by_cat: dict[str, list[str]] = {
        "event": [
            "What is the current conference, and what is its EventInstanceID?",
            "What is the human name/code (e.g. SV26) for event N?",
            "When does this conference start and end?",
        ],
        "invitations": [
            "Was this person invited to conference X, and what is their status?",
            "Who is confirmed / declined / pending for the current conference?",
            "What is this guest's invitation history across years?",
        ],
        "lodging": [
            "Where is this guest staying, and on which nights?",
            "Which hotel/room is assigned for attendee X at the current conference?",
            "How many lodging assignments exist for conference X?",
        ],
        "travel": [
            "What is the full itinerary (air, ground, car service) for this guest?",
            "Who is on the Allen plane / which flight?",
            "What car-service pickup is scheduled, and where?",
        ],
        "activities": [
            "What activities are offered at this conference (catalog, not RSVP)?",
            "Which activities is this guest registered for, and when?",
        ],
        "catering": [
            "Where is this guest seated for dinner?",
            "What meals are being served (menu/session), not just table numbers?",
            "What dietary notes apply to this guest?",
        ],
        "childcare": [
            "Does this guest have childcare booked, for which children, when?",
        ],
        "guest": [
            "Who is this person globally (company, role, contact)?",
            "Who is hosting / who suggested this guest?",
            "Are there coordinator notes that change how we treat this guest?",
        ],
        "vendors": [
            "Which vendors are hired for this conference?",
            "Is this vendor company compliant with requirements?",
            "What is the requirement status of a vendor employee?",
        ],
    }
    questions = list(by_cat.get(category, []))
    if grouping == "1":
        questions.append("Scope answers to one EventInstanceID (current conference by default).")
    return questions


def _proposed_kind(view: str, category: str, grouping: str, status: str) -> dict[str, Any] | None:
    if status != "ok" or view in INGESTED_INTO_ATTENDANCE:
        return None
    mapping: dict[tuple[str, str], dict[str, Any]] = {
        ("event", "1"): {
            "object_type": "conference",
            "grain": "one document per EventInstanceID",
            "priority": "P0",
            "why": "Agents cannot answer 'current conference' or map IDs to SV26 without this.",
        },
        ("invitations", "1,2"): {
            "object_type": "invitationStatus",
            "grain": "one document per (AttendeeID, EventInstanceID)",
            "priority": "P0",
            "why": "Headline yes/no: was this person invited / confirmed for this conference.",
        },
        ("lodging", "1,2"): {
            "object_type": "lodgingStay",
            "grain": "one document per (AttendeeID, EventInstanceID) aggregating assignment rows",
            "priority": "P1",
            "why": "Stay details are not in the attendance profile today.",
        },
        ("lodging", "1"): {
            "object_type": "conferenceLodging",
            "grain": "one document per EventInstanceID (inventory/summary) or merge into conference",
            "priority": "P2",
            "why": "Conference-level lodging facts; prefer merging into conference unless large.",
        },
        ("travel", "1,2"): {
            "object_type": None,
            "grain": "enrich conferenceAttendance.events[].travel",
            "priority": "P1",
            "why": "Same guest×conference grain as the existing profile; add car-service / v_Travel there.",
        },
        ("activities", "1"): {
            "object_type": "conferenceActivity",
            "grain": "one document per (EventInstanceID, activity key)",
            "priority": "P1",
            "why": "Catalog of what is offered — distinct from who registered.",
        },
        ("activities", "1,2"): {
            "object_type": None,
            "grain": "enrich conferenceAttendance.events[].activity_schedule",
            "priority": "P1",
            "why": "Attendee activity rows belong on the existing profile (today the builder keeps only times).",
        },
        ("catering", "1"): {
            "object_type": "conferenceMeal",
            "grain": "one document per (EventInstanceID, meal/session)",
            "priority": "P1",
            "why": "Menu/session catalog; table assignment is already nested on the guest profile.",
        },
        ("childcare", "1,2"): {
            "object_type": "childcareBooking",
            "grain": "one document per (AttendeeID, EventInstanceID) or per child",
            "priority": "P2",
            "why": "Operational Q&A that does not belong on every attendance profile.",
        },
        ("guest", "2"): {
            "object_type": "attendeeIdentity",
            "grain": "one document per AttendeeID (global)",
            "priority": "P1",
            "why": "Stable identity + contact; trim PII. conferenceAttendance is conference-history, not CRM.",
        },
        ("guest", "1,2"): {
            "object_type": None,
            "grain": "enrich conferenceAttendance or skip (garment/notes)",
            "priority": "P2",
            "why": "Notes/hosts/garment: only index if sample rows show coordinator-facing facts agents need.",
        },
        ("vendors", "1,3"): {
            "object_type": "vendorCompany",
            "grain": "one document per (CompanyID, EventInstanceID)",
            "priority": "P2",
            "why": "Different entity than guests; answers vendor-hire and compliance questions.",
        },
        ("vendors", "1,2"): {
            "object_type": "vendorEmployee",
            "grain": "one document per (employee key, EventInstanceID)",
            "priority": "P3",
            "why": "Only if employee-level requirement status is asked in Glean.",
        },
    }
    return mapping.get((category, grouping))


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True, help="User email for Custom Action auth")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--host", default="localhost")
    parser.add_argument(
        "--skip-drill",
        action="store_true",
        help="Skip the current-conference + one-attendee cross-view drill (faster).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    token = load_token(repo_root / ".env")
    base_url = f"http://{args.host}:{args.port}"
    email = args.email

    report: dict[str, Any] = {
        "purpose": (
            "Find which client-listed EMS views can become new Glean document "
            f"types, using Custom Actions, relative to existing kind {EXISTING_KIND}."
        ),
        "existing_document": {
            "object_type": EXISTING_KIND,
            "grain": EXISTING_GRAIN,
            "source_views": sorted(INGESTED_INTO_ATTENDANCE),
            "document_id_pattern": "attendee::{AttendeeID}",
        },
        "api": {"base_url": base_url, "schema_note": "API uses DB_SCHEMA for every view"},
        "available_views_in_api_schema": [],
        "views": {},
        "current_conference": {},
        "attendee_drill": {},
        "recommendations": [],
    }

    def log(msg: str) -> None:
        print(msg, flush=True)

    log("── 0. Schema Explorer: views the API can actually name ──")
    meta_all = api_get(base_url, token, "/metadata", {
        "user_email": email,
        "show_all_views": "true",
    })
    api_views: set[str] = set()
    if _ok(meta_all):
        api_views = {str(v) for v in (meta_all.get("views") or [])}
        report["available_views_in_api_schema"] = sorted(api_views)
        log(f"    {len(api_views)} view(s) in DB_SCHEMA")
        extra = sorted(api_views - {c["view"] for c in CLIENT_VIEWS})
        report["views_in_schema_not_in_client_email"] = extra
        if extra:
            log(f"    {len(extra)} extra view(s) in schema not named in the email (listed in JSON)")
    else:
        report["available_views_in_api_schema_error"] = meta_all
        log(f"    ERROR listing views: {meta_all.get('_error')} {meta_all.get('_detail', '')[:200]}")

    for spec in CLIENT_VIEWS:
        view = spec["view"]
        log(f"\n── {spec['schema']}.{view}  [{spec['category']} / {spec['grouping']}] ──")
        entry: dict[str, Any] = {
            "client_schema": spec["schema"],
            "category": spec["category"],
            "grouping": spec["grouping"],
            "note": spec.get("note"),
            "in_api_schema_list": view in api_views,
            "already_in_conferenceAttendance": view in INGESTED_INTO_ATTENDANCE,
        }

        cols_resp = api_get(base_url, token, "/metadata", {
            "user_email": email,
            "show_view_columns": view,
        })
        entry["columns_response_status"] = _status(cols_resp, spec["schema"], api_views, view)
        columns = _columns_from_metadata(cols_resp) if _ok(cols_resp) else []
        entry["columns"] = columns
        if not _ok(cols_resp):
            entry["columns_error"] = {
                k: cols_resp[k] for k in ("_error", "_detail") if k in cols_resp
            }

        status = entry["columns_response_status"]
        if status != "ok":
            entry["relation_to_existing"] = _relation_to_existing(view, spec["grouping"], status)
            entry["agent_questions"] = _agent_questions(spec["category"], spec["grouping"])
            report["views"][f"{spec['schema']}.{view}"] = entry
            log(f"    status={status}")
            continue

        sample = api_get(base_url, token, "/query", {
            "user_email": email,
            "view_name": view,
            "limit": SAMPLE_ROWS,
        })
        rows = sample.get("data") if _ok(sample) else []
        entry["sample_row_count"] = sample.get("row_count") if _ok(sample) else None
        entry["sample_error"] = None if _ok(sample) else sample
        # Keep at most two sample rows in the report (enough to see shape, less PII dump).
        entry["sample_rows_truncated"] = (rows or [])[:2]
        entry["fill_rates_on_sample"] = _fill_rates(rows or [])
        entry["join_keys_present"] = _present_keys(columns)
        entry["title_column_candidates"] = _title_like(columns)
        entry["pii_column_candidates"] = _pii_like(columns)

        keys_to_probe = entry["join_keys_present"][:4]
        # Always try the grain keys implied by the client legend.
        for implied in ("EventInstanceID", "AttendeeID", "CompanyID"):
            picked = _pick(columns, implied)
            if picked and picked not in keys_to_probe:
                keys_to_probe.append(picked)

        distinct: dict[str, Any] = {}
        for col in keys_to_probe:
            log(f"    distinct {col}")
            dresp = api_get(base_url, token, "/query", {
                "user_email": email,
                "view_name": view,
                "distinct_column": col,
                "limit": DISTINCT_LIMIT,
            })
            if _ok(dresp):
                values = [row.get(col) for row in (dresp.get("data") or [])]
                distinct[col] = {
                    "returned": dresp.get("row_count"),
                    "hit_limit": (dresp.get("row_count") or 0) >= DISTINCT_LIMIT,
                    "sample_values": values[:15],
                }
            else:
                distinct[col] = {"error": dresp}

        entry["distinct"] = distinct

        log("    row count")
        count_resp = api_get(base_url, token, "/aggregate", {
            "user_email": email,
            "view_name": view,
            "aggregation": "count",
        })
        if _ok(count_resp):
            data = count_resp.get("data") or []
            entry["row_count"] = data[0].get("count") if data else count_resp.get("row_count")
        else:
            entry["row_count_error"] = count_resp

        # Grouping check: count per EventInstanceID when that column exists.
        event_col = _pick(columns, "EventInstanceID")
        if event_col:
            log(f"    count by {event_col}")
            grouped = api_get(base_url, token, "/aggregate", {
                "user_email": email,
                "view_name": view,
                "aggregation": "count",
                "group_by_column": event_col,
            })
            if _ok(grouped):
                gdata = grouped.get("data") or []
                entry["rows_per_event_instance"] = {
                    "events_returned": len(gdata),
                    "top": sorted(gdata, key=lambda r: r.get("count") or 0, reverse=True)[:8],
                }
            else:
                entry["rows_per_event_instance_error"] = grouped

        entry["relation_to_existing"] = _relation_to_existing(view, spec["grouping"], "ok")
        entry["agent_questions"] = _agent_questions(spec["category"], spec["grouping"])
        entry["proposed"] = _proposed_kind(view, spec["category"], spec["grouping"], "ok")
        report["views"][f"{spec['schema']}.{view}"] = entry
        log(f"    status=ok  cols={len(columns)}  rows={entry.get('row_count', '?')}")

    # ── Current conference (client instruction) ──────────────────────────────
    if not args.skip_drill:
        log("\n── Current conference (v_EventInstance_Current / fallbacks) ──")
        current: dict[str, Any] = {"instruction": "Use v_EventInstance_Current to get the current conference ID."}
        for view in _CURRENT_CONF_VIEWS:
            resp = api_get(base_url, token, "/query", {
                "user_email": email,
                "view_name": view,
                "limit": 20,
            })
            current[view] = resp if _ok(resp) else {
                "status": "unavailable",
                "error": {k: resp[k] for k in ("_error", "_detail") if k in resp},
            }
            if _ok(resp) and (resp.get("data") or []):
                log(f"    {view}: {resp.get('row_count')} row(s)")
                break
        else:
            # Fallback: distinct EventInstanceID on the attendance view.
            fallback = api_get(base_url, token, "/query", {
                "user_email": email,
                "view_name": "v_EventInstance_Attendee",
                "distinct_column": "EventInstanceID",
                "limit": DISTINCT_LIMIT,
            })
            current["fallback_event_instance_ids_from_attendance"] = fallback
            log("    current-conference views unavailable; recorded EventInstanceIDs from attendance")
        report["current_conference"] = current

        log("\n── One-attendee drill across queryable views with AttendeeID ──")
        att_sample = api_get(base_url, token, "/query", {
            "user_email": email,
            "view_name": "v_EventInstance_Attendee",
            "limit": 1,
        })
        rows = att_sample.get("data") or [] if _ok(att_sample) else []
        sample_id = rows[0].get("AttendeeID") if rows else None
        event_id = rows[0].get("EventInstanceID") if rows else None
        drill: dict[str, Any] = {
            "attendee_id": sample_id,
            "event_instance_id": event_id,
            "by_view": {},
        }
        if sample_id is None:
            drill["_note"] = "No AttendeeID from v_EventInstance_Attendee — skipped."
            log("    skipped (no sample attendee)")
        else:
            log(f"    AttendeeID={sample_id} EventInstanceID={event_id}")
            for spec in CLIENT_VIEWS:
                view = spec["view"]
                ventry = report["views"].get(f"{spec['schema']}.{view}") or {}
                cols = ventry.get("columns") or []
                att_col = _pick(cols, "AttendeeID")
                if not att_col or ventry.get("columns_response_status") != "ok":
                    continue
                filters = [{"column": att_col, "op": "eq", "value": str(sample_id)}]
                ev_col = _pick(cols, "EventInstanceID")
                if ev_col and event_id is not None:
                    filters.append({"column": ev_col, "op": "eq", "value": str(event_id)})
                dresp = api_get(base_url, token, "/query", {
                    "user_email": email,
                    "view_name": view,
                    "filters": json.dumps(filters),
                    "limit": DRILL_LIMIT,
                })
                if _ok(dresp):
                    drill["by_view"][view] = {
                        "row_count": dresp.get("row_count"),
                        "columns_in_first_row": list((dresp.get("data") or [{}])[0].keys()),
                    }
                else:
                    drill["by_view"][view] = {"error": dresp}
        report["attendee_drill"] = drill

    # ── Roll-up recommendations ──────────────────────────────────────────────
    recs: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for key, entry in report["views"].items():
        proposed = entry.get("proposed")
        if not proposed:
            continue
        object_type = proposed.get("object_type") or f"enrich:{entry['category']}"
        if object_type in seen_types:
            rec = next(r for r in recs if r["id"] == object_type)
            rec["source_views"].append(key)
            continue
        seen_types.add(object_type)
        recs.append({
            "id": object_type,
            "priority": proposed.get("priority"),
            "grain": proposed.get("grain"),
            "why": proposed.get("why"),
            "source_views": [key],
            "blocked": entry.get("columns_response_status") != "ok",
        })
    recs.sort(key=lambda r: {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(r["priority"] or "", 9))
    report["recommendations"] = recs

    ok_n = sum(1 for v in report["views"].values() if v.get("columns_response_status") == "ok")
    missing = [
        k for k, v in report["views"].items()
        if v.get("columns_response_status") in {"not_in_api_schema", "not_found"}
    ]
    report["summary"] = {
        "client_views_probed": len(CLIENT_VIEWS),
        "queryable": ok_n,
        "not_in_api_schema_or_missing": missing,
        "existing_kind_unchanged": EXISTING_KIND,
    }

    out_dir = repo_root / ".outputs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "document_candidate_exploration.json"
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("\n════════════════════════════════════════════════════════")
    print(f"Report: {out_path}")
    print(f"Queryable: {ok_n} / {len(CLIENT_VIEWS)}")
    if missing:
        print("Not in API schema (dbo vs rpt) or missing:")
        for name in missing:
            print(f"  - {name}")
    print("Proposed document kinds / enrichments (from queryable views):")
    if not recs:
        print("  (none — wait until dbo views are reachable or rpt views succeed)")
    for rec in recs:
        print(f"  [{rec['priority']}] {rec['id']}: {rec['grain']}")
        print(f"       {rec['why']}")
        print(f"       views: {', '.join(rec['source_views'])}")
    print("Next: share this JSON and we lock catalog entries + builders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
