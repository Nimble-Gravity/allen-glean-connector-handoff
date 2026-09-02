
# Connector Reuse Guide

How to reuse this repo (the **SMART** Glean connector) as the base for a new client connector, and
the specific things to get right for **Allen & Co** so the implementation avoids known traps.

Read `../CLAUDE.md` first for the high-level map and the do-not-break invariants. This guide goes
deeper, in four parts:

- **Part A** — the reusable architecture in detail (what each base module does, how to copy it).
- **Part B** — the new-client playbook (ordered steps).
- **Part C** — Allen & Co focus areas & SMART→Allen deltas (the "avoid errors" section).
- **Part D** — consuming this repo from the new client repo (cross-repo wiring).

The guiding principle, straight from the Allen & Co architecture brief:

> **The application code is identical regardless of where the connector runs. Connectivity is
> configuration, not code.** Only the connection string, host, secrets, permission source, and
> notification channel change between clients.

---

## Part A — Reusable architecture in detail

These modules are the ~40% "base" you copy roughly verbatim. Paths are relative to the repo root.

### A.1 Settings & config (`src/config/config.py`)

Pattern: **frozen dataclasses + manual env readers** (no `pydantic-settings`). Required vars fail
loudly; optional vars have defaults.

```python
def _read_required_str_env(key: str) -> str:
    value = (os.environ.get(key) or "").strip()
    if not value:
        raise OSError(f"Required environment variable '{key}' is not set. Check your .env file.")
    return value

def _read_bool_env(key: str, *, default: bool) -> bool:   # 1/true/yes ↔ 0/false/no
    ...

@dataclass(frozen=True)
class DbSettings:
    server: str; database: str; user: str; password: str
    port: int = 1433
    driver: str = "ODBC Driver 18 for SQL Server"
```

`load_db_settings()` / `load_connector_settings()` build these after `load_dotenv()`. The API
re-declares its **own** `DbSettings` + loaders in `smart_custom_action/settings.py` (it loads
`../.env`). **Reuse:** keep the readers; add/remove fields per client. For new connectivity (managed
identity, tunnels) you will extend `DbSettings` — see Part C.

### A.2 Database connection (`src/smart_connector/db_connection.py`, `smart_custom_action/db.py`)

Both build the same connection string and share a **retry loop** (3 attempts × 5 s, 30 s timeout) for
cold-starts. The **only** intended difference is pooling:

```python
# smart_custom_action/db.py — API, pooling ON (set before first connect())
pyodbc.pooling = True

# src/smart_connector/db_connection.py — indexer, pooling OFF (one-shot script)
```

Current SMART connection string (on-prem, self-signed cert):

```python
connection_string = (
    f"DRIVER={{{settings.driver}}};"
    f"SERVER={settings.server},{settings.port};"
    f"DATABASE={settings.database};"
    f"UID={settings.user};PWD={settings.password};"
    f"Connection Timeout={connect_timeout};"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"   # ← on-prem self-signed; NOT correct for Azure MI (see Part C)
)
```

**Reuse:** keep the retry loop and the `get_connection(settings, *, connect_timeout, retry_attempts,
retry_delay)` signature. Change the **string** per connectivity. These two files are kept in sync by
hand (drift-warning docstrings); for a new client, consider extracting one shared module.

### A.3 Validators (`smart_custom_action/validators.py`)

The whole module — centralized so the three routers can't drift:

```python
SAFE_IDENTIFIER = re.compile(r"^[a-zA-Z0-9_]+$")   # every user-supplied SQL identifier

def _coerce(value: Any) -> Any:                     # pyodbc → JSON-safe
    if value is None: return None
    if isinstance(value, bytes): return value.decode("utf-8", errors="replace")
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)): return value.isoformat()
    if isinstance(value, decimal.Decimal): return float(value)
    return value
```

**Reuse verbatim.** This is the backbone of the SQL-injection defense (Part A.6 shows how routers use it).

### A.4 Notifications (`src/notifications/`) — pure stdlib, shared by both components

The contract that makes it safe and extensible:

```python
# senders/base.py — concrete senders RAISE on failure
class Notifier(ABC):
    name: str = "notifier"
    @abstractmethod
    def send(self, event: ErrorEvent) -> None: ...
```

```python
# factory.py — warn-and-skip a misconfigured-but-enabled channel (never block the sync)
def build_notifier(settings: NotificationSettings) -> Notifier:
    if not settings.enabled:
        return NullNotifier()
    if not (settings.smtp_host and settings.email_from and settings.email_to):
        logger.warning("Notifications enabled but SMTP_* incomplete; notifications disabled.")
        return NullNotifier()
    return CompositeNotifier([EmailNotifier(...)])
```

- `events.py` — `ErrorType` StrEnum (`db_connection`, `glean_prereqs`, `user_indexing`,
  `document_indexing`, `api_startup`, `api_request`, `unexpected`) + `ErrorEvent` (renders text+HTML).
- `resolutions.py` — `resolution_for(error_type)` → a human remediation hint per type.
- `composite.py` — `CompositeNotifier` is the **single never-raising layer**; `NullNotifier` is the no-op.
- The API reuses this package via `smart_custom_action/notifications_setup.py`, which adds `src/` to
  `sys.path` and exposes `notify()` / `notify_db_error()`.

**Reuse:** keep events/composite/factory/resolutions. **To add a channel** (Part C.4): write
`senders/slack.py` (or `site24x7.py`) subclassing `Notifier` (raise on failure), then add it to the
list `CompositeNotifier([...])` in `factory.py` behind its own config check.

### A.5 Glean indexing (`src/glean_index/`)

- `client.py` — singleton wrapping `glean.api_client.Glean`, configured with exponential backoff for
  429/5xx (`default_indexing_retry_config()`). Reads `GLEAN_INSTANCE` / `GLEAN_INDEXING_API_KEY`.
- `index_documents.py` — both **bulk** (`bulk_index_documents_paged`, full-refresh/replace, page ≤
  1000) and **incremental** (`index_documents_paged`, page ≤ 500); a shared `iter_chunks` generator
  drives Glean's multi-page upload (`is_first_page`/`is_last_page`/`force_restart_upload`,
  `disable_stale_*_deletion_check` only on the last page). `GLEAN_FULL_REFRESH` picks the mode.
- `index_users.py` — `bulk_index_users_paged` for datasource users / permissions (same paging).
- `types/documents.py` — `build_document()` → `DocumentDefinition` (JSON body as `text/plain`,
  optional `DocumentPermissionsDefinition(allowed_users=...)`, custom properties).
- `permission_policies.py` — `IndexedDocumentKind` StrEnum + `user_may_access_indexed_document()` with
  `assert_never` exhaustiveness. **Permission logic is client-specific** (see Part C.3).

**Reuse:** client/index_documents/index_users/build_document are base. Permission policy + user model
get rewritten per client.

### A.6 The API skeleton (`smart_custom_action/`)

`main.py` — config loaded once in `lifespan` into `app.state` (notifier built **first**), global
bearer dependency, 422→400:

```python
app = FastAPI(..., lifespan=lifespan, dependencies=[Depends(verify_api_key)])

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(status_code=400, content={"detail": exc.errors()})
```

Each router follows the same shape (from `routers/query.py`): validate identifiers → open connection
(DB error → notify → 500) → check the view exists → build SQL with **bound params** → execute →
`_coerce` rows → return; `finally: conn.close()`.

```python
if not SAFE_IDENTIFIER.match(view_name):
    raise HTTPException(400, "view_name must contain only letters, digits, and underscores.")
...
cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_NAME = ?", view_name)
if cursor.fetchone()[0] == 0:
    raise HTTPException(404, f"View '{view_name}' not found.")
...
parts = [f"SELECT TOP (?) {col_clause} FROM [{view_name}]"]   # identifier bracket-quoted
params = [effective_limit]
if filter_by_column is not None and filter_value is not None:
    parts.append(f"WHERE [{filter_by_column}] = ?"); params.append(filter_value)  # value bound
parts.append("ORDER BY (SELECT NULL)")    # stable order so Glean's paging is consistent
cursor.execute(" ".join(parts), tuple(params))
```

Note the validation/404 paths deliberately **do not notify** — only DB failures (500) and startup do.

**Reuse:** keep `main.py` lifespan, `dependencies.py`, `validators.py`, `schemas.py`, and the router
structure. Per client, change the **view set**, any extra filters, and per-user permission filtering
(today `/query` has a `# TODO: Handle security permissions per user`).

### A.7 OpenAPI specs (`smart_custom_action/openapi/*.yaml`) — agent prompts

These register the endpoints as Glean Custom Actions. Their `description` fields are **prompts for the
Glean agent**, not just schema docs:

```yaml
description: |
  Use this action to retrieve actual data rows from the Smart database.
  **Use this action when the user asks for specific data:** ...
  **Do NOT use this action when:** ... → use the Schema Explorer instead ...
servers:
  - url: "https://SERVER_HOST"     # ← replace at deploy time
```

**Reuse:** keep one spec per action; rewrite the prose to describe the **client's** views and rules,
and set `servers[0].url`.

### A.8 Tests (`tests/` + `smart_custom_action/tests/`)

Two suites, two configs. Key reusable harness:

- `FakeCursor`/`FakeConn` (API `conftest.py`) — pyodbc stand-in with a `fetchone_seq` (`[[1]]` = view
  exists, `[[0]]` = 404) and an `executed` list so tests assert on generated SQL.
- `RecordingNotifier` — captures `ErrorEvent`s to assert the right `ErrorType` fired (no real send).
- `FakeSMTP` — records `starttls`/`login`/`send_message` instead of hitting the network.
- `monkeypatch` collaborators (e.g. `routers.query.get_connection`); use FastAPI `TestClient` **as a
  context manager** so `lifespan` actually runs (needed to test the startup-failure path).

**Reuse:** copy the harness; re-point fixtures at the client's views/permission model.

---

## Part B — New-client playbook

Ordered steps to stand up a new client connector from this base.

1. **Scaffold.** Copy the repo (or the base layer). Rename `src/smart_connector/` →
   `src/<client>_connector/` and update imports. Keep `glean_index/`, `notifications/`, `config/`,
   `view_engine/`, and the `smart_custom_action/` skeleton.
2. **Environment.** Copy `.env.example` → `.env`; fill Glean keys, DB settings, notification settings,
   `CUSTOM_ACTION_API_KEY`. Add any new vars the client needs (and document them in `.env.example`).
3. **Choose connectivity** (this is a *config* decision, not code): inside the DB network, VPN, SSH
   tunnel, or public endpoint. It determines **only** the connection string + host/secrets. See Part
   C.1–C.2 for the matrix.
4. **Connection layer.** Write `src/<client>_connector/db_connection.py` (pooling OFF) and
   `smart_custom_action/db.py` (pooling ON) with the right connection string for that connectivity
   and auth (SQL login vs. managed identity). Keep the retry loop.
5. **Client views.** For each source view, add `src/<client>_connector/views/<view>/` with its query,
   document builder, and any filters. Decide which views the **indexer** snapshots vs. which the
   **API** exposes live.
6. **Permissions.** Implement the client's access model in `glean_index/permission_policies.py` +
   `types/users.py`, and fill `main.load_source_users()` (the SMART stub returns `[]`). Wire
   `allowed_users` onto documents via `build_document(...)`.
7. **Notifications.** If the client doesn't use email, add `senders/<channel>.py` and wire it into
   `factory.build_notifier()` behind a config check (Part C.4).
8. **API actions.** Write `openapi/*.yaml` per action with agent-prose descriptions of the client's
   views; set `servers[0].url`. Add/adjust routers only if the client needs endpoints beyond
   metadata/query/aggregate.
9. **Tests.** Port both suites; re-point `FakeCursor`/fixtures at the client's views and permission
   model. Run `ruff` + `pytest` (both suites).
10. **Deploy.** Pick the target (Azure Container Apps, Docker, Windows service…) per Part C.5.

---

## Part C — Allen & Co focus areas & SMART → Allen deltas

This is the "avoid errors in the future implementation" section. Allen & Co reuses the **same two
components**, indexing four read-only EMS views (`v_Attendee`, `v_Attendee_Event`, `v_Company`,
`v_Participation`) from an **Azure SQL Managed Instance** read-only replica, with permissions from
**AD/Entra ID**. Each item below is a place where copying SMART verbatim would be **wrong**. Source:
`allenco-connector-architecture.md` + `allenco-database-connectivity.md`.

### C.1 Connectivity is configuration, not code — pick the path, change only the string

Four options from the brief (recommendation order): **A** connector inside the Azure VNet
(recommended) · **B1** VPN/peering (best "outside") · **B2** SSH tunnel through a jump host (indexer
only / short-term) · **B3** public endpoint + firewall (last resort). The application code is the same
for all four. Build the connection layer (Part A.2) so the **connection string** is the only thing
that changes.

### C.2 ⚠ Connection-string / TLS cert validation — the #1 trap

SMART connects to on-prem SQL Server with a self-signed cert, so it uses
`Encrypt=yes;TrustServerCertificate=yes`. **Azure SQL Managed Instance has a real, validatable
certificate.** Copying SMART's `TrustServerCertificate=yes` to Allen would silently disable cert
validation — a security regression. Use this matrix instead:

| Option | SERVER in conn string | TLS settings |
|---|---|---|
| **A — inside VNet** | `<mi-fqdn>,1433` (private IP) | `Encrypt=yes;TrustServerCertificate=no` |
| **B1 — VPN** | `<mi-fqdn>,1433` (private over VPN) | `Encrypt=yes;TrustServerCertificate=no` |
| **B2 — SSH tunnel** | `127.0.0.1,11433` (local forwarded port) | `Encrypt=yes;HostNameInCertificate=<mi-fqdn>;TrustServerCertificate=no` |
| **B3 — public endpoint** | public `<mi-fqdn>,3342` (MI public port) | `Encrypt=yes;TrustServerCertificate=no` |

Key point for **B2**: you dial `127.0.0.1` but must still validate the **real** MI certificate —
`HostNameInCertificate=<mi-fqdn>` tells the driver which name to check, and
`TrustServerCertificate=no` keeps validation on. The tunnel itself is set up outside the app:

```bash
ssh -N -L 127.0.0.1:11433:<mi-fqdn>:1433 tunneluser@<jump-host>   # then app connects to 127.0.0.1,11433
```

with `StrictHostKeyChecking=yes` (host key pre-pinned in `known_hosts` — no trust-on-first-use). The
SSH key is restricted (`restrict,permitopen="<mi-fqdn>:1433"`) so it can only forward to the DB.

**Where to change:** `src/<client>_connector/db_connection.py` and `smart_custom_action/db.py` —
parameterize `Encrypt` / `TrustServerCertificate` / `HostNameInCertificate` via `DbSettings` (e.g.
add `host_name_in_certificate: str | None`, `trust_server_certificate: bool = False`) rather than
hardcoding.

### C.3 Permissions: AD/Entra ID groups, not a SQL security view

SMART derives document access from a SQL "security view" + `GlobalUser.can_access_financial_data` +
an env superuser allow-list, and `main.load_source_users()` is a **stub returning `[]`**. Allen ties
Glean access to **allenco.com identities** with document permissions from **AD/Entra ID groups**.

**Where to change:**
- `src/main.load_source_users()` — populate real users (from Entra ID, e.g. via Graph, or from a
  view that mirrors AD groups) instead of `[]`.
- `glean_index/types/users.py` — replace the `can_access_financial_data` model with Allen's
  group-membership model.
- `glean_index/permission_policies.py` — rewrite `user_may_access_indexed_document()` for the new
  model; keep the `assert_never` exhaustiveness check.
- `index_users.py` (`bulk_index_users_paged`) — push the datasource users/permissions so Glean
  enforces document-level access.
- Set `allowed_users` on each document via `build_document(...)`.

### C.4 Notifications: Slack and/or Site24x7, not SMTP email

SMART sends SMTP email. Allen wants alerts to **Slack and/or Site24x7**. The notifications package is
built exactly for this — the `Notifier` abstraction + `CompositeNotifier` are the extension points.

**Where to change:**
- Add `src/notifications/senders/slack.py` (and/or `site24x7.py`) subclassing `Notifier`. **Raise on
  transport failure** (the composite isolates failures, not the sender).
- Extend `NotificationSettings` (`notifications/config.py`) with the new channel's config
  (`SLACK_WEBHOOK_URL`, etc.) and document it in `.env.example`.
- In `factory.build_notifier()`, append the configured sender(s) to the `CompositeNotifier([...])`
  list, each behind its own warn-and-skip config check. Email can stay, be removed, or run alongside.
- The `ErrorType`/`resolution_for`/`ErrorEvent` layer is unchanged — events are channel-agnostic.

### C.5 Deployment & auth: Azure-native (Option A) vs. SMART's Windows/Docker

SMART deploys as a Windows service via **NSSM** (`SDHGleanAPI`) + a one-shot Docker image for the
indexer (host cron `0 */4 * * *`). Allen Option A is **Azure-native**:

- **Indexer** → container image in **Azure Container Registry**, run as a **Container Apps scheduled
  job** (runs, indexes, exits — scale-to-zero between runs).
- **Custom Action API** → an **Azure Container App** (HTTPS, autoscaling replicas).
- **Secrets** → **Azure Key Vault** (not plaintext config).
- **Auth** → prefer **passwordless managed identity** over a SQL login. This changes the connection
  string: **no `UID`/`PWD`**; instead `Authentication=ActiveDirectoryMsi` (or
  `ActiveDirectoryDefault`) with the appropriate ODBC driver support. Make `DbSettings`/the connection
  builder support **both** SQL-auth and managed-identity modes (e.g. an `auth_mode` field) so the same
  code serves Option A and the outside options.

The existing `Dockerfile` (installs `msodbcsql18`) is a good base for the ACR image. Reuse it; the
scheduling/hosting moves from cron/NSSM to Container Apps.

### C.6 Tunnel resilience & pooling (only if Option B2)

The always-on API over an SSH tunnel is fragile (the brief flags this explicitly — prefer A/B1). If
B2 is used:
- Run the tunnel as a managed service: `autossh + systemd`, `ServerAliveInterval`,
  `ExitOnForwardFailure=yes`, auto-restart.
- **Invalidate stale pooled connections on failure.** With `pyodbc.pooling = True`, a tunnel blip can
  leave a dead socket in the pool. The current retry loop reconnects but doesn't explicitly drop a
  poisoned pooled connection — add handling so a failed request discards its connection instead of
  returning it to the pool. The scheduled indexer is fine (it just retries next run).

### C.7 API egress hardening

The brief requires the Custom Action API be restricted to **Glean's published egress IP ranges** (on
top of the bearer key it already enforces). Today the API only checks the bearer token
(`dependencies.verify_api_key`). Add IP allow-listing at the platform layer (Container App
ingress / firewall / reverse proxy) and/or in middleware.

### C.8 Views & least-privilege DB login

In scope: `v_Attendee`, `v_Attendee_Event`, `v_Company`, `v_Participation` (SELECT only). The DB login
is read-only and granted SELECT **only on those views** (not base tables). Encode exactly these four
views; don't carry over SMART's financial views.

---

## Part D — Consuming this repo from the new client repo

You'll have both repos locally. Make this repo a knowledge source for the new one:

### Option 1 — `@import` (recommended for local dev)

In the **new repo's** `CLAUDE.md`, import this repo's hub (and optionally this guide). Claude Code
resolves `@` imports, including absolute/`~` paths:

```markdown
# <Client> Glean Connector — CLAUDE.md

This connector reuses the SMART connector architecture. Reference:
@~/Desktop/Repos/SMART-glean-custom-connector/CLAUDE.md
@~/Desktop/Repos/SMART-glean-custom-connector/docs/connector-reuse-guide.md
```

Note: an `@import` auto-loads that file into context every session. Importing `CLAUDE.md` is cheap;
importing the full guide every time is heavier — link to it in prose and let the agent open it on
demand if you'd rather keep context lean.

### Option 2 — git submodule (travels with the repo on GitHub)

```bash
git submodule add https://github.com/<org>/SMART-glean-custom-connector reference/smart
```

Then reference `reference/smart/CLAUDE.md`. Anyone who clones the new repo gets the reference pinned
to a commit.

### Option 3 — template repo (for the code skeleton)

Make a sanitized version of this repo a GitHub **template**; each new client = "Use this template."
Combine with Option 1/2 for the evolving knowledge.

⚠ **Sanitize before reusing.** Don't carry over SMART/SDH secrets, connection strings, the financial
views, or `can_access_financial_data` logic into a new client. Strip client-specific data when turning
anything into a template or shared reference.
