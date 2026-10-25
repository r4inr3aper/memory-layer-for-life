<#
.SYNOPSIS
    Checks the backend, builds its image, pushes it to a registry, and has Render deploy
    it (the free deployment in docs/DEPLOYMENT.md).

.DESCRIPTION
    Runs from anywhere; works in memory-layer-for-life/. Needs Docker; not Python: every
    package is installed inside the image, from uv.lock. In order:
      1. Lint, format, types, and the test suite, using the local Python environment
         (.venv). -SkipTests skips the tests (they need the local test PostgreSQL);
         -SkipChecks skips all of it, on a computer without that environment, for code
         already checked elsewhere.
      2. Builds the image for linux/amd64 and pushes it as :latest and as a dated tag.
         Run `docker login` once first.
      3. With a deploy hook (-DeployHook, or the RENDER_DEPLOY_HOOK environment
         variable), tells Render to deploy the dated tag.
      4. With -HealthUrl, waits until the API answers ready (database included).

.EXAMPLE
    .\deploy\push-image.ps1 -Image docker.io/yourname/muse-api
.EXAMPLE
    .\deploy\push-image.ps1 -Image docker.io/yourname/muse-api -SkipChecks
.EXAMPLE
    $env:RENDER_DEPLOY_HOOK = 'https://api.render.com/deploy/srv-...?key=...'
    .\deploy\push-image.ps1 -Image docker.io/yourname/muse-api -HealthUrl https://muse-api.onrender.com
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Image,
    [string]$DeployHook = $env:RENDER_DEPLOY_HOOK,
    [string]$HealthUrl,
    [switch]$SkipTests,
    [switch]$SkipChecks
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

$python = '.\.venv\Scripts\python.exe'
$tag = Get-Date -Format 'yyyyMMdd-HHmm'

function Invoke-Step([string]$Name, [scriptblock]$Action) {
    Write-Host "==> $Name" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit code $LASTEXITCODE)." }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is not installed or not on PATH. Install Docker Desktop and start it.'
}

if ($SkipChecks) {
    Write-Host '==> Skipping lint, types, and tests (-SkipChecks)' -ForegroundColor Yellow
} else {
    if (-not (Test-Path $python)) {
        throw "No Python environment at $python. Create it (docs/DEPLOYMENT.md, 'Recreating the Python environment'), or pass -SkipChecks for code already checked."
    }
    Invoke-Step 'Lint' { & $python -m ruff check . }
    Invoke-Step 'Format' { & $python -m ruff format --check . }
    Invoke-Step 'Types' { & $python -m mypy }
    if (-not $SkipTests) {
        Invoke-Step 'Tests' { & $python -m pytest tests -q -p no:cacheprovider }
    }
}

Invoke-Step "Build $Image`:$tag" {
    docker build --platform linux/amd64 -t "$Image`:$tag" -t "$Image`:latest" .
}
Invoke-Step 'Push' { docker push "$Image`:$tag" }
Invoke-Step 'Push latest' { docker push "$Image`:latest" }

if ($DeployHook) {
    Write-Host '==> Deploy on Render' -ForegroundColor Cyan
    $separator = if ($DeployHook.Contains('?')) { '&' } else { '?' }
    $hook = $DeployHook + $separator + 'imgURL=' + [uri]::EscapeDataString("$Image`:$tag")
    Invoke-RestMethod -Method Post -Uri $hook | Out-Null
    Write-Host "Render is deploying $Image`:$tag" -ForegroundColor Green
} else {
    Write-Host "Pushed $Image`:$tag. In Render: Manual Deploy > Deploy latest reference." -ForegroundColor Yellow
}

if ($HealthUrl) {
    Write-Host '==> Waiting for the API' -ForegroundColor Cyan
    $deadline = (Get-Date).AddMinutes(8)
    do {
        Start-Sleep -Seconds 15
        try {
            $ready = Invoke-RestMethod -Uri "$($HealthUrl.TrimEnd('/'))/api/v1/health/ready" -TimeoutSec 30
            if ($ready.status -eq 'ready') {
                Write-Host "Live: $HealthUrl (database $($ready.database))" -ForegroundColor Green
                return
            }
        } catch { }
    } while ((Get-Date) -lt $deadline)
    throw "The API did not answer ready within 8 minutes. Check the service's logs in Render."
}
