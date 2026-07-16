// Log Analytics workspace — the backing store for Container Apps logs and
// Application Insights. Without it, azure-diagnostics has nothing to query.
metadata description = 'Log Analytics workspace for Container Apps logs + App Insights.'

param name string
param location string = resourceGroup().location

@description('Log retention in days.')
param retentionInDays int = 30

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: name
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
  }
}

output id string = workspace.id
output customerId string = workspace.properties.customerId
#disable-next-line outputs-should-not-contain-secrets
output primarySharedKey string = workspace.listKeys().primarySharedKey
