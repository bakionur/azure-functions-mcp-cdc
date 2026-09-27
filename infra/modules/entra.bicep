// Demo 3 · the Entra app registration that PROTECTS one MCP server (built-in MCP auth, no client secret anywhere).
// Adapted from Azure-Samples/remote-mcp-functions-python infra/app/entra.bicep.
// Note: Graph objects are not resource-group resources → `azd down` leaves this registration behind (harmless, reused
// on the next deploy via uniqueName). Deploying needs the right to register apps in the tenant.
extension microsoftGraphV1

param appUniqueName string
param appDisplayName string
param functionAppHostname string
param managedIdentityPrincipalId string
@description('Grant tenant-wide consent for Graph User.Read + Azure DevOps user_impersonation (the OBO calls) so users see no consent prompt. Needs an admin deployer; set false otherwise and consent once via /.auth/login/aad.')
param grantAdminConsent bool = true
@description('Clients allowed to get tokens for this API without a consent prompt: VS Code + Azure CLI (for smoke tests)')
param preAuthorizedClientIds array = [ 'aebc6443-996d-45c2-90f0-388ff96faa56', '04b07795-8ddb-461a-bbee-02f9e1bf7b46' ]

var scopeId = guid(appUniqueName, 'default-scope', 'user_impersonation')
var identifierUri = 'api://${appUniqueName}-${uniqueString(subscription().id, resourceGroup().id, appUniqueName)}'

resource app 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: appUniqueName
  displayName: appDisplayName
  signInAudience: 'AzureADMyOrg'
  // The MCP client (VS Code) sends RFC 8707 resource=<server URL> alongside the api:// scope; Entra rejects that
  // (AADSTS9010010) unless the server URL is ALSO an identifier URI of this app.
  identifierUris: [ identifierUri, 'https://${functionAppHostname}', 'https://${functionAppHostname}/runtime/webhooks/mcp' ]
  api: {
    requestedAccessTokenVersion: 2
    oauth2PermissionScopes: [
      {
        id: scopeId
        value: 'user_impersonation'
        type: 'User'
        isEnabled: true
        adminConsentDisplayName: 'Use the MCP server as the signed-in user'
        adminConsentDescription: 'Allow the client to call the MCP server on behalf of the signed-in user'
        userConsentDisplayName: 'Use the MCP server as you'
        userConsentDescription: 'Allow the client to call the MCP server on your behalf'
      }
    ]
    preAuthorizedApplications: [for c in preAuthorizedClientIds: { appId: c, delegatedPermissionIds: [ scopeId ] }]
  }
  web: {
    redirectUris: [ 'https://${functionAppHostname}/.auth/login/aad/callback' ]
    implicitGrantSettings: { enableAccessTokenIssuance: false, enableIdTokenIssuance: true }
  }
  requiredResourceAccess: [
    {
      resourceAppId: '00000003-0000-0000-c000-000000000000' // Microsoft Graph
      resourceAccess: [ { id: 'e1fe6dd8-ba31-4d61-89e7-88639da4683d', type: 'Scope' } ] // User.Read (for the whoami OBO call)
    }
    {
      resourceAppId: '499b84ac-1321-427f-aa17-267ca6975798' // Azure DevOps
      resourceAccess: [ { id: 'ee69721e-6c3a-468f-a9ec-302d16a4c599', type: 'Scope' } ] // user_impersonation (OBO → ADO as the user)
    }
  ]
}

resource sp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: app.appId
}

// The app proves its identity with the function app's managed identity instead of a secret.
resource fic 'Microsoft.Graph/applications/federatedIdentityCredentials@v1.0' = {
  name: '${app.uniqueName}/mcp-function-managed-identity'
  audiences: [ 'api://AzureADTokenExchange' ]
  issuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
  subject: managedIdentityPrincipalId
  description: 'Function app UAMI as client assertion for built-in auth + OBO'
}

resource graphSp 'Microsoft.Graph/servicePrincipals@v1.0' existing = {
  appId: '00000003-0000-0000-c000-000000000000'
}

resource adoSp 'Microsoft.Graph/servicePrincipals@v1.0' existing = {
  appId: '499b84ac-1321-427f-aa17-267ca6975798' // present once any ADO org is connected to the tenant
}

resource adoConsent 'Microsoft.Graph/oauth2PermissionGrants@v1.0' = if (grantAdminConsent) {
  clientId: sp.id
  resourceId: adoSp.id
  consentType: 'AllPrincipals'
  scope: 'user_impersonation'
}

resource consent 'Microsoft.Graph/oauth2PermissionGrants@v1.0' = if (grantAdminConsent) {
  clientId: sp.id
  resourceId: graphSp.id
  consentType: 'AllPrincipals'
  scope: 'User.Read'
}

output applicationId string = app.appId
output identifierUri string = identifierUri
output servicePrincipalId string = sp.id
