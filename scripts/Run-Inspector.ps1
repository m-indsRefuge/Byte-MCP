[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "Connect MCP Inspector to http://127.0.0.1:8000/mcp"
npx -y @modelcontextprotocol/inspector
