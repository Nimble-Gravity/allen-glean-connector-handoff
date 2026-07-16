# Allen & Co Glean Connector — build & deploy guide

*Hand-off from Nimble Gravity. Start here. Machine-level detail (installs, TLS,
connection strings, ports) is in the annex: [`PREREQUISITES.md`](./PREREQUISITES.md).*

Nimble Gravity delivers the **source code** and this **build/deploy tooling**. Allen & Co
**builds the two images in your own ACR and deploys** them — no pre-built image and no
production database credentials ever leave your environment.

## What you're deploying

| Image | Component | Runs as |
|---|---|---|
| `indexer` | Batch job that indexes the EMS views into Glean | Container Apps **Job** (scheduled) |
| `custom-action` | Always-on API for Glean's live queries | Container **App** (HTTPS) |

Four steps: **1) build → 2) provision → 3) deploy → 4) verify.**

---

## Step 1 — Build the two images

Recommended path uses `az acr build`: the build runs **server-side in your ACR**, so the
machine running the script **needs no Docker** (just Azure CLI + AcrPush). Full build-machine
requirements: [`PREREQUISITES.md` §A](./PREREQUISITES.md).

**PowerShell**
```powershell
$env:ACR = "<your-acr-name>"          # registry name, without .azurecr.io
./infra/allenco/build-images.ps1              # az acr build (recommended)
./infra/allenco/build-images.ps1 -Local       # or: local Docker build + push
```

**Bash**
```bash
ACR=<your-acr-name> ./infra/allenco/build-images.sh           # az acr build
ACR=<your-acr-name> ./infra/allenco/build-images.sh --local   # or local Docker
```

> **Platform:** the images must be **`linux/amd64`** (what Container Apps runs).
> `az acr build` produces that automatically; the `--local` mode pins
> `--platform linux/amd64` for you (so a build on an Apple Silicon / ARM machine
> still yields a deployable image — via emulation, a bit slower).

---

## Step 2 — Provision the surrounding infrastructure

`deploy` is **deploy-only** — it does not create infra. Provision these first (details in
`docs/allenco-database-connectivity.md` §B):

- **Container Apps environment** (VNet-injected) + the VNet/subnet, with a **Log Analytics
  workspace** attached (so logs are queryable).
- **Key Vault** with the secrets: `glean-indexing-api-key`, `custom-action-api-key`,
  optional `slack-webhook-url`.
- **Storage account** (a blob container) for the connector's incremental sync state.
- A **user-assigned managed identity**, granted:
  | Grant | On | Why |
  |---|---|---|
  | **AcrPull** | the ACR | pull the image at runtime (or the app can't start) |
  | **Key Vault Secrets User** | the Key Vault | read the secrets |
  | **Storage Blob Data Contributor** | the storage account | persist sync state |
  | **`SELECT`** on the 4 views | the database | run `infra/sql/mi_user.sql` as the Entra admin |
- **NSG rule**: container subnet → MI :1433 (MI public endpoint stays disabled).

Then fill **`infra/allenco/main.bicepparam`** with those resource IDs **and the identity's
client id**:
```bash
az identity show --ids <identity-resource-id> --query clientId -o tsv   # → managedIdentityClientId
```
The client id is what makes the workloads pick the right user-assigned identity for the
database (msi) and the sync-state blob.

---

## Step 3 — Deploy

> ⚠️ **AcrPull propagation gate.** The apps pull their image from the ACR using the managed
> identity, and Azure RBAC takes time to propagate. Deploying the instant after granting
> `AcrPull` can make the revision hang ~900s. Grant `AcrPull` first, confirm it propagated,
> then deploy:
> ```bash
> PRINCIPAL_ID=$(az identity show --ids <identity-resource-id> --query principalId -o tsv)
> ACR_ID=$(az acr show --name <acr-name> --query id -o tsv)
> for i in 1 2 3 4 5; do
>   az role assignment list --scope "$ACR_ID" --assignee-object-id "$PRINCIPAL_ID" \
>     --query "[?roleDefinitionName=='AcrPull'].roleDefinitionName" -o tsv | grep -qx AcrPull \
>     && { echo "AcrPull propagated."; break; }
>   echo "waiting for AcrPull RBAC ($i/5)..."; sleep 60
> done
> ```

```bash
RG=<your-rg> INDEXER_TAG=indexer:latest API_TAG=custom-action:latest ./infra/allenco/deploy.sh
```
(PowerShell: `deploy.ps1`. CI/CD: `azure-pipelines.yml`.) It prints the **API endpoint URL** —
give that to your Glean admin. If a revision still fails to pull:
`az containerapp registry set --name <app> -g <rg> --server <acr>.azurecr.io --identity <identity-resource-id>`.

---

## Step 4 — Verify

**Roles landed** (Bicep can be right yet drift/policy can strip a role):
```bash
PRINCIPAL_ID=$(az identity show --ids <identity-resource-id> --query principalId -o tsv)
az role assignment list --assignee-object-id "$PRINCIPAL_ID" \
  --query "[].{role:roleDefinitionName, scope:scope}" -o table
# Expect: AcrPull (ACR) · Key Vault Secrets User (KV) · Storage Blob Data Contributor (storage).
# The SQL SELECT grant (mi_user.sql) is checked in the DB, not via RBAC.
```

**API health** (unauthenticated probe): `curl https://<api-fqdn>/health` → `{"status":"ok"}`.

Adding a view later = `GRANT SELECT` on it → rebuild (Step 1) → re-deploy (Step 3). No downtime.

---

## Delivery model (recap)

Allen & Co builds, owns, and operates everything; Nimble Gravity provides source + tooling and
holds **no** production access or credentials. Production database auth is the **managed
identity** (passwordless); the `glean_dev` SQL login is dev-only and removed at go-live.
