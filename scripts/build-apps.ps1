# Builds the two MCP App widgets into single-file index.html (runs as azd preprovision hook).
$ErrorActionPreference = 'Stop'
foreach ($s in 'skywatch','domainforge') {
  Push-Location "$PSScriptRoot/../servers/$s/app"
  try {
    if (-not (Test-Path node_modules)) { npm ci --no-audit --no-fund | Out-Null; if ($LASTEXITCODE) { throw "npm ci failed for $s" } }
    npm run build | Out-Null; if ($LASTEXITCODE) { throw "widget build failed for $s" }
    Write-Host "built $s widget -> servers/$s/app/dist/index.html"
  } finally { Pop-Location }
}
