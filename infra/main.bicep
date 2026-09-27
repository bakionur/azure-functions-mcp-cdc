// CDC-Germany 2026 · "Azure Functions as MCP Servers"
// One resource group. FOUR remote MCP servers, each its own Flex Consumption app (one MCP endpoint per app):
//   concierge   — self-hosted: the official MCP SDK server from local/, unchanged (Demo 1)
//   skywatch    — MCP extension + MCP App radar                                       (Demo 2)
//   domainforge — MCP extension + MCP App picker + blob output binding                (Demo 2, Demo 4 via Foundry)
//   ado         — MCP extension, protected by built-in Entra auth + on-behalf-of       (Demo 3)
// Plus: API Center (registry, Demo 4), Foundry project + model (Demo 4), optional APIM gateway.
targetScope = 'resourceGroup'

@description('azd environment name (used for naming)')
param environmentName string
param location string = resourceGroup().location
@description('Object id of the person running azd (azd fills AZURE_PRINCIPAL_ID)')
param principalId string = ''

// --- Azure DevOps: no PAT. The ado server calls ADO on behalf of the signed-in Entra user (org must be connected to this tenant).
param adoOrgUrl string = ''
param adoProject string = ''
param adoTeam string = ''

// --- SkyWatch defaults: Congress Park Hanau ---
param homeLat string = '50.1329'
param homeLon string = '8.9169'

// --- feature switches ---
@description('Protect the ado server with built-in Entra auth (needs the right to register apps in the tenant)')
param enableEntraAuth bool = true
param enableApiCenter bool = true
param apiCenterLocation string = 'westeurope' // API Center is not offered in germanywestcentral
param enableFoundry bool = true
param foundryLocation string = location
param foundryModel string = 'gpt-5.4-mini'
param foundryModelVersion string = '2026-03-17'
@description('Optional APIM (Basic v2) gateway in front of skywatch for the Foundry path (~€5/day while it exists)')
param enableApim bool = false
param apimPublisherEmail string = 'demo@example.com'

var suffix = toLower(take(uniqueString(subscription().id, resourceGroup().id, environmentName), 8))
var servers = [
  'concierge'
  'ado'
  'skywatch'
  'domainforge'
]
var appName = { concierge: 'func-concierge-${suffix}', ado: 'func-ado-${suffix}', skywatch: 'func-skywatch-${suffix}', domainforge: 'func-domainforge-${suffix}' }

// Built-in role IDs
var roleBlobOwner = 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
var roleQueueContrib = '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
var roleTableContrib = '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
var roleMetricsPublisher = '3913510d-42f4-4e42-8a64-420c390055eb'

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-mcp-${suffix}'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-mcp-${suffix}'
  location: location
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-mcp-${suffix}'
  location: location
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'stmcp${suffix}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
  }
}

resource blobSvc 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

// one deployment container per server + one for DomainForge "reservations"
resource pkgContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for s in servers: {
  parent: blobSvc
  name: 'app-package-${s}'
}]

resource reservations 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobSvc
  name: 'reservations'
}

resource roles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in [roleBlobOwner, roleQueueContrib, roleTableContrib]: {
  name: guid(storage.id, identity.id, r)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}]

// the deploying user can open the reservations container in the portal
resource userBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(storage.id, principalId, roleBlobOwner)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleBlobOwner)
    principalId: principalId
    principalType: 'User'
  }
}

resource appiRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(appi.id, identity.id, roleMetricsPublisher)
  scope: appi
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleMetricsPublisher)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ------------------------------------------------------------------ Entra app registration for the ado server
module entra 'modules/entra.bicep' = if (enableEntraAuth) {
  name: 'entra-ado'
  params: {
    appUniqueName: '${appName.ado}-app'
    appDisplayName: 'MCP server · adopilot (${appName.ado})'
    functionAppHostname: '${appName.ado}.azurewebsites.net' // predicted → no cycle with the app
    managedIdentityPrincipalId: identity.properties.principalId
  }
}

var entraAppId = enableEntraAuth ? entra!.outputs.applicationId : ''
var entraIdentifierUri = enableEntraAuth ? entra!.outputs.identifierUri : ''

// ------------------------------------------------------------------ the four function apps
// Flex plans/apps created in parallel in one RG fail with InternalServerError/conflict → one at a time
@batchSize(1)
resource plans 'Microsoft.Web/serverfarms@2024-04-01' = [for s in servers: {
  name: 'plan-${s}-${suffix}'
  location: location
  kind: 'functionapp'
  sku: { tier: 'FlexConsumption', name: 'FC1' }
  properties: { reserved: true }
}]

var commonSettings = [
  { name: 'AzureWebJobsStorage__accountName', value: storage.name }
  { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
  { name: 'AzureWebJobsStorage__clientId', value: identity.properties.clientId }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appi.properties.ConnectionString }
  { name: 'APPLICATIONINSIGHTS_AUTHENTICATION_STRING', value: 'ClientId=${identity.properties.clientId};Authorization=AAD' }
]

var adoAuthSettings = enableEntraAuth ? [
  { name: 'WEBSITE_AUTH_PRM_DEFAULT_WITH_SCOPES', value: '${entraIdentifierUri}/user_impersonation' }
  { name: 'OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID', value: identity.properties.clientId }
  { name: 'WEBSITE_AUTH_AAD_ALLOWED_TENANTS', value: tenant().tenantId }
  // Entra is the only gate on this app: turn the mcp_extension key requirement off (docs: "Anonymous … when using OAuth")
  { name: 'AzureFunctionsJobHost__extensions__mcp__system__webhookAuthorizationLevel', value: 'Anonymous' }
] : []

var perServerSettings = {
  concierge: [
    // self-hosted MCP (preview): the Functions host launches `python server.py` and proxies /mcp to it
    { name: 'AzureWebJobsFeatureFlags', value: 'EnableMcpCustomHandlerPreview' }
    { name: 'PYTHONPATH', value: '/home/site/wwwroot/.python_packages/lib/site-packages' }
  ]
  ado: concat([
    { name: 'ADO_ORG_URL', value: adoOrgUrl }
    { name: 'ADO_PROJECT', value: adoProject }
    { name: 'ADO_TEAM', value: adoTeam }
  ], adoAuthSettings)
  skywatch: [
    { name: 'HOME_LAT', value: homeLat }
    { name: 'HOME_LON', value: homeLon }
    { name: 'HOME_NAME', value: 'Congress Park Hanau' }
  ]
  domainforge: [
    { name: 'RESERVATIONS_CONTAINER', value: reservations.name }
  ]
}

@batchSize(1)
resource apps 'Microsoft.Web/sites@2024-04-01' = [for (s, i) in servers: {
  name: appName[s]
  location: location
  kind: 'functionapp,linux'
  tags: { 'azd-service-name': s }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    serverFarmId: plans[i].id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}app-package-${s}'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: identity.id
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
        // one warm instance per app = no cold start during demos. Remove alwaysReady afterwards to pay ~0.
        // ❓ MCP-extension triggers may not belong to the 'http' group — check Scale and concurrency in the portal.
        alwaysReady: [ { name: 'http', instanceCount: 1 } ]
      }
      runtime: { name: 'python', version: '3.13' }
    }
    siteConfig: {
      appSettings: concat(commonSettings, perServerSettings[s])
    }
  }
  dependsOn: [ roles, pkgContainers ]
}]

// built-in auth (EasyAuth) on ado: 401 → protected-resource metadata → Entra sign-in in VS Code
resource adoAuth 'Microsoft.Web/sites/config@2024-04-01' = if (enableEntraAuth) {
  parent: apps[1]
  name: 'authsettingsV2'
  properties: {
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'Return401'
      redirectToProvider: 'azureactivedirectory'
    }
    httpSettings: {
      requireHttps: true
      routes: { apiPrefix: '/.auth' }
      forwardProxy: { convention: 'NoProxy' }
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
          clientId: entraAppId
          clientSecretSettingName: 'OVERRIDE_USE_MI_FIC_ASSERTION_CLIENTID' // managed identity instead of a secret (a setting NAME, not a value) pragma: allowlist secret
        }
        login: { loginParameters: [ 'scope=openid profile email User.Read' ] }
        validation: {
          jwtClaimChecks: {}
          allowedAudiences: [ entraIdentifierUri ]
          defaultAuthorizationPolicy: {
            allowedPrincipals: {}
            allowedApplications: [ entraAppId, 'aebc6443-996d-45c2-90f0-388ff96faa56', '04b07795-8ddb-461a-bbee-02f9e1bf7b46' ] // itself + VS Code + Azure CLI (smoke)
          }
        }
        isAutoProvisioned: false
      }
    }
    login: {
      routes: { logoutEndpoint: '/.auth/logout' }
      tokenStore: { enabled: true, tokenRefreshExtensionHours: 72 }
      preserveUrlFragmentsForLogins: false
      cookieExpiration: { convention: 'FixedTime', timeToExpiration: '08:00:00' }
      nonce: { validateNonce: true, nonceExpirationInterval: '00:05:00' }
    }
    platform: { enabled: true, runtimeVersion: '~1' }
  }
}

var mcpUrl = {
  concierge: 'https://${apps[0].properties.defaultHostName}/mcp'
  ado: 'https://${apps[1].properties.defaultHostName}/runtime/webhooks/mcp'
  skywatch: 'https://${apps[2].properties.defaultHostName}/runtime/webhooks/mcp'
  domainforge: 'https://${apps[3].properties.defaultHostName}/runtime/webhooks/mcp'
}

// ------------------------------------------------------------------ Demo 4: registry, agent platform, gateway
module apic 'modules/apicenter.bicep' = if (enableApiCenter) {
  name: 'apicenter'
  params: {
    name: 'apic-mcp-${suffix}'
    location: apiCenterLocation
    // Entra-only registry: the deploying user + the Foundry project identity (private tool catalog) — no anonymous access
    readers: concat(empty(principalId) ? [] : [ { id: principalId, type: 'User' } ],
                    enableFoundry ? [ { id: foundry!.outputs.projectPrincipalId, type: 'ServicePrincipal' } ] : [])
    servers: [
      { name: 'cdc-concierge', title: 'CDC Concierge (self-hosted SDK server)', summary: 'Session status, coffee, applause. The same FastMCP/MCPServer file that runs on a laptop.', url: mcpUrl.concierge }
      { name: 'adopilot', title: 'AdoPilot (Entra-protected)', summary: 'Azure DevOps board, bugs, pipelines, create_bug, /standup. Sign in with Entra ID.', url: mcpUrl.ado }
      { name: 'skywatch', title: 'SkyWatch', summary: 'Live aircraft over Hanau with an MCP App radar; PNG fallback.', url: mcpUrl.skywatch }
      { name: 'domainforge', title: 'DomainForge', summary: 'Pun domain names, live RDAP/DNS availability, MCP App picker, reserve to blob.', url: mcpUrl.domainforge }
    ]
  }
}

module apicClient 'modules/apicenter-client.bicep' = if (enableApiCenter && enableEntraAuth) {
  name: 'apicenter-client'
  params: {
    appUniqueName: 'apic-mcp-${suffix}-reader'
    appDisplayName: 'API Center MCP registry reader (apic-mcp-${suffix})'
    portalUrl: apic!.outputs.portalUrl
  }
}

module foundry 'modules/foundry.bicep' = if (enableFoundry) {
  name: 'foundry'
  params: {
    name: 'aif-mcp-${suffix}'
    location: foundryLocation
    modelName: foundryModel
    modelVersion: foundryModelVersion
    userPrincipalId: principalId
  }
}

module apim 'modules/apim.bicep' = if (enableApim) {
  name: 'apim'
  params: {
    name: 'apim-mcp-${suffix}'
    location: location
    publisherEmail: empty(apimPublisherEmail) ? 'demo@example.com' : apimPublisherEmail
    functionAppName: apps[2].name
  }
}

// ------------------------------------------------------------------ outputs → azd env (read by scripts/*)
output RESOURCE_GROUP string = resourceGroup().name
output MCP_CONCIERGE_URL string = mcpUrl.concierge
output MCP_ADO_URL string = mcpUrl.ado
output MCP_SKYWATCH_URL string = mcpUrl.skywatch
output MCP_DOMAINFORGE_URL string = mcpUrl.domainforge
output APP_CONCIERGE string = apps[0].name
output APP_ADO string = apps[1].name
output APP_SKYWATCH string = apps[2].name
output APP_DOMAINFORGE string = apps[3].name
output APPINSIGHTS_NAME string = appi.name
output STORAGE_ACCOUNT string = storage.name
output ADO_AUTH_MODE string = enableEntraAuth ? 'entra' : 'key'
output ENTRA_APP_ID string = entraAppId
output APIC_NAME string = enableApiCenter ? apic!.outputs.name : ''
output APIC_PORTAL_URL string = enableApiCenter ? apic!.outputs.portalUrl : ''
output APIC_REGISTRY_URL string = enableApiCenter ? apic!.outputs.registryUrl : ''
output APIC_CLIENT_ID string = (enableApiCenter && enableEntraAuth) ? apicClient!.outputs.clientId : ''
output AZURE_TENANT_ID string = tenant().tenantId
output FOUNDRY_PROJECT_ENDPOINT string = enableFoundry ? foundry!.outputs.projectEndpoint : ''
output FOUNDRY_PROJECT_ID string = enableFoundry ? foundry!.outputs.projectId : ''
output FOUNDRY_MODEL string = enableFoundry ? foundry!.outputs.modelName : ''
output APIM_GATEWAY_URL string = enableApim ? apim!.outputs.gatewayUrl : ''
output APIM_SUBSCRIPTION_ID string = enableApim ? apim!.outputs.subscriptionId : ''
