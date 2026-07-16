// Azure Container Apps managed environment, VNet-injected.
metadata description = 'Container Apps managed environment (VNet-injected) + optional Log Analytics.'

param name string
param location string = resourceGroup().location

@description('Resource ID of the infrastructure subnet (delegated to Microsoft.App/environments).')
param infrastructureSubnetId string

@description('Set true to keep the environment internal (no public ingress). The mirror uses false so we can hit the API.')
param internal bool = false

@description('Optional Log Analytics workspace customerId; empty = Azure-managed logs.')
param logAnalyticsCustomerId string = ''

@secure()
@description('Optional Log Analytics shared key (required if customerId is set).')
param logAnalyticsSharedKey string = ''

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: name
  location: location
  properties: {
    vnetConfiguration: {
      infrastructureSubnetId: infrastructureSubnetId
      internal: internal
    }
    appLogsConfiguration: empty(logAnalyticsCustomerId)
      ? null
      : {
          destination: 'log-analytics'
          logAnalyticsConfiguration: {
            customerId: logAnalyticsCustomerId
            sharedKey: logAnalyticsSharedKey
          }
        }
  }
}

output id string = env.id
output name string = env.name
