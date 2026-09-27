// Demo 4a · API Center = the private MCP registry. "How does anyone else FIND my tools?"
// Free SKU, no traffic flows through it. Not available in germanywestcentral → deploy to westeurope.
// kind 'mcp' is an extensible-enum value (not yet in the published enum) → Bicep warns BCP036; the RP accepts it.
param name string
param location string = 'westeurope'
@description('[{ name, title, summary, url }]')
param servers array
@description('Who may read the registry with Entra (no anonymous access): [{ id, type: User|ServicePrincipal }]')
param readers array = []

var roleDataReader = 'c7244dfb-f447-457d-b2ba-3999044d1706' // Azure API Center Data Reader

resource apic 'Microsoft.ApiCenter/services@2024-06-01-preview' = {
  name: name
  location: location
  #disable-next-line BCP187 // not in the published type, but updates fail without it ("A valid Sku is required")
  sku: { name: 'Free' }
  identity: { type: 'SystemAssigned' }
}

resource ws 'Microsoft.ApiCenter/services/workspaces@2024-06-01-preview' = {
  parent: apic
  name: 'default'
  properties: { title: 'Default workspace', description: 'CDC-Germany 2026 MCP servers' }
}

resource env 'Microsoft.ApiCenter/services/workspaces/environments@2024-06-01-preview' = {
  parent: ws
  name: 'functions-flex'
  properties: {
    title: 'Azure Functions Flex Consumption'
    kind: 'production'
    server: { type: 'Azure compute service' }
  }
}

#disable-next-line BCP036
resource api 'Microsoft.ApiCenter/services/workspaces/apis@2024-06-01-preview' = [for s in servers: {
  parent: ws
  name: s.name
  properties: { title: s.title, kind: 'mcp', summary: s.summary, description: s.summary }
}]

resource ver 'Microsoft.ApiCenter/services/workspaces/apis/versions@2024-06-01-preview' = [for (s, i) in servers: {
  parent: api[i]
  name: '1-1-0'
  properties: { title: '1.1.0', lifecycleStage: 'production' }
}]

resource def 'Microsoft.ApiCenter/services/workspaces/apis/versions/definitions@2024-06-01-preview' = [for (s, i) in servers: {
  parent: ver[i]
  name: 'default'
  properties: { title: 'default', description: s.summary }
}]

resource dep 'Microsoft.ApiCenter/services/workspaces/apis/deployments@2024-06-01-preview' = [for (s, i) in servers: {
  parent: api[i]
  name: 'flex'
  properties: {
    title: 'Azure Functions (Flex)'
    environmentId: '/workspaces/default/environments/${env.name}'
    definitionId: '/workspaces/default/apis/${s.name}/versions/${ver[i].name}/definitions/${def[i].name}'
    state: 'active'
    server: { runtimeUri: [ s.url ] }
  }
}]

resource readerRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in readers: {
  name: guid(apic.id, r.id, roleDataReader)
  scope: apic
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDataReader)
    principalId: r.id
    principalType: r.type
  }
}]

output name string = apic.name
output portalUrl string = 'https://${apic.name}.portal.${location}.azure-apicenter.ms'
output registryUrl string = 'https://${apic.name}.data.${location}.azure-apicenter.ms/workspaces/default/v0.1/servers'
