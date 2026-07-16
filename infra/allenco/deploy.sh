#!/usr/bin/env bash
# ============================================================================
# Deploy the Allen & Co connector into Allen & Co's Azure — DEPLOY ONLY.
#
# The two images must ALREADY be in the ACR. Build them first with
# infra/allenco/build-images.sh (or the azure-pipelines.yml). This script does
# NOT build — it deploys the Container Apps Job + App from the given image tags.
#
# Prereqs (see infra/allenco/CLIENT-HANDOFF.md):
#   - az CLI logged in to Allen's tenant/subscription
#   - the two images already built into the ACR (build-images.sh)
#   - the surrounding infra provisioned: Container Apps env, VNet, Key Vault +
#     secrets, storage account (sync state), and a managed identity granted
#     AcrPull + Key Vault Secrets User + Storage Blob Data Contributor + SELECT
#     on the four views (mi_user.sql)
#   - infra/allenco/main.bicepparam filled with Allen's resource IDs
#
# Usage:
#   RG=<resource-group> INDEXER_TAG=indexer:latest API_TAG=custom-action:latest \
#     ./infra/allenco/deploy.sh
# ============================================================================
set -euo pipefail

RG="${RG:?set RG to the target resource group}"
INDEXER_TAG="${INDEXER_TAG:-indexer:latest}"
API_TAG="${API_TAG:-custom-action:latest}"
DEPLOYMENT_NAME="${DEPLOYMENT_NAME:-allenco-connector}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo ">> Deploying Container Apps (indexer Job + Custom Action App) from prebuilt images"
echo "   indexer=$INDEXER_TAG  api=$API_TAG"
az deployment group create \
  --name "$DEPLOYMENT_NAME" \
  --resource-group "$RG" \
  --template-file "$REPO_ROOT/infra/allenco/main.bicep" \
  --parameters "$REPO_ROOT/infra/allenco/main.bicepparam" \
  --parameters indexerImage="$INDEXER_TAG" apiImage="$API_TAG"

echo ">> Done. Custom Action API endpoint (give this to the Glean admin):"
az deployment group show --resource-group "$RG" --name "$DEPLOYMENT_NAME" \
  --query properties.outputs.apiEndpoint.value -o tsv
