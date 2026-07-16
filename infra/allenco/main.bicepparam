using './main.bicep'

// Fill these with Allen & Co's existing resource identifiers before deploying.
// Values here are placeholders.

param acrLoginServer = 'allencoacr.azurecr.io'
param managedEnvironmentId = '/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.App/managedEnvironments/<env-name>'
param userAssignedIdentityId = '/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<identity-name>'
// Client ID (GUID) of that identity: az identity show ... --query clientId -o tsv
param managedIdentityClientId = '00000000-0000-0000-0000-000000000000'
param dbServerFqdn = 'allenco-mi.<zone>.database.windows.net'
param dbName = 'ems'
param dbAuthMode = 'msi'
param gleanInstance = 'allenandco'
param gleanDatasource = 'allenco_ems'
param keyVaultName = 'allenco-kv'
param syncStateBlobAccountUrl = 'https://allencosyncstate.blob.core.windows.net/'
// indexerImage / apiImage are passed by deploy.sh (default indexer:latest / custom-action:latest).
