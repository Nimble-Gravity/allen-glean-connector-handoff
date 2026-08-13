# Allen & Co Glean Connector — development machine setup

*Hand-off from Nimble Gravity. This is the software to install on the **Managed Windows
Instance** (in Allen & Co's Azure) that the Nimble Gravity developer will use to build the
connector. This step is only about the **development toolchain** — the container **build &
deploy** tooling is a separate, later hand-off.*

## What this machine is for

Per our meeting, development happens on a **Managed Windows Instance inside Allen & Co's
Azure cloud** (the NG developer connects to it, e.g. via Bastion/RDP) — replacing the earlier
"open the firewall to a specific NG IP" idea. On that box we edit the code, run the test
suites, and dry-run the connector.

## Access we need from Allen & Co

- **Remote access** to the box for the NG developer (Bastion / RDP, per your standard).
- **Local-admin** on the box (needed to install the software below).

---

## Software to install

Modern Windows 11 / Windows Server 2025 ship `winget`; the commands below use it. If `winget`
isn't available (some Windows Server builds), use the **download link** instead — same result.

| Component | Why it's needed | Install (`winget`) | Download link |
|---|---|---|---|
| **Git for Windows** | clone the source repository | `winget install Git.Git` | https://git-scm.com/download/win |
| **Python 3.12 (64-bit)** | the connector runtime (`>=3.12`) | `winget install Python.Python.3.12` | https://www.python.org/downloads/windows/ |
| **Microsoft ODBC Driver 18 for SQL Server** | required by `pyodbc` to reach Azure SQL MI | *(MSI only)* | https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server |
| **Visual Studio Code** *(or your preferred editor)* | writing / navigating the code | `winget install Microsoft.VisualStudioCode` | https://code.visualstudio.com/ |
| **Azure CLI** | `az login`; later used for build/deploy and to read the identity client-id | `winget install Microsoft.AzureCLI` | https://learn.microsoft.com/cli/azure/install-azure-cli-windows |
| **SQL client** — SSMS *or* Azure Data Studio | validate the DB connection and run the grant scripts | `winget install Microsoft.SQLServerManagementStudio` *(or)* `winget install Microsoft.AzureDataStudio` | https://learn.microsoft.com/sql/ssms/download-sql-server-management-studio-ssms · https://learn.microsoft.com/sql/azure-data-studio/download-azure-data-studio |
| **Docker Desktop** — *optional, later* | **only** if you later build images locally; **not** needed for development, and **not** needed for the recommended `az acr build` path | `winget install Docker.DockerDesktop` | https://www.docker.com/products/docker-desktop/ |

> The exact driver name string the connector expects is **`ODBC Driver 18 for SQL Server`**.
> After installing, confirm it appears under **ODBC Data Sources (64-bit) → Drivers** on the box.

---

## Set up the project (once the software is installed)

Clone the repo, then from the repo root in **PowerShell**:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install -r allenco_custom_action\requirements.txt
copy .env.example .env    # then fill in the values
```

---

## Verify the toolchain (no Azure or Glean access needed yet)

```powershell
python --version                       # expect 3.12.x or newer
pytest                                 # indexer test suite → all green
cd allenco_custom_action; pytest; cd ..   # API test suite → all green
ruff check src allenco_custom_action tests

# Dry-run the indexer end-to-end without a database or Glean:
$env:GLEAN_ENABLE_INDEXING = "false"; $env:PYTHONPATH = "src"; python -m main
# → writes sample documents to .outputs\*.json (the dry run tolerates having no DB)
```

If the tests pass and the dry-run writes JSON to `.outputs\`, the development machine is ready.

---

## Connect to the real EMS DB → discover the schema → dry-run (now that DB access exists)

Once the box can reach the SQL Managed Instance, wire the connector to the real **Conference**
views. Development still happens on the Mac; **pull the changes on this VM** to run the steps
below against the live DB.

**1. Point `.env` at the real DB.** In `.env` set (SQL login is the dev-phase auth):

```
DB_SERVER=<mi-fqdn-or-127.0.0.1>
DB_NAME=<database>
DB_SCHEMA=Conference            # the schema the Conference views live in (confirm in step 3)
DB_AUTH_MODE=sql
DB_USER=<dev-sql-login>
DB_PASSWORD=<dev-sql-password>
```

**2. Confirm connectivity** — connects and counts the catalog's views (schema-qualified):

```powershell
python scripts\check_db.py        # expect RESULT: PASS
```

**3. Discover the real schema** — lists every view + columns and prints ready-to-paste
catalog entries with guessed id / title / watermark columns:

```powershell
python scripts\discover_schema.py   # writes .outputs\schema.json, prints VIEW_CATALOG snippets
```

Paste the printed entries into `src\allenco_connector\views\catalog.py` (replacing the seed
`VIEW_CATALOG`), then **confirm each guessed column** (`id_column`, `title_columns`,
`watermark_column`) against `schema.json`. Set `DB_SCHEMA` to the real schema so the entries
inherit it. Commit the catalog change from the Mac; pull it here.

**4. Dry-run against the real views** — builds real documents, no push to Glean:

```powershell
$env:GLEAN_ENABLE_INDEXING = "false"; $env:PYTHONPATH = "src"; python -m main
# → .outputs\ems_documents_*.json — inspect: ids unique per view, sensible titles, full bodies
```

**5. (Optional) Real ACLs.** To attach AD/Entra group ACLs, set `DB_GROUPS_VIEW` (+ the
`DB_GROUPS_*` columns) and `GLEAN_ALLOWED_GROUPS` in `.env` — the groups come from a SQL view
that mirrors the directory. Until then, documents carry only superuser ACLs
(`GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS`). See `.env.example` for all keys.

---

## Controlled live-indexing test (small, replaceable batch)

Verify the Glean push end-to-end **without flooding Glean or over-exposing PII**. Uses a row cap
+ a full-refresh (so the datasource ends up as exactly the test batch) + column redaction.

**`.env`** (on top of the working DB credentials):

```
GLEAN_INSTANCE=<instance>
GLEAN_INDEXING_API_KEY=<token>
GLEAN_DATASOURCE=allenco_ems
GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS=["<your-glean-email>"]   # so you can SEE the docs in Glean
FETCH_ROW_LIMIT=25            # ~25 rows x 11 views ~= 275 docs
GLEAN_FULL_REFRESH=true       # datasource = exactly this batch (replaceable)
EXCLUDE_COLUMNS=DOB,LicenseNumber,LicenseExpirationDate,LicenseDOB,DietaryAllergyComments,RSVPDietaryAllergyComments
SYNC_STATE_BACKEND=none
GLEAN_ENABLE_INDEXING=false   # start with a dry run (step 1)
```

1. **Dry run first** — `$env:PYTHONPATH="src"; python -m main` → inspect `.outputs\ems_documents_*.json`:
   ~275 docs across 11 types, sensible titles, and the `EXCLUDE_COLUMNS` fields absent from the body.
2. **Live push** — set `GLEAN_ENABLE_INDEXING=true`, run `python -m main`. Expect a log line
   `Starting Glean indexing. datasource=allenco_ems mode=full_refresh ... documents=~275` and
   `ok=True`. (⚠️ The connector warns if indexing is on with `FETCH_ROW_LIMIT=0` — that would push
   EVERY row; keep the cap for the test.)
3. **Verify in Glean** — signed in as the superuser email, search a known attendee/activity: the
   document should appear with the right title/body; a non-superuser must NOT see it (deny-by-default
   until the groups view is wired).
4. **Iterate** — `full_refresh` means the next run replaces the batch. Do the real (uncapped, scoped)
   index only once the client confirms scope / PII / PKs.

---

## Outbound network this machine needs (for development)

HTTPS (443) to:

- **`pypi.org`** and **`files.pythonhosted.org`** — installing Python dependencies (`pip`).
- **`packages.microsoft.com`** — the ODBC Driver 18 installer.
- **your Git remote** — cloning / pulling the source.
- **`<instance>-be.glean.com`** — only once you start test-pushing to Glean (see the Glean
  API-key guide).

Private database connectivity (to the SQL Managed Instance on port 1433) and the
container-registry / Azure control-plane egress are part of the **later build/deploy
hand-off**, not this step.

---

*Questions on any of the above → Nimble Gravity.*
