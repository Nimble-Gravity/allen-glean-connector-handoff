// ============================================================================
// Allen & Co connector — DEPLOY-ONLY into existing Azure infrastructure.
//
// Allen & Co owns and provisions the surrounding infra (ACR, Container Apps
// environment, VNet, Key Vault, managed identity, SQL MI) per
// docs/allenco-database-connectivity.md §B. This template deploys ONLY the two
// workloads (indexer Job + Custom Action API App) into that existing infra and
// wires their config/secrets.
//
// Prereqs Allen provisions (see CLIENT-HANDOFF.md → "Before you deploy"): the ACR, a
// Container Apps managed environment (VNet-injected), a user-assigned managed
// identity granted AcrPull on the ACR + "Key Vault Secrets User" on the KV + a
// SQL user with SELECT on the 4 views, and the Key Vault secrets.
// ============================================================================

targetScope = 'resourceGroup'
metadata description = 'Allen & Co connector — deploy Job + App into existing Azure infra.'

@description('Azure region.')
param location string = resourceGroup().location

@description('ACR login server (existing), e.g. allencoacr.azurecr.io.')
param acrLoginServer string

@description('Indexer image repo:tag inside the ACR.')
param indexerImage string = 'indexer:latest'

@description('Custom Action API image repo:tag inside the ACR.')
param apiImage string = 'custom-action:latest'

@description('Resource ID of the existing Container Apps managed environment.')
param managedEnvironmentId string

@description('Resource ID of the existing user-assigned managed identity.')
param userAssignedIdentityId string

@description('Client ID (GUID) of that user-assigned managed identity — required so the workloads select the right identity for SQL (msi) and Blob (sync state) access. Allen provides this alongside the identity resource ID.')
param managedIdentityClientId string

@description('Azure SQL MI FQDN (private), e.g. allenco-mi.<zone>.database.windows.net.')
param dbServerFqdn string

@description('Database name.')
param dbName string = 'ems'

@description('DB auth mode: msi (passwordless, recommended in Azure) / default / sql.')
@allowed([ 'msi', 'default', 'sql' ])
param dbAuthMode string = 'msi'

@description('Glean instance name.')
param gleanInstance string

@description('Glean datasource namespace.')
param gleanDatasource string = 'allenco_ems'

@description('Blob endpoint of the storage account that holds the incremental sync state, e.g. https://<account>.blob.core.windows.net/. The managed identity needs Storage Blob Data Contributor on it.')
param syncStateBlobAccountUrl string

@description('Blob container name for the sync state.')
param syncStateContainer string = 'sync-state'

@description('Existing Key Vault name holding the Glean/API secrets.')
param keyVaultName string

@description('KV secret name: Glean indexing API key.')
param gleanIndexingApiKeySecretName string = 'glean-indexing-api-key'

@description('KV secret name: Custom Action API bearer key.')
param customActionApiKeySecretName string = 'custom-action-api-key'

@description('KV secret name: Slack webhook URL (optional).')
param slackWebhookSecretName string = 'slack-webhook-url'

param indexerName string = 'allenco-indexer'
param apiName string = 'allenco-custom-action'

@description('Indexer schedule (UTC cron). Default every 6 hours.')
param cronExpression string = '0 */6 * * *'

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

var kvUri = kv.properties.vaultUri

// Secrets pulled from Key Vault via the managed identity.
var indexerSecrets = [
  {
    name: 'glean-indexing-api-key'
    keyVaultUrl: '${kvUri}secrets/${gleanIndexingApiKeySecretName}'
    identity: userAssignedIdentityId
  }
  {
    name: 'slack-webhook-url'
    keyVaultUrl: '${kvUri}secrets/${slackWebhookSecretName}'
    identity: userAssignedIdentityId
  }
]

var apiSecrets = [
  {
    name: 'custom-action-api-key'
    keyVaultUrl: '${kvUri}secrets/${customActionApiKeySecretName}'
    identity: userAssignedIdentityId
  }
]

// Common DB config. auth_mode=msi means no DB_USER/DB_PASSWORD (passwordless).
var commonDbEnv = [
  { name: 'DB_SERVER', value: dbServerFqdn }
  { name: 'DB_NAME', value: dbName }
  { name: 'DB_AUTH_MODE', value: dbAuthMode }
  { name: 'DB_TRUST_SERVER_CERTIFICATE', value: 'false' } // Azure MI has a real cert
]

var indexerEnv = concat(commonDbEnv, [
  { name: 'GLEAN_ENABLE_INDEXING', value: 'true' }
  { name: 'GLEAN_INSTANCE', value: gleanInstance }
  { name: 'GLEAN_DATASOURCE', value: gleanDatasource }
  { name: 'GLEAN_INDEXING_API_KEY', secretRef: 'glean-indexing-api-key' }
  { name: 'NOTIFICATIONS_ENABLED', value: 'true' }
  { name: 'SLACK_WEBHOOK_URL', secretRef: 'slack-webhook-url' }
  // Incremental sync state lives in Blob Storage (the MI is read-only).
  { name: 'SYNC_STATE_BACKEND', value: 'blob' }
  { name: 'SYNC_STATE_BLOB_ACCOUNT_URL', value: syncStateBlobAccountUrl }
  { name: 'SYNC_STATE_BLOB_CONTAINER', value: syncStateContainer }
])

var apiEnv = concat(commonDbEnv, [
  { name: 'CUSTOM_ACTION_API_KEY', secretRef: 'custom-action-api-key' }
])

module indexer '../modules/containerAppsJob.bicep' = {
  name: 'indexer-job'
  params: {
    name: indexerName
    location: location
    environmentId: managedEnvironmentId
    userAssignedIdentityId: userAssignedIdentityId
    identityClientId: managedIdentityClientId
    acrLoginServer: acrLoginServer
    image: '${acrLoginServer}/${indexerImage}'
    cronExpression: cronExpression
    envVars: indexerEnv
    secrets: indexerSecrets
  }
}

module api '../modules/containerApp.bicep' = {
  name: 'custom-action-app'
  params: {
    name: apiName
    location: location
    environmentId: managedEnvironmentId
    userAssignedIdentityId: userAssignedIdentityId
    identityClientId: managedIdentityClientId
    acrLoginServer: acrLoginServer
    image: '${acrLoginServer}/${apiImage}'
    envVars: apiEnv
    secrets: apiSecrets
  }
}

@description('Custom Action API endpoint — give this to the Glean admin.')
output apiEndpoint string = api.outputs.apiEndpoint
