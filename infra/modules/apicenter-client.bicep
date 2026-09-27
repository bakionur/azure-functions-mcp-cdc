// Demo 4 · Entra app registration for reading the API Center MCP registry — no anonymous access.
// Used by (1) the API Center portal: Settings → Identity provider → Manual → this client id, and
// (2) scripts/registry.py (interactive sign-in, public client). The Azure CLI can't get API Center data-plane tokens
// (AADSTS65002: first-party pre-authorization), hence our own client.
extension microsoftGraphV1

param appUniqueName string
param appDisplayName string
param portalUrl string
param grantAdminConsent bool = true

var centerServicePrincipalAppId = 'c3ca1a77-7a87-4dba-b8f8-eea115ae4573' // "Azure API Center" (data plane)
var centerUserImpersonationScope = '44327351-3395-414e-882e-7aa4a9c3b25d'

resource app 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: appUniqueName
  displayName: appDisplayName
  signInAudience: 'AzureADMyOrg'
  isFallbackPublicClient: true
  spa: { redirectUris: [ portalUrl ] }
  publicClient: { redirectUris: [ 'http://localhost' ] }
  requiredResourceAccess: [
    {
      resourceAppId: centerServicePrincipalAppId
      resourceAccess: [ { id: centerUserImpersonationScope, type: 'Scope' } ]
    }
  ]
}

resource sp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: app.appId
}

resource apicSp 'Microsoft.Graph/servicePrincipals@v1.0' existing = {
  appId: centerServicePrincipalAppId
}

resource consent 'Microsoft.Graph/oauth2PermissionGrants@v1.0' = if (grantAdminConsent) {
  clientId: sp.id
  resourceId: apicSp.id
  consentType: 'AllPrincipals'
  scope: 'user_impersonation'
}

output clientId string = app.appId
