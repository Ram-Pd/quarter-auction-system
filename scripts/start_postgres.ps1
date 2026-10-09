# Start the portable PostgreSQL server used by this project.
#   .\scripts\start_postgres.ps1
#
# PostgreSQL is installed (unzipped) in %USERPROFILE%\pgsql with its data in
# %USERPROFILE%\pgsql-data. It is NOT a Windows service, so run this after
# every reboot. Override the folders with $env:PGSQL_HOME / $env:PGSQL_DATA.

$pgHome = if ($env:PGSQL_HOME) { $env:PGSQL_HOME } else { "$env:USERPROFILE\pgsql" }
$pgData = if ($env:PGSQL_DATA) { $env:PGSQL_DATA } else { "$env:USERPROFILE\pgsql-data" }
$pgCtl  = "$pgHome\bin\pg_ctl.exe"

& $pgCtl -D $pgData status *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "PostgreSQL is already running."
    exit 0
}

# Started in its own hidden window so it keeps running after this window closes.
Start-Process -FilePath $pgCtl -ArgumentList "-D", "`"$pgData`"", "-l", "`"$pgData\server.log`"", "start" -WindowStyle Hidden

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    & "$pgHome\bin\pg_isready.exe" -h localhost -q
    if ($LASTEXITCODE -eq 0) {
        Write-Host "PostgreSQL is running on localhost:5432."
        exit 0
    }
}
Write-Host "PostgreSQL did not become ready. Check the log: $pgData\server.log"
exit 1
