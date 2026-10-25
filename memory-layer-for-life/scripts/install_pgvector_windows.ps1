# Builds pgvector from its official source and installs it into the portable PostgreSQL
# used for the tests (RUN_LOCALLY.md). Neon already has pgvector; this is for local only.
#
# Needs the "Desktop development with C++" workload of Visual Studio Build Tools, and git.
# Run in a normal PowerShell from the project folder:
#     powershell -ExecutionPolicy Bypass -File scripts\install_pgvector_windows.ps1
# Then restart PostgreSQL (pg_ctl restart), so it loads the new library.

param(
    [string]$PgRoot = "$env:LOCALAPPDATA\second-brain-postgres\pgsql",
    [string]$Version = "v0.8.7"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path "$PgRoot\bin\pg_config.exe")) {
    throw "No PostgreSQL found at $PgRoot. Pass -PgRoot with the folder that holds bin\pg_config.exe."
}

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsPath) {
    throw "Visual Studio C++ build tools (x64) not found. Install the 'Desktop development with C++' workload."
}
$vcvars = Join-Path $vsPath "VC\Auxiliary\Build\vcvars64.bat"

$work = Join-Path $env:TEMP "pgvector-build"
if (Test-Path $work) { Remove-Item -Recurse -Force $work }
git clone --depth 1 --branch $Version https://github.com/pgvector/pgvector.git $work

# nmake needs the compiler environment, which vcvars64.bat sets up in cmd.
$build = "call `"$vcvars`" && cd /d `"$work`" && set `"PGROOT=$PgRoot`" && nmake /NOLOGO /F Makefile.win && nmake /NOLOGO /F Makefile.win install"
cmd /c $build
if ($LASTEXITCODE -ne 0) { throw "Building pgvector failed (exit code $LASTEXITCODE)." }

Write-Host "pgvector $Version installed into $PgRoot. Restart PostgreSQL to load it:"
Write-Host "    & `"$PgRoot\bin\pg_ctl.exe`" restart -D `"$env:LOCALAPPDATA\second-brain-postgres\data`""
