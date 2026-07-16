// Windows dev VM (Server 2022) with NO public IP — reachable only via Bastion.
// Carries a user-assigned managed identity so it can hit the mirror SQL
// passwordlessly (DB_AUTH_MODE=msi) and pull secrets from Key Vault.
metadata description = 'Windows Server 2022 dev VM (no public IP) + managed identity.'

param name string
param location string = resourceGroup().location

@description('Resource ID of the VM subnet.')
param subnetId string

@description('Resource ID of the user-assigned managed identity to attach.')
param userAssignedIdentityId string

param adminUsername string

@secure()
param adminPassword string

param vmSize string = 'Standard_B2s'

resource nic 'Microsoft.Network/networkInterfaces@2023-11-01' = {
  name: '${name}-nic'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: {
            id: subnetId
          }
          privateIPAllocationMethod: 'Dynamic'
          // Intentionally no publicIPAddress — access is via Azure Bastion only.
        }
      }
    ]
  }
}

resource vm 'Microsoft.Compute/virtualMachines@2023-09-01' = {
  name: name
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedIdentityId}': {}
    }
  }
  properties: {
    hardwareProfile: {
      vmSize: vmSize
    }
    osProfile: {
      computerName: take(name, 15)
      adminUsername: adminUsername
      adminPassword: adminPassword
    }
    storageProfile: {
      imageReference: {
        publisher: 'MicrosoftWindowsServer'
        offer: 'WindowsServer'
        sku: '2022-datacenter-azure-edition'
        version: 'latest'
      }
      osDisk: {
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
        }
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: nic.id
        }
      ]
    }
  }
}

output vmName string = vm.name
