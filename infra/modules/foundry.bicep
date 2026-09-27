// Demo 4b · Azure AI Foundry project + model. The agent itself (with the MCP tools) is created by
// scripts/foundry_agent.py AFTER deploy, because the Functions mcp_extension key only exists once the apps are running.
param name string
param location string
param projectName string = 'cdc-mcp'
param modelName string = 'gpt-5.4-mini'   // gpt-4.1(-mini) is Deprecated: new subscriptions can't deploy it
param modelVersion string = '2026-03-17'
param modelCapacity int = 50
@description('Object id of the person running azd (AZURE_PRINCIPAL_ID) — gets Foundry User to create/run agents')
param userPrincipalId string = ''

var roleFoundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'   // "Foundry User" (formerly Azure AI User)

resource foundry 'Microsoft.CognitiveServices/accounts@2026-07-01' = {
  name: name
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: name
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-07-01' = {
  parent: foundry
  name: projectName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: { displayName: 'CDC-Germany 2026 · MCP on Functions', description: 'Agents that use the Functions MCP servers' }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2026-07-01' = {
  parent: foundry
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: { model: { format: 'OpenAI', name: modelName, version: modelVersion } }
  dependsOn: [ project ] // one operation at a time on the account (else RequestConflict / InternalServerError)
}

resource userRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  scope: foundry
  name: guid(foundry.id, userPrincipalId, roleFoundryUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleFoundryUser)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

resource projectRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, project.id, roleFoundryUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleFoundryUser)
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output projectEndpoint string = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output projectId string = project.id
output projectPrincipalId string = project.identity.principalId
output modelName string = model.name
