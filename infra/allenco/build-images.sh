#!/usr/bin/env bash
# ============================================================================
# Container creation — build the TWO connector images and publish them to
# Allen & Co's Azure Container Registry (ACR). Build-only (no deploy); run
# deploy.sh afterwards, or hand the images to whoever deploys.
#
#   Image 1: indexer         (root Dockerfile)                — scheduled batch
#   Image 2: custom-action   (allenco_custom_action/Dockerfile) — always-on API
#
# Two modes:
#   (default) az acr build : builds server-side INSIDE the ACR — no local Docker.
#   --local              : docker build locally, then docker push to the ACR.
#
# Full step-by-step guide: infra/allenco/CLIENT-HANDOFF.md
# Machine prerequisites:  infra/allenco/PREREQUISITES.md
#   default : Azure CLI logged in (az login) + AcrPush (or Contributor) on the ACR.
#   --local : Docker + Azure CLI + AcrPush on the ACR.
#
# Usage:
#   ACR=<acr-name> ./infra/allenco/build-images.sh            # az acr build (recommended)
#   ACR=<acr-name> ./infra/allenco/build-images.sh --local    # local docker build + push
# ============================================================================
set -euo pipefail

MODE="acr"
if [ "${1:-}" = "--local" ]; then MODE="local"; fi

ACR="${ACR:?set ACR to the container registry name (without .azurecr.io)}"
INDEXER_TAG="${INDEXER_TAG:-indexer:latest}"
API_TAG="${API_TAG:-custom-action:latest}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOGIN_SERVER="${ACR}.azurecr.io"

if [ "$MODE" = "acr" ]; then
  echo ">> [1/2] az acr build → ${LOGIN_SERVER}/${INDEXER_TAG}"
  az acr build --registry "$ACR" --image "$INDEXER_TAG" \
    --file "$REPO_ROOT/Dockerfile" "$REPO_ROOT"

  echo ">> [2/2] az acr build → ${LOGIN_SERVER}/${API_TAG}"
  az acr build --registry "$ACR" --image "$API_TAG" \
    --file "$REPO_ROOT/allenco_custom_action/Dockerfile" "$REPO_ROOT"
else
  # Azure Container Apps runs linux/amd64, so we pin the platform. On an Apple
  # Silicon / ARM machine this builds via emulation (slower) but produces a
  # deployable image; a native arm64 build would fail to run on Container Apps.
  # (The recommended `az acr build` path already produces linux/amd64.)
  PLATFORM="${BUILD_PLATFORM:-linux/amd64}"
  echo ">> [1/4] docker build (local, ${PLATFORM}) → ${LOGIN_SERVER}/${INDEXER_TAG}"
  docker build --platform "$PLATFORM" -t "${LOGIN_SERVER}/${INDEXER_TAG}" -f "$REPO_ROOT/Dockerfile" "$REPO_ROOT"

  echo ">> [2/4] docker build (local, ${PLATFORM}) → ${LOGIN_SERVER}/${API_TAG}"
  docker build --platform "$PLATFORM" -t "${LOGIN_SERVER}/${API_TAG}" -f "$REPO_ROOT/allenco_custom_action/Dockerfile" "$REPO_ROOT"

  echo ">> [3/4] az acr login → ${ACR}"
  az acr login --name "$ACR"

  echo ">> [4/4] docker push"
  docker push "${LOGIN_SERVER}/${INDEXER_TAG}"
  docker push "${LOGIN_SERVER}/${API_TAG}"
fi

echo ">> Done. Images available in ${LOGIN_SERVER}:"
echo "     ${INDEXER_TAG}"
echo "     ${API_TAG}"
