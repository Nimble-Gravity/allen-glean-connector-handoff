// Azure Container Registry. Optionally grants AcrPull to a managed identity.
metadata description = 'Azure Container Registry (+ optional AcrPull role assignment).'

param name string
param location string = resourceGroup().location
param sku string = 'Basic'

@description('Optional principalId (managed identity) to grant AcrPull.')
param pullPrincipalId string = ''

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  sku: {
    name: sku
  }
  properties: {
    adminUserEnabled: false
  }
}

// Built-in role: AcrPull
var acrPullRoleId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(pullPrincipalId)) {
  name: guid(acr.id, pullPrincipalId, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: acrPullRoleId
    principalId: pullPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output loginServer string = acr.properties.loginServer
output name string = acr.name
output id string = acr.id
