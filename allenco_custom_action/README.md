# Allen & Co Glean Custom Action API

A FastAPI server that exposes Allen & Co's read-only **EMS views** (on the Azure
SQL Managed Instance) to Glean's AI agent via the
[Glean Custom Actions](https://developers.glean.com/docs/custom-actions) framework.

The agent uses this API when it needs **live data** not covered by the indexed
documents — querying a specific view, fetching raw rows with a filter, or
computing a real-time aggregate.

**Views in scope (SELECT only):** `v_Attendee`, `v_Attendee_Event`, `v_Company`,
`v_Participation`.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/metadata` | Explore the schema: list views or inspect a view's columns |
| `GET` | `/query` | Fetch data rows from a view (filter, sort, select, distinct) |
| `GET` | `/aggregate` | `count` / `sum` / `avg` / `min` / `max`, optionally grouped |

All endpoints require a `user_email` query parameter (the authenticated Glean
user's email, for audit logging and AD/Entra permission checks) and a bearer
`CUSTOM_ACTION_API_KEY` in the `Authorization` header.

---

## Local setup

```bash
# From the project root — activate the shared virtual environment
source .venv/bin/activate

# Install Custom Action dependencies
pip install -r allenco_custom_action/requirements.txt

# Configure .env at the project root (shared with the indexer)
```

### Running

```bash
cd allenco_custom_action
uvicorn main:app --reload
```

Server at `http://127.0.0.1:8000`; Swagger UI at `/docs`, ReDoc at `/redoc`.

> The startup does **not** open a DB connection (the AD/Entra permission cache is
> a stub — see `permissions.py`), so the API boots without a live MI. Each request
> opens its own pooled connection on demand.

---

## Environment variables

The API reads settings from the shared `.env` at the project root (one level up).

| Variable | Description |
|---|---|
| `DB_SERVER` | Azure SQL MI FQDN (or `127.0.0.1` when tunneling) |
| `DB_NAME` | Database name |
| `DB_AUTH_MODE` | `sql` (dev), `msi` or `default` (Azure passwordless) |
| `DB_USER` / `DB_PASSWORD` | Required when `DB_AUTH_MODE=sql` |
| `DB_PORT` | Default `1433` |
| `DB_DRIVER` | Default `ODBC Driver 18 for SQL Server` |
| `DB_TRUST_SERVER_CERTIFICATE` | Keep `false` for Azure MI (real cert) |
| `DB_HOST_NAME_IN_CERTIFICATE` | Only when tunneling (Option B2) |
| `CUSTOM_ACTION_API_KEY` | Bearer key Glean must present |
| `MAX_ROWS` | Max rows for `/query` (default `500`) |

---

## OpenAPI specs

Glean Custom Actions are registered from the OpenAPI 3.0 specs in `openapi/`
(`metadata.yaml`, `query.yaml`, `aggregate.yaml`). Their `description` fields are
**prompts for the Glean agent**. On deploy, replace `SERVER_HOST` in each spec's
`servers[0].url` with the API's public hostname.

---

## Security notes

- Identifier parameters (`view_name`, `filter_by_column`, …) are validated against
  `^[a-zA-Z0-9_]+$` and bracket-quoted — no injection via identifiers.
- Value parameters are passed as bound SQL parameters, never interpolated.
- Read-only: all queries are `SELECT`.
- ⚠️ Per-user view access (`permissions.check_user_has_view_access`) is a
  **skeleton stub** pending the AD/Entra source decision — currently only
  superusers pass. See the repo `CLAUDE.md` → "Open questions".
