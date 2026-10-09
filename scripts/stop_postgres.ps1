# Stop the portable PostgreSQL server cleanly.
#   .\scripts\stop_postgres.ps1

$pgHome = if ($env:PGSQL_HOME) { $env:PGSQL_HOME } else { "$env:USERPROFILE\pgsql" }
$pgData = if ($env:PGSQL_DATA) { $env:PGSQL_DATA } else { "$env:USERPROFILE\pgsql-data" }

& "$pgHome\bin\pg_ctl.exe" -D $pgData stop -m fast
