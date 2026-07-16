// Custom Action API as an always-on Azure Container App (external HTTPS ingress).
metadata description = 'Container App for the Custom Action API (always-on, autoscaling).'

@description('App name.')
param name string

@description('Azure region.')
param location string = resourceGroup().location

@description('Resource ID of the Container Apps managed environment.')
param environmentId string

@description('Resource ID of the user-assigned managed identity (ACR pull + SQL/KV access).')
param userAssignedIdentityId string

@description('Client ID of that user-assigned identity — injected as AZURE_CLIENT_ID so the app selects the right identity for SQL (msi) and Blob access.')
param identityClientId string = ''

@description('ACR login server, e.g. myacr.azurecr.io.')
param acrLoginServer string

@description('Full image reference, e.g. myacr.azurecr.io/custom-action:latest.')
param image string

@description('Container port the API listens on.')
param targetPort int = 8000

@description('Expose the ingress externally (Glean calls it over HTTPS).')
param externalIngress bool = true

@description('Env vars: array of { name, value } and/or { name, secretRef }.')
param envVars array = []

@description('Secrets: array of { name, keyVaultUrl, identity } and/or { name, value }.')
param secrets array = []

param minReplicas int = 1
param maxReplicas int = 3

// Inject AZURE_CLIENT_ID (user-assigned identity) so the app selects the right
// identity for SQL (msi) and Blob access.
var envWithIdentity = empty(identityClientId)
  ? envVars
  : concat(envVars, [ { name: 'AZURE_CLIENT_ID', value: identityClientId } ])

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: externalIngress
        targetPort: targetPort
        transport: 'auto'
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      registries: [
        {
          server: acrLoginServer
          identity: userAssignedIdentityId
        }
      ]
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'custom-action'
          image: image
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: envWithIdentity
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: targetPort
              }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: targetPort
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

output fqdn string = app.properties.configuration.ingress.fqdn
output apiEndpoint string = 'https://${app.properties.configuration.ingress.fqdn}'
