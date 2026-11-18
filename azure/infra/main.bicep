// Model Audit Kit on Azure: everything Phase 1 needs, in one resource group.
//
//   Storage account (Data Lake Gen2)  audit-inputs, audit-reports, app-package containers
//   Function App (Flex Consumption)   runs the audit when submit.json arrives; managed identity
//   Azure SQL Database (free offer)   audit.runs / check_results / explanations; Entra-only auth
//   Key Vault (RBAC)                  holds the Foundry API key; the app reads it by reference
//   Log Analytics + App Insights      logs, failures, the alert below
//   Microsoft Foundry (optional)      AI Services account + a small chat model deployment
//   Budget + failure alert (optional) email when spend passes the budget or an audit fails
//
// Deploy with azure/scripts/deploy.ps1 (it fills in your user id and IP for you).

targetScope = 'resourceGroup'

@description('Short name used in every resource name (lowercase letters and digits).')
@minLength(3)
@maxLength(10)
param prefix string = 'maudit'

param location string = resourceGroup().location

@description('Object id of the person deploying (az ad signed-in-user show --query id -o tsv). Becomes SQL admin and Key Vault secrets officer.')
param deployerObjectId string

@description('Sign-in name of the deployer, shown as the SQL Entra admin.')
param deployerLogin string

@description('Your public IP, so sqlcmd can reach the SQL server from your PC. Empty = no rule.')
param clientIp string = ''

@description('Region for Azure SQL, if the main region is not accepting new SQL servers.')
param sqlLocation string = location

@description('Create a Microsoft Foundry (Azure OpenAI) resource and model deployment.')
param deployFoundry bool = true

@description('Region for Foundry, if the model is not offered in the main region.')
param foundryLocation string = location

@description('Chat model to deploy. Check availability: Foundry portal > Models.')
param modelName string = 'gpt-4.1-mini'
param modelVersion string = '2025-04-14'
@description('Thousands of tokens per minute. 10 is plenty for this workload.')
param modelCapacity int = 10

@description('Email for the budget and failure alerts. Empty = no alerts.')
param alertEmail string = ''
@description('Monthly budget for this resource group, in your billing currency.')
param monthlyBudget int = 10
param budgetStartDate string = utcNow('yyyy-MM-01')

var suffix = uniqueString(resourceGroup().id)
var names = {
  storage: toLower('${prefix}st${take(suffix, 8)}')
  plan: '${prefix}-plan'
  func: '${prefix}-func-${take(suffix, 6)}'
  logs: '${prefix}-logs'
  insights: '${prefix}-insights'
  vault: '${prefix}-kv-${take(suffix, 6)}'
  sql: '${prefix}-sql-${take(suffix, 6)}'
  db: 'auditdb'
  foundry: '${prefix}-ai-${take(suffix, 6)}'
}

// Built-in role definition ids
var roles = {
  blobOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  queueContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  tableContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  blobContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  kvSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  openAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
}

// ---------------- Monitoring ----------------

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: names.logs
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 } // hard cap so a log loop cannot run up a bill
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: names.insights
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
    DisableLocalAuth: false
  }
}

// ---------------- Storage (Data Lake Gen2) ----------------

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: names.storage
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true            // Data Lake Storage Gen2: folders, and OneLake shortcuts from Fabric
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false   // Entra ID only: no account keys in use anywhere
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    defaultToOAuthAuthentication: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for c in ['audit-inputs', 'audit-reports', 'app-package']: {
  parent: blobService
  name: c
  properties: { publicAccess: 'None' }
}]

// Client data is deleted 30 days after upload, matching the promise in templates/CLIENT-DATA-SPEC.md.
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'delete-client-inputs-after-30-days'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: { blobTypes: ['blockBlob'], prefixMatch: ['audit-inputs/'] }
            actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: 30 } } }
          }
        }
      ]
    }
  }
}

// ---------------- Key Vault ----------------

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: names.vault
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

// ---------------- Microsoft Foundry (Azure OpenAI) ----------------

resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' = if (deployFoundry) {
  name: names.foundry
  location: foundryLocation
  kind: 'AIServices'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: names.foundry
    publicNetworkAccess: 'Enabled'
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = if (deployFoundry) {
  parent: foundry
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
  }
}

// The API key goes straight from Foundry into Key Vault; no person ever copies it.
resource foundryKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (deployFoundry) {
  parent: vault
  name: 'foundry-api-key'
  properties: {
    #disable-next-line BCP422
    value: deployFoundry ? foundry.listKeys().key1 : ''
    contentType: 'Microsoft Foundry API key for the audit explainer'
  }
}

// ---------------- Azure SQL (free offer) ----------------

resource sql 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: names.sql
  location: sqlLocation
  properties: {
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    administrators: {
      administratorType: 'ActiveDirectory'
      azureADOnlyAuthentication: true   // no SQL logins or passwords at all
      login: deployerLogin
      sid: deployerObjectId
      tenantId: subscription().tenantId
      principalType: 'User'
    }
  }
}

resource db 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sql
  name: names.db
  location: sqlLocation
  sku: { name: 'GP_S_Gen5', tier: 'GeneralPurpose', family: 'Gen5', capacity: 2 }
  properties: {
    useFreeLimit: true                       // free offer: 100k vCore-seconds + 32 GB a month
    freeLimitExhaustionBehavior: 'AutoPause' // pause instead of billing when the free amount runs out
    autoPauseDelay: 60
    minCapacity: json('0.5')
    maxSizeBytes: 34359738368
  }
}

// Lets Azure services (the Function) reach the server. Access still requires Entra authentication.
resource sqlAllowAzure 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sql
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource sqlAllowClient 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = if (!empty(clientIp)) {
  parent: sql
  name: 'AllowDeployerIp'
  properties: { startIpAddress: clientIp, endIpAddress: clientIp }
}

// ---------------- Function App (Flex Consumption) ----------------

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: names.plan
  location: location
  kind: 'functionapp'
  sku: { name: 'FC1', tier: 'FlexConsumption' }
  properties: { reserved: true }
}

var foundryEndpoint = deployFoundry ? 'https://${names.foundry}.openai.azure.com' : ''

resource func 'Microsoft.Web/sites@2024-04-01' = {
  name: names.func
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storage.name }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
        // Identity-based connection used by the blob trigger (connection="AuditStorage")
        { name: 'AuditStorage__blobServiceUri', value: storage.properties.primaryEndpoints.blob }
        { name: 'AuditStorage__queueServiceUri', value: storage.properties.primaryEndpoints.queue }
        { name: 'AUDIT_STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
        { name: 'AUDIT_SQL_SERVER', value: sql.properties.fullyQualifiedDomainName }
        { name: 'AUDIT_SQL_DATABASE', value: names.db }
        { name: 'AUDIT_SQL_AUTH', value: 'ActiveDirectoryMSI' }
        { name: 'AZURE_OPENAI_ENDPOINT', value: foundryEndpoint }
        { name: 'AZURE_OPENAI_DEPLOYMENT', value: deployFoundry ? modelName : '' }
        // Key Vault reference: the platform fetches the secret with the app's managed identity.
        { name: 'AZURE_OPENAI_API_KEY', value: deployFoundry ? '@Microsoft.KeyVault(VaultName=${names.vault};SecretName=foundry-api-key)' : '' }
      ]
    }
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}app-package'
          authentication: { type: 'SystemAssignedIdentity' }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 10   // small cap: audits are occasional and this limits cost
        instanceMemoryMB: 2048
      }
      runtime: { name: 'python', version: '3.12' }
    }
  }
  dependsOn: [containers]
}

// ---------------- Role assignments ----------------

resource funcBlobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, func.id, roles.blobOwner)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobOwner)
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource funcQueue 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, func.id, roles.queueContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.queueContributor)
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource funcTable 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, func.id, roles.tableContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.tableContributor)
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// You can upload client batches with `az storage blob upload --auth-mode login`.
resource deployerBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, deployerObjectId, roles.blobContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.blobContributor)
    principalId: deployerObjectId
    principalType: 'User'
  }
}

resource funcSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, func.id, roles.kvSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsUser)
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerSecrets 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, deployerObjectId, roles.kvSecretsOfficer)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.kvSecretsOfficer)
    principalId: deployerObjectId
    principalType: 'User'
  }
}

// Also lets the app call Foundry with Entra ID if you later remove the key setting.
resource funcOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployFoundry) {
  scope: foundry
  name: guid(names.foundry, func.id, roles.openAiUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.openAiUser)
    principalId: func.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------- Alerts and budget (optional) ----------------

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = if (!empty(alertEmail)) {
  name: '${prefix}-alerts'
  location: 'global'
  properties: {
    groupShortName: take('${prefix}alert', 12)
    enabled: true
    emailReceivers: [{ name: 'owner', emailAddress: alertEmail, useCommonAlertSchema: true }]
  }
}

// Fires when an audit throws, or a batch is rejected for bad input (AUDIT_INPUT_ERROR, logged at Error).
resource failureAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = if (!empty(alertEmail)) {
  name: '${prefix}-audit-failures'
  location: location
  properties: {
    displayName: 'Model audit: failed or rejected runs'
    severity: 2
    enabled: true
    scopes: [insights.id]
    evaluationFrequency: 'PT15M'
    windowSize: 'PT15M'
    criteria: {
      allOf: [
        {
          query: 'union isfuzzy=true exceptions, (traces | where severityLevel >= 3) | where cloud_RoleName =~ "${names.func}"'
          timeAggregation: 'Count'
          operator: 'GreaterThan'
          threshold: 0
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: { actionGroups: [actionGroup.id] }
  }
}

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = if (!empty(alertEmail)) {
  name: '${prefix}-monthly-budget'
  properties: {
    category: 'Cost'
    amount: monthlyBudget
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStartDate }
    notifications: {
      actual50: { enabled: true, operator: 'GreaterThan', threshold: 50, contactEmails: [alertEmail], thresholdType: 'Actual' }
      actual90: { enabled: true, operator: 'GreaterThan', threshold: 90, contactEmails: [alertEmail], thresholdType: 'Actual' }
      forecast100: { enabled: true, operator: 'GreaterThan', threshold: 100, contactEmails: [alertEmail], thresholdType: 'Forecasted' }
    }
  }
}

// ---------------- Outputs (used by deploy.ps1) ----------------

output functionAppName string = func.name
output storageAccountName string = storage.name
output storageAccountId string = storage.id
output sqlServerFqdn string = sql.properties.fullyQualifiedDomainName
output sqlDatabaseName string = names.db
output keyVaultName string = vault.name
output appInsightsName string = insights.name
output foundryEndpoint string = foundryEndpoint
