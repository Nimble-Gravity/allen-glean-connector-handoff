# Database schema changes log

> **Why this file exists.** Allen & Co will move the connector's source DB onto **transactional
> replication**. Per the client: *"If you make any changes to schemas or create your own database,
> views, stored procedures, indices, etc. please write them down. When Transactional Replication goes
> into place, it should wipe those. We can restore them with the script."*
>
> So: **every** DB-side object we create or alter for the connector goes here, with the exact DDL, so
> it can be re-applied after a replication reset. The connector itself is **read-only** (SELECT on the
> report views) — ideally this list stays empty. Anything we do add lives here as the restore script.

## Status

**No schema changes made yet.** The connector reads existing views only (target: the `rpt` schema).

## Convention — custom objects go under a `glean` schema (client-confirmed, 2026-08-20)

The client chose **Option B** on schema changes and asked: *"I would make a schema called `glean` and
just store any custom objects you guys create under that schema. This way it is all in one place and
if you need us then we can find it easily."*

So **any** DB object we create for the connector (helper view, stored procedure, index, etc.) is
created as **`glean.<object>`** — never in `rpt`/`dbo`/`Conference`. Benefits: one place to find them,
a trivial restore after each replication reset (recreate the `glean` schema + its objects from the DDL
logged below), and zero collision with EMS objects. Wire-up when this applies:
- Groups/ACL view (if we build one): `DB_GROUPS_VIEW=<name>` + `DB_GROUPS_SCHEMA=glean`.
- Restore step: `CREATE SCHEMA glean;` then the logged `CREATE` statements, in order.

## Log

_Add an entry per change. Newest first._

<!--
### YYYY-MM-DD — <short title>
- **Object:** <schema>.<name> (view | stored proc | index | table)
- **Reason:** <why the connector needs it>
- **DDL (restore script):**
  ```sql
  -- exact CREATE/ALTER statement(s) to re-apply after a replication reset
  ```
- **Applied on:** <server / database>
- **Author:** <name>
-->

## If we end up needing a helper view/index

Prefer asking the client to add it to the replicated source (so it survives resets) over creating it
ourselves. If we must create one during development, record it above **and** flag it to the client so
it can be folded into their replication script.
