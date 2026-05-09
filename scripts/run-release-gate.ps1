$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$orchestratorDir = Join-Path $repoRoot "services\office-orchestrator"
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (!(Test-Path $pythonExe)) {
    throw "Python environment not found at $pythonExe"
}

Set-Location $orchestratorDir

& $pythonExe -m pytest tests/test_routing_and_dispatch.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $pythonExe -m pytest tests/test_security_and_observability.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $pythonExe -m pytest tests/test_http_endpoints_live.py -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $pythonExe -m pytest tests/test_local_process_smoke.py -v
exit $LASTEXITCODE
