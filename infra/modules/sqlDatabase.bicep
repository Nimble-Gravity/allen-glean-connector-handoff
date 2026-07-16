// Azure SQL logical server + database for the dev mirror.
// Mixed auth: a SQL admin (for setup) + an Entra admin (so the managed identity
// can be added as a DB user for the passwordless DB_AUTH_MODE=msi path).
metadata description = 'Azure SQL server + database (Basic) with Entra admin.'

param serverName string
param databaseName string = 'ems'
param location string = resourceGroup().location

@description('SQL administrator login (for initial setup / SQL-auth path).')
param administratorLogin string

@secure()
@description('SQL administrator password.')
param administratorPassword string

@description('Entra (Azure AD) admin display name (user or group).')
param aadAdminLogin string

@description('Entra (Azure AD) admin object ID (user or group).')
param aadAdminObjectId string

@description('Database SKU. Basic is cheapest/simplest for a mirror.')
param databaseSku string = 'Basic'

@description('Allow other Azure services (e.g. Container Apps) to reach the server.')
param allowAzureServices bool = true

resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: serverName
  location: location
  properties: {
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    administrators: {
      administratorType: 'ActiveDirectory'
      login: aadAdminLogin
      sid: aadAdminObjectId
      tenantId: subscription().tenantId
      principalType: 'User'
      azureADOnlyAuthentication: false
    }
  }
}

resource database 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: databaseName
  location: location
  sku: {
    name: databaseSku
    tier: databaseSku
  }
}

resource allowAzure 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = if (allowAzureServices) {
  parent: sqlServer
  // Start=End=0.0.0.0 is the special "Allow Azure services" rule.
  name: 'AllowAllWindowsAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

output serverFqdn string = sqlServer.properties.fullyQualifiedDomainName
output serverName string = sqlServer.name
output databaseName string = database.name
