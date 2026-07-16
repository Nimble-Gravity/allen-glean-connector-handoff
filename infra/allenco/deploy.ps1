# ============================================================================
# Deploy the Allen & Co connector into Allen's Azure — DEPLOY ONLY (PowerShell).
#
# The two images must ALREADY be in the ACR (build them first with
# build-images.ps1 or the azure-pipelines.yml). This does NOT build.
# See deploy.sh / CLIENT-HANDOFF.md for the full prerequisites.
#
# Usage:
#   $env:RG="<resource-group>"; ./infra/allenco/deploy.ps1
# ============================================================================
$ErrorActionPreference = 'Stop'

$RG = $env:RG; if (-not $RG) { throw 'Set $env:RG to Allen & Co''s resource group.' }
$IndexerTag = if ($env:INDEXER_TAG) { $env:INDEXER_TAG } else { 'indexer:latest' }
$ApiTag     = if ($env:API_TAG)     { $env:API_TAG }     else { 'custom-action:latest' }
$DeployName = if ($env:DEPLOYMENT_NAME) { $env:DEPLOYMENT_NAME } else { 'allenco-connector' }
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..' '..')).Path

Write-Host ">> Deploying Container Apps (indexer Job + Custom Action App) from prebuilt images"
Write-Host "   indexer=$IndexerTag  api=$ApiTag"
az deployment group create `
  --name $DeployName `
  --resource-group $RG `
  --template-file (Join-Path $RepoRoot 'infra/allenco/main.bicep') `
  --parameters (Join-Path $RepoRoot 'infra/allenco/main.bicepparam') `
  --parameters indexerImage=$IndexerTag apiImage=$ApiTag

Write-Host ">> Done. Custom Action API endpoint (give this to the Glean admin):"
az deployment group show --resource-group $RG --name $DeployName `
  --query properties.outputs.apiEndpoint.value -o tsv
