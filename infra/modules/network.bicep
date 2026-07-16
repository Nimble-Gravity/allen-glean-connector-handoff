// VNet + subnets for the dev mirror: Container Apps (delegated), data (SQL PE),
// AzureBastionSubnet, and the dev VM subnet.
metadata description = 'VNet with subnets for Container Apps env, SQL, Bastion and the dev VM.'

param name string
param location string = resourceGroup().location
param addressPrefix string = '10.20.0.0/16'
param containerAppsSubnetPrefix string = '10.20.0.0/23'
param dataSubnetPrefix string = '10.20.2.0/24'
param bastionSubnetPrefix string = '10.20.3.0/26'
param vmSubnetPrefix string = '10.20.4.0/24'

resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: name
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [ addressPrefix ]
    }
    subnets: [
      {
        name: 'snet-containerapps'
        properties: {
          addressPrefix: containerAppsSubnetPrefix
          delegations: [
            {
              name: 'containerapps-delegation'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'snet-data'
        properties: {
          addressPrefix: dataSubnetPrefix
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        // Name is required to be exactly 'AzureBastionSubnet'.
        name: 'AzureBastionSubnet'
        properties: {
          addressPrefix: bastionSubnetPrefix
        }
      }
      {
        name: 'snet-vm'
        properties: {
          addressPrefix: vmSubnetPrefix
        }
      }
    ]
  }
}

output vnetId string = vnet.id
output containerAppsSubnetId string = vnet.properties.subnets[0].id
output dataSubnetId string = vnet.properties.subnets[1].id
output bastionSubnetId string = vnet.properties.subnets[2].id
output vmSubnetId string = vnet.properties.subnets[3].id
