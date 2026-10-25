<#
.SYNOPSIS
    Checks the backend, then deploys it to one environment on Fly.io.

.DESCRIPTION
    Runs from anywhere; works in memory-layer-for-life/. In order:
      1. Lint, format, types, and the test suite (the tests need the local test
         PostgreSQL running; -SkipTests skips them, for a re-deploy of tested code).
      2. With -ImportSecrets, imports deploy/<environment>.secrets.env into Fly, refusing
         a file that still holds the template's placeholders.
      3. fly deploy: Fly builds the image, runs the migrations in a temporary machine
         (alembic upgrade head), then replaces the running machine. A failed migration or
         health check stops the deploy and the old version keeps serving.
      4. A smoke test against the deployed API's readiness check (database included).
    Production asks for confirmation unless -Yes is given.

.EXAMPLE
    .\deploy\deploy.ps1 staging -ImportSecrets
.EXAMPLE
    .\deploy\deploy.ps1 production
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('staging', 'production')]
    [string]$Environment,
    [switch]$ImportSecrets,
    [switch]$SkipTests,
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

$config = "fly.$Environment.toml"
$python = '.\.venv\Scripts\python.exe'
$app = (Select-String -Path $config -Pattern '^app\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$url = "https://$app.fly.dev"

function Invoke-Step([string]$Name, [scriptblock]$Action) {
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit code $LASTEXITCODE)." }
}

if (-not (Get-Command flyctl -ErrorAction SilentlyContinue)) {
    throw 'flyctl is not installed. Install it: iwr https://fly.io/install.ps1 -useb | iex'
}

Invoke-Step 'Lint' { & $python -m ruff check . }
Invoke-Step 'Format' { & $python -m ruff format --check . }
Invoke-Step 'Types' { & $python -m mypy }
if (-not $SkipTests) {
    Invoke-Step 'Tests' { & $python -m pytest tests -q -p no:cacheprovider }
}

if ($ImportSecrets) {
    $file = "deploy\$Environment.secrets.env"
    if (-not (Test-Path $file)) {
        throw "Missing $file. Copy deploy\secrets.example.env to it and fill it in."
    }
    # Only NAME=value lines with a value; comments and empty optional keys are left out.
    $lines = Get-Content $file | Where-Object { $_ -match '^\s*[A-Z][A-Z0-9_]*=\S' }
    $placeholders = 'YOUR_PROJECT_REF|USER:PASSWORD|ep-NAME|sk-ant-\.\.\.|you@example\.com'
    $unfilled = $lines | Where-Object { $_ -match $placeholders }
    if ($unfilled) {
        $names = ($unfilled | ForEach-Object { ($_ -split '=', 2)[0] }) -join ', '
        throw "$file still has template values for: $names"
    }
    # --stage: the values apply with the deploy below, not with a restart now.
    Invoke-Step "Secrets for $app" { $lines | flyctl secrets import --config $config --stage }
}

if ($Environment -eq 'production' -and -not $Yes) {
    $answer = Read-Host "Deploy to PRODUCTION ($app)? Type the app name to continue"
    if ($answer -ne $app) { throw 'Not confirmed; nothing was deployed.' }
}

Invoke-Step "Deploy $app" { flyctl deploy --config $config --remote-only }

Write-Host '==> Smoke test' -ForegroundColor Cyan
$ready = Invoke-RestMethod -Uri "$url/api/v1/health/ready" -TimeoutSec 60
if ($ready.status -ne 'ready') { throw "The API answered but is not ready: $($ready | ConvertTo-Json -Compress)" }
Write-Host "Deployed: $url (database $($ready.database))" -ForegroundColor Green
