# Custom Action Triggers (Glean Agent Setup)

> **Purpose.** Each OpenAPI spec in `allenco_custom_action/openapi/` defines *what* an action does
> and *how* to call it. Glean's Custom Action configuration additionally asks for a **trigger** —
> a short natural-language instruction that tells the Glean agent *when* to invoke that action
> relative to the others. This doc is the single place to copy those trigger strings from when
> registering the three actions in the Glean admin console.
>
> Keep this file in sync with the `info.description` block of each YAML — the trigger is a
> condensed version of the same "use when / do NOT use when" logic. If you change the routing
> logic in one place, update the other.

## Registration order

Register all three actions in the Actions or Tools menu (the name has been updated recently), selecting the "Create from scratch" option. Order doesn't affect behavior,
but registering **EMS Schema Explorer → EMS Query → EMS Aggregate** matches the natural dependency chain
(you often need view/column names before you can query or aggregate).

---

## 1. EMS Schema Explorer (`metadata.yaml` → `GET /metadata`, `exploreEmsDatabaseSchema`)

**Trigger:**
```
Use this action when the user asks what data is available in the Allen & Co EMS database, or
when you need to confirm the exact name of a view or its columns before calling the EMS Query
or EMS Aggregate action. Trigger on questions like "what views/data do you have?" or "what
columns does v_EventInstance_Attendee have?". Do not trigger this action if you already know
the exact view and column names, or if the user wants actual data rows or a computed metric —
use EMS Query or EMS Aggregate instead. Each call does exactly one thing: list all views, or
list the columns of one named view — never both.
```

## 2. EMS Query (`query.yaml` → `GET /query`, `queryEmsDatabaseView`)

**Trigger:**
```
Before calling this action, search the indexed Glean documents first — many questions are
already answered by an indexed summary. Only fall through to this action if the indexed
search returns nothing relevant, or the user explicitly needs live/current row-level data.

Use this action when the user asks for actual data rows from the Allen & Co EMS database —
e.g. "show me the attendees for company X", "list flights for attendee Z", "which companies
are registered for event 3?", or any request with a filter, date range, or partial-text match.
Do not trigger this action if the answer is already available from indexed documents, if the
user only wants to know what views or columns exist (use the EMS Schema Explorer action
first), if the user wants a count/sum/average/min/max rather than row-level data (use EMS
Aggregate instead), or if you do not yet know the exact view or column name (resolve that with
the Schema Explorer first). Always pass the current user's email in user_email.
```

## 3. EMS Aggregate (`aggregate.yaml` → `GET /aggregate`, `aggregateEmsDatabaseView`)

**Trigger:**
```
Before calling this action, search the indexed Glean documents first. If a pre-computed
summary already answers the question, use that instead of calling this action.

Use this action when the user asks for a computed metric over many rows in the Allen & Co EMS
database — counts, sums, averages, or extremes, optionally broken down by a category — e.g.
"how many attendees per company?", "average flight cost for attendee X", "count registrations
grouped by company". Do not trigger this action if the answer is a pre-computed summary
already in the indexed documents, if the user wants the underlying data rows (use EMS Query
instead), or if you do not yet know the exact view or column name (resolve that with the EMS
Schema Explorer first). agg_column is required for sum/avg/min/max but must be omitted for
count. Always pass the current user's email in user_email.
```

---

## Notes

- **Indexed documents take priority over Query/Aggregate.** Both actions' triggers instruct the
  agent to search indexed Glean documents first and only fall through to a live DB call if
  nothing relevant is indexed, or the user explicitly needs live/current data. This avoids
  redundant DB round-trips for questions already answered by an indexed summary. The Schema
  Explorer is exempt — it returns structural metadata (view/column names), which is never
  something an indexed document would carry.
- All three triggers assume the agent has already resolved the user's identity — `user_email`
  is always populated from the authenticated Glean session, never asked of the user.
