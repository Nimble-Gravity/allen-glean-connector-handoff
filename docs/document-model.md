# EMS → Glean document model

> **Status:** design agreed with the client (their "Documents" question). Implemented as a
> layered, `EventInstanceID`-anchored model. Tier 1 + Tier 2 first; Tier 3 as a fast-follow.
> Concrete columns land after `scripts/discover_schema.py` against the **`rpt`** schema.

## Why layered (and why it fixes the "wrong answer" in Glean)

The first test index shipped one **generic document per row** with no conference context and weak
titles. Glean could *find* the connector but answered questions wrong because it could not tell
"Jane Doe at Sun Valley **2025**" from "Jane Doe at Sun Valley **2026**", and rows collided (226
duplicate ids were dropped). The fix is a model that:

1. anchors every conference-scoped fact to **`EventInstanceID`** (carried as a filterable custom
   property *and* in the title/body), and
2. uses **composite ids** so one attendee can have many flights/activities without collisions.

The current conference is always `EventInstance.IsDefault = 1`; `EventInstanceID` maps to a human
code/name (e.g. `SV26` = "Sun Valley Conference 2026") via the `EventInstance` table/view.

## ⚠️ Replica prerequisite: read access to `ConferenceImage`

The report views that carry the **person's name** — `rpt.v_Attendee_Global` (global identity),
`rpt.v_Invitation_CurrentStatus` (name + conference code + status), `rpt.v_Invitation_History`,
`rpt.v_Attendee_Event_LocalStaff` — transitively read **`ConferenceImage.dbo.Attendee_Picture`** (the
attendee-photo table). That database is **not present/accessible on the read replica**, so those views
fail to bind (SQL error 4413) and cannot be queried. Verified with `scripts/probe_views.py`.

**Ask for the client:** grant the replica **read access to the `ConferenceImage` database** (the
report views join to it for the photo flag). Until then, the connector runs on the **binds-today**
views below and the name-bearing views stay disabled in the catalog (flip `enabled=True` once granted).

## The tiers (by BIND status)

**Enabled — bind today, no `ConferenceImage`:**

| Tier | object_type | `rpt` view | id (`id_columns`) | Title |
|---|---|---|---|---|
| **2 — Attendee @ Conference** | `attendeeConf` | `v_EventInstance_Attendee` | `AttendeeID`, `EventInstanceID` | `Acme Corp – GUEST` (IDs + company; no name in this view) |
| **3 — Catering** | `catering` | `v_Catering_TableAssignment` | `AttendeeID`, `EventInstanceID`, `EventInstanceActivityID` | `Jane Doe – Welcome Dinner` (has the name) |
| **3 — Activity** | `activityAttendee` | `v_Activity_Attendee_TimeRange` | + `EventInstanceActivityID` | (activity id / times) |
| **3 — Travel (air/ground)** | `travelAir`, `travelGround` | `v_TravelAir`, `v_TravelGround` | + `RecordID` | `United – 482` |

**Disabled — blocked on `ConferenceImage` (enable when granted):**

| Tier | object_type | `rpt` view | Title | Why it's the goal |
|---|---|---|---|---|
| **1 — Attendee (global)** | `attendee` | `v_Attendee_Global` | `Jane Doe – Acme Corp` | stable global identity + dietary/allergy |
| **2 — Attendee status** | `attendeeStatus` | `v_Invitation_CurrentStatus` | `Jane Doe – SV26` | **the headline doc**: name + `SV26` code + status → answers "was X at Y?" |

Every doc carries `EventInstanceID` (and, where present, the conference code) as a **custom property**
for per-conference filtering. Bodies keep **dietary/allergy** (catering must-have) and drop the PII in
`EXCLUDE_COLUMNS`.

Common report filters the client named, carried as body fields (and, where they drive per-conference
scoping, custom properties): Attendee `AttendeeCodeID`, `AttendeeCodeTypeSub`; Travel
`TravelRecordTypeID`, `TravelMethodAirID`, `TravelDate`; Lodging `AccommodationID`; Catering/Activities
`ActivityID`, `ActivityTypeID`, `ActivitySubTypeID`. (See the `rpt` stored procedures for how they join.)

## How it maps to the catalog (no per-view Python)

Each tier is a `ViewCatalogEntry` in `src/allenco_connector/views/catalog.py`; the generic
`rows_to_documents` builder does the shaping via three fields:

- **`id_columns`** — composite document key (joined by `:`), e.g. `("AttendeeID", "EventInstanceID")`
  for Tier 2, `("AttendeeID", "EventInstanceID", "<flight key>")` for a Tier-3 flight. Overrides the
  single `id_column`. This is what removes the duplicate-id drops.
- **`property_columns`** — columns emitted as Glean **custom properties** (filterable metadata),
  always including `EventInstanceID` for conference-scoped tiers.
- **`title_columns`** — human title parts (name + conference).

A tier that needs richer shaping than one-row-one-doc (e.g. Tier 2 aggregating travel/lodging into a
summary) can set a per-entry `build=` override instead — but prefer a well-chosen `rpt` view that is
already at the right grain.

## Data source: the `rpt` schema

The client recommends the **`rpt`** views (report-optimized, already joined) over the raw `cnf`
views. Confirmed on the DB (`scripts/discover_schema.py` → 36 `rpt` views). The catalog uses:

- `rpt.v_Attendee_Global` — attendee-global grain → **Tier 1** (`attendee`).
- `rpt.v_Invitation_CurrentStatus` — attendee × conference grain, with name + `EventInstanceShort` +
  `EventYear` + status → **Tier 2** (`attendeeConf`).
- `rpt.v_TravelAir` / `v_TravelGround` / `v_Activity_Attendee_TimeRange` / `v_Catering_TableAssignment`
  → **Tier 3** (disabled in v1).

Conference identity + "current" flag: `rpt.v_EventInstance_PrevNext` maps `EventInstanceID` →
`EventInstance` / `EventInstanceShort` / `EventYear`; the **current** conference is `IsDefault = 1` on
the EventInstance master (`dbo.v_EventInstance`), which the hourly job uses to scope Tier 2.

If a field is missing from the `rpt` views, the client will point to where it lives (their `rpt`
stored procedures are the canonical examples).

## Cross-cutting policy

- **PII** — mirror the Salesforce connector's exclusions via `EXCLUDE_COLUMNS`, **but keep
  dietary/allergy** (must-have for catering). The conservative `EXCLUDE_COLUMNS` template lives in the
  dev runbook (`infra/allenco/DEV-ENVIRONMENT.md`); reconcile its names against discovery.
- **Permissions** — for now every authorized user sees all conference info → a single "authorized
  users" AD group grants all documents (sourced from the SQL groups view). Restricted options if the
  client wants them later: per-conference (`EventInstanceID` → group), per-object-type/category, or
  per-attendee sensitivity — all deny-by-default.
- **Include inactive/deleted** — `IsDeleted` / `IsInactive` attendees are still indexed (historical
  relevance); do **not** filter them out.
- **Cadence** — historical daily; current conference (`IsDefault = 1`) hourly (sub-hourly during the
  event). Hourly is cheap because it's a single `EventInstanceID` (naturally small; full-refresh of
  just that conference is fine even without a watermark column).

## Open items (confirm on the VM / with the client)

- Exact `rpt` view + column names for each tier (run discovery, paste into the catalog).
- The `EventInstanceID → code/name` source (the `EventInstance` view/columns).
- The natural keys for Tier-3 detail rows (flight/lodging/activity), for the composite `id_columns`.
- The Salesforce PII exclusion list to mirror.
- Whether Tier-2 comes from one `rpt` view or needs a `build=` aggregation.
