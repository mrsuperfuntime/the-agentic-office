param(
    [ValidateSet("finance", "sales", "hr", "customer-service", "procurement", "manufacturing", "social-media", "it")]
    [string]$Office = "finance",
    [int]$OrchestratorPort = 8000,
    [int]$OfficePort = 8005,
    [string]$ApiKey = "agentic-office-dev-key",
    [string]$DatabasePath = "",
    [string]$OllamaUrl = "http://127.0.0.1:11434",
    [string]$OllamaModel = "mistral"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (!(Test-Path $pythonExe)) {
    throw "Python environment not found at $pythonExe"
}

if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
    $DatabasePath = Join-Path $repoRoot "services\office-orchestrator\orchestrator_local.db"
}

$officeServiceMap = @{
    "finance" = "finance-office"
    "sales" = "sales-office"
    "hr" = "hr-office"
    "customer-service" = "customer-service-office"
    "procurement" = "procurement-office"
    "manufacturing" = "manufacturing-office"
    "social-media" = "social-media-office"
    "it" = "it-office"
}

$officeServiceFolder = $officeServiceMap[$Office]
$officeDir = Join-Path $repoRoot ("services\" + $officeServiceFolder)
$orchestratorDir = Join-Path $repoRoot "services\office-orchestrator"

$officeEnvKey = "OFFICE_URL_" + ($Office.ToUpper().Replace("-", "_"))
$officeUrl = "http://127.0.0.1:$OfficePort"

$allOfficeEnvKeys = @(
    "OFFICE_URL_SALES",
    "OFFICE_URL_HR",
    "OFFICE_URL_CUSTOMER_SERVICE",
    "OFFICE_URL_PROCUREMENT",
    "OFFICE_URL_FINANCE",
    "OFFICE_URL_MANUFACTURING",
    "OFFICE_URL_SOCIAL_MEDIA",
    "OFFICE_URL_IT"
)

$officeCommand = @(
    "$env:PYTHONPATH='$repoRoot'",
    "$env:LLM_STRICT_LOCAL='true'",
    "$env:LLM_PRIMARY_PROVIDER='ollama'",
    "$env:LLM_FALLBACK_PROVIDER='groq'",
    "$env:LLM_ENABLE_FALLBACK='false'",
    "$env:OLLAMA_URL='$OllamaUrl'",
    "$env:OLLAMA_MODEL='$OllamaModel'",
    "Set-Location '$officeDir'",
    "& '$pythonExe' -m uvicorn main:app --host 127.0.0.1 --port $OfficePort"
) -join "; "

$orchestratorCommand = @(
    "$env:ORCHESTRATOR_API_KEY='$ApiKey'",
    "$env:DATABASE_URL='sqlite:///$($DatabasePath -replace '\\','/')'",
    "$env:LLM_STRICT_LOCAL='true'",
    "$env:LLM_PRIMARY_PROVIDER='ollama'",
    "$env:LLM_FALLBACK_PROVIDER='groq'",
    "$env:LLM_ENABLE_FALLBACK='false'",
    "$env:OLLAMA_URL='$OllamaUrl'",
    "$env:OLLAMA_MODEL='$OllamaModel'",
    ($allOfficeEnvKeys | ForEach-Object { "Set-Item -Path 'Env:$_' -Value '$officeUrl'" }) -join "; ",
    "Set-Item -Path 'Env:$officeEnvKey' -Value '$officeUrl'",
    "Set-Location '$orchestratorDir'",
    "& '$pythonExe' -m uvicorn main:app --host 127.0.0.1 --port $OrchestratorPort"
) -join "; "

Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", $officeCommand | Out-Null
Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-Command", $orchestratorCommand | Out-Null

Write-Host "Started local stack:"
Write-Host "- Office: $Office on $officeUrl"
Write-Host "- Orchestrator: http://127.0.0.1:$OrchestratorPort"
Write-Host "- API key: $ApiKey"
Write-Host "- DB: $DatabasePath"
Write-Host "- LLM profile: strict-local (ollama, fallback disabled)"
Write-Host "- OLLAMA_URL: $OllamaUrl"
Write-Host "- OLLAMA_MODEL: $OllamaModel"
Write-Host ""
Write-Host "Quick checks:"
Write-Host "Invoke-RestMethod -Uri http://127.0.0.1:$OrchestratorPort/health"
Write-Host "Invoke-RestMethod -Uri http://127.0.0.1:$OrchestratorPort/stats -Headers @{ 'X-API-Key' = '$ApiKey' }"
