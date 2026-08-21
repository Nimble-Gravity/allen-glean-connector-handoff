# Prerequisites & connecting-machine requirements — Allen & Co

Technical annex to **`CLIENT-HANDOFF.md`** (the step-by-step). This file is the
machine-level "install this / open that": what the build machine needs, what a
machine that connects to the database needs, and the exact TLS/auth settings.

---

## A. Build machine — runs `build-images` to create the two images

Two modes; pick one:

| | `az acr build` (recommended) | `--local` |
|---|---|---|
| Local Docker | **not needed** — builds run in the ACR | Docker 24+ |
| Azure CLI (`az login` to your tenant) | 2.50+ | 2.50+ |
| ACR permission | **AcrPush** (or Contributor) | **AcrPush** |
| Source repository | ✅ | ✅ |
| Outbound HTTPS 443 (this machine) | `*.azurecr.io` + Azure control plane (`login.microsoftonline.com`, `management.azure.com`) | the above **+** `mcr.microsoft.com` + `packages.microsoft.com` + `deb.debian.org`/`security.debian.org` (base-image apt deps) |
| Disk | minimal | ~2–3 GB |

In **`az acr build`** mode the base image (`mcr.microsoft.com`) and ODBC Driver 18
(`packages.microsoft.com`) are pulled by the **ACR build agent** (server-side) — the
machine running the script only needs the ACR endpoint + Azure control plane. A
locked-down build box can still use `az acr build`. Only **`--local`** needs your
machine to reach `mcr`/`packages`/the Debian mirrors (`deb.debian.org`).

**Target platform:** the deployed images must be **`linux/amd64`** (Azure Container
Apps). `az acr build` produces amd64 by default; `--local` pins `--platform
linux/amd64` (so an Apple Silicon / ARM build box still produces a deployable image,
via emulation). A native arm64 image would fail to run on Container Apps.

---

## B. Machine that connects to the SQL server (dev / validation only)

The MI has **no public endpoint** — a developer reaches it via **Azure Bastion + jump
VM**. Production containers connect over the private VNet and need none of this.

- **Microsoft ODBC Driver 18 for SQL Server** — Windows `.msi` · macOS `brew install msodbcsql18` · Linux `ACCEPT_EULA=Y apt-get install msodbcsql18`.
- **Azure CLI** + an **Entra ID guest account (MFA)** with **Reader** on the Bastion and jump VM → `az network bastion tunnel`.
- A SQL client: **SSMS** or `sqlcmd`.
- Credentials: the temporary read-only **`glean_dev`** login (dev). Production is passwordless (managed identity).

---

## C. TLS & connection settings

Azure SQL MI has a **real, validatable certificate**, so the connector always validates
it. These map to the `DB_*` env vars (`.env.example`) and the builder in
`src/allenco_connector/db_connection.py`:

| Setting | Value | Why |
|---|---|---|
| `Encrypt` | `yes` | Encrypt in transit (always). |
| `TrustServerCertificate` | `no` | MI has a real cert — never trust-all. |
| `HostNameInCertificate` | `<mi-fqdn>` — **only** when tunneling | Dial `127.0.0.1` but validate the MI's real cert name. |
| Auth — **prod** | `Authentication=ActiveDirectoryMsi` **+** `UID=<identity-client-id>` (`DB_AUTH_MODE=msi`) | Passwordless. ⚠️ A **user-assigned** identity must be selected by its **client id** — without `UID` the driver targets a non-existent system identity and fails. |
| Auth — **dev** | `UID=glean_dev;PWD=…` (`DB_AUTH_MODE=sql`) | The read-only dev login. |

Connection-string shapes:

```
# Production — user-assigned managed identity (passwordless)
DRIVER={ODBC Driver 18 for SQL Server};SERVER=<mi-fqdn>,1433;DATABASE=<ems-database>;
Encrypt=yes;TrustServerCertificate=no;Authentication=ActiveDirectoryMsi;UID=<identity-client-id>;

# Dev — SQL login (Bastion / initial validation)
DRIVER={ODBC Driver 18 for SQL Server};SERVER=<mi-fqdn>,1433;DATABASE=<ems-database>;
Encrypt=yes;TrustServerCertificate=no;UID=glean_dev;PWD=<secret>;
```

> The container injects the identity's client id automatically as `AZURE_CLIENT_ID`; the
> connector also accepts `DB_MSI_CLIENT_ID`. Get the value with:
> `az identity show --ids <identity-resource-id> --query clientId -o tsv`.

---

## D. Runtime network (deployed containers / server side)

Provisioned by Allen (connectivity doc §B) — listed for completeness:

- **Container subnet → MI :1433** over the private VNet (single NSG rule; MI public endpoint stays disabled).
- Containers **outbound 443** to the Glean Indexing API, ACR, Key Vault, and the sync-state storage account.
- **Custom Action API inbound 443** restricted to **Glean's published egress IP ranges** (plus the bearer API key).
