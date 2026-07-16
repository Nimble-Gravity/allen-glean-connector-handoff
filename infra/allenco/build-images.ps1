# ============================================================================
# Container creation (PowerShell) — build the two connector images and publish
# them to Allen & Co's ACR.
# Full step-by-step guide: infra/allenco/CLIENT-HANDOFF.md
# Machine prerequisites:  infra/allenco/PREREQUISITES.md
#
# Usage:
#   $env:ACR="<acr-name>"; ./infra/allenco/build-images.ps1            # az acr build
#   $env:ACR="<acr-name>"; ./infra/allenco/build-images.ps1 -Local     # local docker
# ============================================================================
param([switch]$Local)
$ErrorActionPreference = 'Stop'

$ACR = $env:ACR; if (-not $ACR) { throw 'Set $env:ACR to the ACR name (without .azurecr.io).' }
$IndexerTag = if ($env:INDEXER_TAG) { $env:INDEXER_TAG } else { 'indexer:latest' }
$ApiTag     = if ($env:API_TAG)     { $env:API_TAG }     else { 'custom-action:latest' }
$RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot '..' '..')).Path
$LoginServer = "$ACR.azurecr.io"
$IndexerDockerfile = Join-Path $RepoRoot 'Dockerfile'
$ApiDockerfile     = Join-Path $RepoRoot 'allenco_custom_action/Dockerfile'

if (-not $Local) {
  Write-Host ">> [1/2] az acr build -> $LoginServer/$IndexerTag"
  az acr build --registry $ACR --image $IndexerTag --file $IndexerDockerfile $RepoRoot
  Write-Host ">> [2/2] az acr build -> $LoginServer/$ApiTag"
  az acr build --registry $ACR --image $ApiTag --file $ApiDockerfile $RepoRoot
}
else {
  # Azure Container Apps runs linux/amd64, so we pin the platform. On ARM this
  # builds via emulation (slower) but produces a deployable image. (The
  # recommended `az acr build` path already produces linux/amd64.)
  $Platform = if ($env:BUILD_PLATFORM) { $env:BUILD_PLATFORM } else { 'linux/amd64' }
  Write-Host ">> [1/4] docker build ($Platform) -> $LoginServer/$IndexerTag"
  docker build --platform $Platform -t "$LoginServer/$IndexerTag" -f $IndexerDockerfile $RepoRoot
  Write-Host ">> [2/4] docker build ($Platform) -> $LoginServer/$ApiTag"
  docker build --platform $Platform -t "$LoginServer/$ApiTag" -f $ApiDockerfile $RepoRoot
  Write-Host ">> [3/4] az acr login -> $ACR"
  az acr login --name $ACR
  Write-Host ">> [4/4] docker push"
  docker push "$LoginServer/$IndexerTag"
  docker push "$LoginServer/$ApiTag"
}

Write-Host ">> Done. Images available in ${LoginServer}: $IndexerTag, $ApiTag"
