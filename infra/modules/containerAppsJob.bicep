// Indexer as an Azure Container Apps scheduled Job (runs, indexes, exits).
metadata description = 'Container Apps Job for the connector indexer (scheduled, scale-to-zero).'

@description('Job name.')
param name string

@description('Azure region.')
param location string = resourceGroup().location

@description('Resource ID of the Container Apps managed environment.')
param environmentId string

@description('Resource ID of the user-assigned managed identity (ACR pull + SQL/KV access).')
param userAssignedIdentityId string

@description('Client ID of that user-assigned identity — injected as AZURE_CLIENT_ID so the indexer selects the right identity for SQL (msi) and Blob (sync state) access.')
param identityClientId string = ''

@description('ACR login server, e.g. myacr.azurecr.io.')
param acrLoginServer string

@description('Full image reference, e.g. myacr.azurecr.io/indexer:latest.')
param image string

@description('Cron schedule (UTC). Default: every 6 hours.')
param cronExpression string = '0 */6 * * *'

@description('Env vars: array of { name, value } and/or { name, secretRef }.')
param envVars array = []

@description('Secrets: array of { name, keyVaultUrl, identity } and/or { name, value }.')
param secrets array = []

@description('Per-run timeout (seconds).')
param replicaTimeout int = 3600

// Inject AZURE_CLIENT_ID (user-assigned identity) so the indexer selects the right
// identity for SQL (msi) and Blob (sync state) access.
var envWithIdentity = empty(identityClientId)
  ? envVars
  : concat(envVars, [ { name: 'AZURE_CLIENT_ID', value: identityClientId } ])

resource job 'Microsoft.App/jobs@2024-03-01' = {
  name: name
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedIdentityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: replicaTimeout
      replicaRetryLimit: 1
      scheduleTriggerConfig: {
        cronExpression: cronExpression
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: acrLoginServer
          identity: userAssignedIdentityId
        }
      ]
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'indexer'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: envWithIdentity
        }
      ]
    }
  }
}

output name string = job.name
