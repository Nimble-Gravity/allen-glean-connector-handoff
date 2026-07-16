// Sets a single secret in an existing Key Vault.
metadata description = 'Create/update one Key Vault secret.'

param keyVaultName string
param name string

@secure()
param value string

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource secret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: kv
  name: name
  properties: {
    value: value
  }
}

output uri string = secret.properties.secretUri
