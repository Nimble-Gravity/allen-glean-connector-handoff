# Allen & Co Glean Connector

A [Glean](https://www.glean.com/) custom connector that indexes Allen & Co's **EMS** data (from a
read-only replica on **Azure SQL Managed Instance**) into Glean, plus a **Custom Action API** that
answers live queries from the Glean assistant.

It is the **Azure** variant of the SMART connector, reusing its architecture and adapting connectivity,
permissions, and alerting.

## Two components

| Component | Path | What it does |
|---|---|---|
| **Indexer** | `src/` | One-shot batch: reads 4 EMS views, builds Glean documents with ACLs, pushes via the Glean Indexing API. Runs as an Azure Container Apps scheduled job. |
| **Custom Action API** | `allenco_custom_action/` | Always-on FastAPI: answers live `/metadata`, `/query`, `/aggregate` calls from Glean over HTTPS + bearer key. |

**Views in scope (SELECT only):** `v_Attendee`, `v_Attendee_Event`, `v_Company`, `v_Participation`.

## Quick start

```bash
# Python 3.12+ and Microsoft ODBC Driver 18 for SQL Server required.
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -r allenco_custom_action/requirements.txt

cp .env.example .env   # then fill in Glean keys, DB settings, notification channels
```

### Run the indexer (dry run — no Glean push, exports JSON to `.outputs/`)

```bash
GLEAN_ENABLE_INDEXING=false PYTHONPATH=src python -m main
```

### Run the Custom Action API

```bash
cd allenco_custom_action && uvicorn main:app --reload
# Swagger UI at http://127.0.0.1:8000/docs
```

### Tests & lint

```bash
pytest                                 # indexer suite
cd allenco_custom_action && pytest     # API suite
ruff check src/ allenco_custom_action/ tests/
```

## Connectivity (Azure SQL MI)

Connectivity is **configuration, not code** — only `.env` changes between topologies:

- **`DB_AUTH_MODE`**: `sql` (dev, `DB_USER`/`DB_PASSWORD`), `msi` (managed identity, Azure prod), or
  `default` (`ActiveDirectoryDefault`).
- **TLS**: keep `DB_TRUST_SERVER_CERTIFICATE=false` — Azure MI has a real cert. Only set
  `DB_HOST_NAME_IN_CERTIFICATE` when connecting through a local tunnel.

See `.env.example` for every variable and the TLS/auth rules.

## Status

This is an initial **skeleton**: the reusable base is in place and the Azure connection layer, the 4
EMS view modules, permissions, and notifications are wired as stubs. The EMS document shaping,
AD/Entra permission source, and Azure deployment are the next milestones.
