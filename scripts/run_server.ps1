# Start everything needed for the website, using the project's venv Python.
#   .\scripts\run_server.ps1
#
# No need to activate the venv first: this calls venv\Scripts\python.exe directly,
# so the computer-wide Python (which lacks the project's packages) is never used.

$project = Split-Path -Parent $PSScriptRoot
$python  = Join-Path $project "venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "venv not found. Create it first (see README.md, Setup)."
    exit 1
}

& (Join-Path $PSScriptRoot "start_postgres.ps1")
if ($LASTEXITCODE -ne 0) { exit 1 }

Set-Location $project
& $python manage.py runserver
