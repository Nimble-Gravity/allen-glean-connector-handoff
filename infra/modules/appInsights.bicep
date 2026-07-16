// Application Insights (workspace-based) — app-level telemetry for both
// components. The connection string is passed to the containers as
// APPLICATIONINSIGHTS_CONNECTION_STRING.
metadata description = 'Workspace-based Application Insights.'

param name string
param location string = resourceGroup().location

@description('Resource ID of the Log Analytics workspace to back this component.')
param workspaceId string

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: name
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspaceId
  }
}

output connectionString string = appInsights.properties.ConnectionString
output instrumentationKey string = appInsights.properties.InstrumentationKey
