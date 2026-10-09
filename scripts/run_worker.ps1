# Start the background worker (closes finished auctions, sends winner emails),
# using the project's venv Python. Run it in a second terminal.
#   .\scripts\run_worker.ps1

$project = Split-Path -Parent $PSScriptRoot
$python  = Join-Path $project "venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "venv not found. Create it first (see README.md, Setup)."
    exit 1
}

& (Join-Path $PSScriptRoot "start_postgres.ps1")
if ($LASTEXITCODE -ne 0) { exit 1 }

Set-Location $project
& $python manage.py run_auction_worker
