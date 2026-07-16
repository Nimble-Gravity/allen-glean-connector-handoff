// Azure Key Vault (RBAC mode). Optionally grants "Key Vault Secrets User".
metadata description = 'Azure Key Vault (RBAC) + optional Secrets User role assignment.'

param name string
param location string = resourceGroup().location
param tenantId string = subscription().tenantId

@description('Optional principalId (managed identity) to grant Key Vault Secrets User.')
param secretsUserPrincipalId string = ''

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  properties: {
    tenantId: tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

// Built-in role: Key Vault Secrets User
var kvSecretsUserRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4633458b-17de-408a-b874-0445c86b69e6'
)

resource secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(secretsUserPrincipalId)) {
  name: guid(kv.id, secretsUserPrincipalId, kvSecretsUserRoleId)
  scope: kv
  properties: {
    roleDefinitionId: kvSecretsUserRoleId
    principalId: secretsUserPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output name string = kv.name
output id string = kv.id
output uri string = kv.properties.vaultUri
