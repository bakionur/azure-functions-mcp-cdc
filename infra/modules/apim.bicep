// Optional (enableApim=true) · API Management as the MCP GATEWAY in front of skywatch.
// The client (Foundry agent) only holds an APIM subscription key; APIM injects the Functions key and rate-limits.
// Basic v2 provisions in minutes (classic Developer: 30–45 min). Prompts are not proxied; MCP App widgets may not be
// → use it for the Foundry path, keep VS Code on the direct URL.
param name string
param location string
param publisherEmail string
param functionAppName string
param rateLimitCalls int = 5
param rateLimitPeriod int = 30

resource func 'Microsoft.Web/sites@2024-04-01' existing = { name: functionAppName }

resource apim 'Microsoft.ApiManagement/service@2025-09-01-preview' = {
  name: name
  location: location
  sku: { name: 'BasicV2', capacity: 1 }
  properties: { publisherEmail: publisherEmail, publisherName: 'CDC-Germany 2026 demo' }
}

resource fnKey 'Microsoft.ApiManagement/service/namedValues@2025-09-01-preview' = {
  parent: apim
  name: 'skywatch-mcp-key'
  properties: {
    displayName: 'skywatch-mcp-key'
    secret: true
    value: listKeys('${func.id}/host/default', '2024-04-01').systemKeys.mcp_extension
  }
}

resource mcp 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = {
  parent: apim
  name: 'skywatch-mcp'
  properties: {
    type: 'mcp'
    displayName: 'SkyWatch MCP (via gateway)'
    path: 'skywatch'
    protocols: [ 'https' ]
    serviceUrl: 'https://${func.properties.defaultHostName}/runtime/webhooks'
    subscriptionRequired: true
    mcpProperties: {
      transportType: 'streamable'
      endpoints: [ { name: 'message', uriTemplate: '/mcp' } ]
    }
  }
}

resource policy 'Microsoft.ApiManagement/service/apis/policies@2025-09-01-preview' = {
  parent: mcp
  name: 'policy'
  dependsOn: [ fnKey ]
  properties: {
    format: 'rawxml'
    value: '<policies><inbound><base /><rate-limit-by-key calls="${rateLimitCalls}" renewal-period="${rateLimitPeriod}" counter-key="@(context.Subscription?.Id ?? context.Request.IpAddress)" remaining-calls-header-name="x-ratelimit-remaining" /><set-header name="x-functions-key" exists-action="override"><value>{{skywatch-mcp-key}}</value></set-header><set-header name="Ocp-Apim-Subscription-Key" exists-action="delete" /></inbound><backend><forward-request /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>'
  }
}

resource sub 'Microsoft.ApiManagement/service/subscriptions@2025-09-01-preview' = {
  parent: apim
  name: 'foundry-agent'
  properties: { displayName: 'Foundry agent', scope: mcp.id, state: 'active' }
}

output gatewayUrl string = '${apim.properties.gatewayUrl}/skywatch/mcp'
output subscriptionId string = sub.id
