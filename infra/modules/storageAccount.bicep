// Storage account + blob container for the connector's incremental sync state.
// The EMS Replica is read-only, so the "persist sync metadata to avoid
// re-processing" state lives HERE (a blob), never in the Managed Instance.
metadata description = 'Storage account + blob container for sync state (+ optional RBAC grant).'

param name string
param location string = resourceGroup().location
param containerName string = 'sync-state'

@description('Optional principalId (managed identity) to grant Storage Blob Data Contributor.')
param dataContributorPrincipalId string = ''

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: containerName
  properties: {
    publicAccess: 'None'
  }
}

// Built-in role: Storage Blob Data Contributor
var blobContributorRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)

resource grant 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(dataContributorPrincipalId)) {
  name: guid(storage.id, dataContributorPrincipalId, blobContributorRoleId)
  scope: storage
  properties: {
    roleDefinitionId: blobContributorRoleId
    principalId: dataContributorPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output name string = storage.name
output blobEndpoint string = storage.properties.primaryEndpoints.blob
output containerName string = containerName
