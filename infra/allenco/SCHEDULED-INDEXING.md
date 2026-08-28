# Scheduled indexing on the VM — weekly Glean refresh

*Hand-off from Nimble Gravity. How to run the **indexer** on a recurring schedule
**directly on the Managed Windows Instance**, using **Windows Task Scheduler**.*

## What this is (and how it relates to the Container Apps Job)

The indexer (`src/main.py`) is a one-shot batch: it reads the in-scope EMS `rpt` views,
builds Glean documents, and pushes them via the Glean Indexing API. This runbook wires it to
run **once a week on the VM**.

> **Two ways to schedule the indexer — pick ONE, don't run both against the same datasource.**
> The production design also ships the indexer as an **Azure Container Apps Job** (scheduled,
> scale-to-zero — `infra/modules/containerAppsJob.bicep`, cron in **UTC**). This VM path is the
> **alternative**: simpler to operate on the box you already have, no container build/deploy
> loop. Two schedulers doing a **full refresh** at once would fight over the same datasource.

**Cadence note.** The recorded client target was *daily (historical) / hourly (current
conference)*. "Weekly" is coarser; changing it later is a **schedule parameter**, not a code
change (re-run the register script with a different `-DayOfWeek` / `-At`, or add triggers).

## Prerequisites (one-time)

1. **Dev toolchain installed** and the project set up per
   [`DEV-ENVIRONMENT.md`](./DEV-ENVIRONMENT.md): Python 3.12, **ODBC Driver 18**, and a **`.venv`
   at the repo root** (`python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -e ".[dev]"`).
   The wrapper runs `.venv\Scripts\python.exe` — it must exist.
2. **The VM's managed identity is a DB principal with `SELECT`** on the in-scope `rpt` views.
   Run [`infra/sql/mi_user.sql`](../sql/mi_user.sql) **as the Entra admin**, with `MI_NAME` set
   to the VM's user-assigned managed-identity display name:
   ```
   sqlcmd -S <mi-host>.database.windows.net -d <ems-database> -G -v MI_NAME="<vm-identity-name>" -i infra\sql\mi_user.sql
   ```
3. **Datasource configured once in Glean** (object types + urlRegex):
   `python scripts\setup_datasource.py` (see `DEV-ENVIRONMENT.md`). Re-run only when a view is
   enabled/renamed.
4. **Outbound network** from the VM: HTTPS to `<instance>-be.glean.com` and the SQL MI on
   **:1433** (VNet/private endpoint).

## Configure `.env` for the weekly run

The scheduled run is **`.env`-driven**. Set these in the repo-root `.env` (msi + full refresh):

```
GLEAN_INSTANCE=<instance>
GLEAN_INDEXING_API_KEY=<indexing-api-key>
GLEAN_DATASOURCE=ems                # must match what setup_datasource.py registered
GLEAN_ENABLE_INDEXING=true          # ← real push (see the override note below)
GLEAN_FULL_REFRESH=true             # ← full refresh each week (reflects deletions)
FETCH_ROW_LIMIT=0                   # no cap: the full index
SYNC_STATE_BACKEND=none             # full refresh → no watermark/blob state to keep

DB_AUTH_MODE=msi
DB_MSI_CLIENT_ID=<client-id of the VM's user-assigned identity>   # required for user-assigned MI
DB_SERVER=<mi-fqdn>                 # e.g. your-mi.<zone>.database.windows.net
DB_PORT=1433
DB_NAME=<ems-database>
DB_SCHEMA=rpt
DB_ENCRYPT=true                     # Azure MI presents a real, validatable cert
DB_TRUST_SERVER_CERTIFICATE=false   # ⚠️ NEVER true against Azure MI (silently disables validation)

# PII: keep dietary/allergy (catering must-have); drop the rest. Case-insensitive globs.
EXCLUDE_COLUMNS=DOB,License*,Passport*,SSN,NationalID
VIEW_URL=http://ems3/#/home         # single deep-link target (hash-route SPA)

# ACLs: either the AD/Entra groups view + allowed groups, or superuser emails.
DB_GROUPS_VIEW=                     # e.g. glean.v_UserGroups; empty = superusers only
GLEAN_ALLOWED_GROUPS=
GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS=

# Failure alerts (recommended so a bad scheduled run is noticed).
NOTIFICATIONS_ENABLED=true
SLACK_WEBHOOK_URL=<webhook>
```

> ⚠️ **`.env` overrides the shell.** `main.py` calls `load_dotenv(override=True)`, so values in
> `.env` **win** over any environment variables. The run mode (`GLEAN_ENABLE_INDEXING`,
> `GLEAN_FULL_REFRESH`) is therefore controlled **here in `.env`** — the wrapper does not (and
> cannot) set it via the shell. Find the full key reference in [`.env.example`](../../.env.example).

Get the identity client id with:
```
az identity show --ids <vm-identity-resource-id> --query clientId -o tsv
```

## Register the weekly task

Run in an **elevated PowerShell** on the VM, from the repo root:

```powershell
# Run as SYSTEM (simplest; msi means the DB identity is the VM's, not this account):
./infra/allenco/register-scheduled-task.ps1 -AsSystem

# …or run as a dedicated service account (prompts for its password, stored by Task Scheduler):
./infra/allenco/register-scheduled-task.ps1 -RunAsUser 'ALLENCO\svc-glean' -DayOfWeek Sunday -At 02:00
```

- **Times are the VM's local time.** Default: **Sunday 02:00**.
- The task is **idempotent** — re-run with different `-DayOfWeek`/`-At` to change the schedule.
- With **msi**, the Run As account only needs **local** rights to the repo + `.venv`; the SQL
  identity comes from the VM's managed identity via IMDS, independent of this account.

## Run once manually (test before trusting the schedule)

```powershell
# Dry run first (no push): temporarily set GLEAN_ENABLE_INDEXING=false in .env, then:
./infra/allenco/run-indexer.ps1     # writes .outputs\ems_documents_*.json; inspect it

# Real run (GLEAN_ENABLE_INDEXING=true in .env):
./infra/allenco/run-indexer.ps1
```

Each run tees a full transcript to **`logs\scheduled\indexer-<timestamp>.log`** (kept 90 days;
override with `-RetentionDays`). The wrapper returns the indexer's exit code: **0 = OK**,
**non-zero = failure** (a failed Glean push returns `1`; fatal errors also surface as non-zero).

## Verify

| Check | How |
|---|---|
| DB reachable via msi | `python scripts\check_db.py` → `RESULT: PASS` |
| Wrapper run OK | last log line reads `... ok=True`; script exits `0` |
| Docs landed in Glean | `python scripts\check_index.py` shows documents in the datasource |
| Task registered | `Get-ScheduledTaskInfo -TaskName AllenCo-Glean-Indexer-Weekly` → next run time |
| Forced run result | `Start-ScheduledTask -TaskName AllenCo-Glean-Indexer-Weekly` → `LastTaskResult` = `0` |
| Failure alerting | break a credential in `.env` → confirm the Slack alert fires and result ≠ 0 |

## Troubleshooting

- **`Python venv not found`** → create `.venv` at the repo root (Prerequisite 1).
- **Task result `0x1` / non-zero** → open the newest `logs\scheduled\indexer-*.log`; the tail
  carries the exception. Common causes: MI grant missing (Prerequisite 2), wrong
  `DB_MSI_CLIENT_ID`, or `DB_TRUST_SERVER_CERTIFICATE=true` against the MI.
- **Task never fires** → it only runs when the VM is on and on the network
  (`-RunOnlyIfNetworkAvailable`); `-StartWhenAvailable` catches a missed slot on next wake.
- **Two indexers double-pushing** → you're running both this task and the Container Apps Job;
  disable one.

---

*Questions → Nimble Gravity.*
