# Allen & Co Glean Connector — Glean access & Indexing API key

*Hand-off from Nimble Gravity. This guide is for **Allen & Co's Glean administrator**. The
connector pushes documents into Glean through the **Indexing API**, so it needs three things
from your Glean environment. Please complete the steps below and share the results with Nimble
Gravity **securely** (see Step 4).*

## What the connector needs from Glean

| Item | Becomes the config value | Where it comes from |
|---|---|---|
| A **custom datasource** | `GLEAN_DATASOURCE` (`allenco_ems`) | you create it (Step 1) |
| An **Indexing API token** | `GLEAN_INDEXING_API_KEY` | you generate it (Step 2) |
| Your **instance name** | `GLEAN_INSTANCE` | your Glean subdomain (Step 3) |

> **Who can do this:** creating an Indexing API token requires a Glean **Super Admin**. A plain
> *Admin* cannot create indexing tokens, and an *API Token Creator* can only create self-scoped
> tokens — neither is sufficient here. Please have a **Super Admin** perform Steps 1–2.

---

## Step 1 — Create the custom datasource

In the Glean **Admin Console → Data sources → Add data source → Custom**, fill in the basics
and **Publish**. Recommended values:

| Field | Value | Notes |
|---|---|---|
| **name** | `allenco_ems` | The unique datasource id. Must match the connector's `GLEAN_DATASOURCE` **exactly** — please keep this value. |
| **displayName** | e.g. `Allen & Co EMS` | What users see in search results. |
| **datasourceCategory** | `CRM` | Best fit for EMS (attendees, companies, participation = relationship/customer data). Glean requires a category — it cannot be left `UNCATEGORIZED`. |
| **urlRegex** | `https://<ems-host>/.*` — **confirm the EMS host** | Required. A regex that must match the **view URL** the connector stamps on each record. Tell NG whether EMS records have their own web URL and on what host; the pattern and the connector's URL are then set together. |
| **isUserReferencedByEmail** | `true` | The connector identifies users by email. *(Confirm with NG — this ties to the AD/Entra permission model we're still finalizing.)* |

Nimble Gravity can join a screen-share to co-fill the *confirm with NG* fields — they depend on
the final EMS document shaping.

---

## Step 2 — Create the Indexing API token

In the Glean **Admin Console → Platform → API Tokens → Indexing Tokens** tab, click
**Add API token**:

- **Name:** e.g. `allenco-connector-indexing`.
- **Permissions:** indexing tokens are **global by default** — that's exactly what the connector
  needs (it indexes both documents *and* the user/permission records for the datasource). No
  per-scope configuration is required.
- **Expiration:** an expiration date is **required**. Pick a date and note it — plan to rotate
  the token before it expires (rotating = generate a new token and update the stored secret).
- **Optional:** you can add an IP allow-list later, once the connector's container egress IPs are
  known, and enable automatic rotation.

> ⚠️ **The token is shown only once.** Copy it immediately and store it securely — Glean cannot
> display it again. If it's lost, generate a new one.

---

## Step 3 — Find your instance name (Server URL)

The connector reaches the Indexing API at:

```
https://<instance>-be.glean.com/api/index/v1/…
```

> ⚠️ **Your `<instance>` is *not* your Glean app subdomain.** It is your **server-instance
> name**, which usually differs from the app URL and often carries a suffix like `-prod`
> (Glean's own example is `acme-prod-be.glean.com`). The `-be.glean.com` domain has **no
> wildcard DNS**, so `<instance>-be.glean.com` resolves *only* for your exact provisioned
> instance — guessing the app subdomain will fail to resolve.

Read the authoritative value in your admin console:

1. Go to **`https://app.glean.com/admin/about-glean`** (the **About** page).
2. Find the **Server instance / Server URL** field — that is your real backend host.
3. (Optional self-check) run `nslookup <that-value>-be.glean.com`; when it returns an IP
   address, that's the correct instance.

The **`<instance>` value** (the part before `-be.glean.com`) becomes `GLEAN_INSTANCE`.

> If your Glean is a **private / VPC deployment** with no public `-be.glean.com` host, the
> About page still shows your actual API URL — send Nimble Gravity that complete **Server
> URL** instead, and the connector will be pointed directly at it.

---

## Step 4 — Hand off to Nimble Gravity (securely)

Share these three values over a **secure channel** (your secrets manager / Key Vault entry — not
email or chat):

| Value | Config key |
|---|---|
| the Indexing API token from Step 2 | `GLEAN_INDEXING_API_KEY` |
| your instance name from Step 3 | `GLEAN_INSTANCE` |
| the datasource name (`allenco_ems`) | `GLEAN_DATASOURCE` |

In production these live in Allen & Co's **Key Vault** (as the secret `glean-indexing-api-key`);
during development they go into the connector's `.env` on the dev machine.

---

## FYI — one key that does *not* come from Glean

The always-on **Custom Action API** (a separate component, deployed later) authenticates Glean's
live calls with a bearer secret, `CUSTOM_ACTION_API_KEY`. That key is **generated by Allen & Co**
(any strong random secret) — Glean does **not** issue it. Glean references it later when the
**Custom Action** is configured against the API endpoint. **No action is needed now** — this is
just so it isn't confused with the Indexing API token above.

---

## Reference (Glean's own documentation)

- Indexing API authentication — https://developers.glean.com/api-info/indexing/authentication/overview
- Set up a custom datasource — https://developers.glean.com/api-info/indexing/getting-started/setup-datasource

*Questions on any of the above → Nimble Gravity.*
