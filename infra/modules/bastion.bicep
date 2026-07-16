// Azure Bastion (Standard) — brokers RDP/SSH + native-client tunnels to VMs with
// no public IP. Standard SKU is required for the native-client tunnel feature.
metadata description = 'Azure Bastion Standard + its public IP.'

param name string
param location string = resourceGroup().location

@description('Resource ID of the AzureBastionSubnet.')
param bastionSubnetId string

resource pip 'Microsoft.Network/publicIPAddresses@2023-11-01' = {
  name: '${name}-pip'
  location: location
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

resource bastion 'Microsoft.Network/bastionHosts@2023-11-01' = {
  name: name
  location: location
  sku: {
    name: 'Standard'
  }
  properties: {
    enableTunneling: true
    ipConfigurations: [
      {
        name: 'ipconf'
        properties: {
          subnet: {
            id: bastionSubnetId
          }
          publicIPAddress: {
            id: pip.id
          }
        }
      }
    ]
  }
}

output name string = bastion.name
