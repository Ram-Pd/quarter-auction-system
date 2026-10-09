# Turn on real email sending (Gmail) and send a test email.
#   .\scripts\setup_email.ps1
#
# You need a Gmail App Password first (NOT your normal Gmail password):
#   1. https://myaccount.google.com/security      -> turn on 2-Step Verification
#   2. https://myaccount.google.com/apppasswords  -> create one, copy the 16 characters
# The password is typed hidden and saved only in .env (which git never commits).

$project = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $project ".env"
$python  = Join-Path $project "venv\Scripts\python.exe"

$lines = [IO.File]::ReadAllLines($envFile)
$userLine = $lines | Where-Object { $_ -match '^EMAIL_HOST_USER=' } | Select-Object -First 1
$gmail = if ($userLine) { $userLine.Split('=', 2)[1] } else { "" }
if (-not $gmail) {
    $gmail = Read-Host "Your Gmail address"
}
Write-Host "Sending from: $gmail"

$secure = Read-Host "Paste your 16-character Gmail App Password (hidden)" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)) -replace '\s', ''
if ($plain.Length -ne 16) {
    Write-Host "That is $($plain.Length) characters; a Gmail App Password has 16. Nothing was changed."
    exit 1
}

# Replace (or add) the email lines in .env, keeping everything else unchanged.
$wanted = [ordered]@{
    "EMAIL_HOST" = "smtp.gmail.com"; "EMAIL_PORT" = "587"; "EMAIL_USE_TLS" = "True"
    "EMAIL_HOST_USER" = $gmail; "DEFAULT_FROM_EMAIL" = $gmail; "EMAIL_HOST_PASSWORD" = $plain
}
$out = New-Object System.Collections.Generic.List[string]
$done = @{}
foreach ($line in $lines) {
    $key = ($line -split '=', 2)[0]
    if ($wanted.Contains($key)) {
        if (-not $done[$key]) { $out.Add("$key=$($wanted[$key])"); $done[$key] = $true }
    } elseif ($line -notmatch '^EMAIL_BACKEND=') {   # let settings.py choose SMTP automatically
        $out.Add($line)
    }
}
foreach ($key in $wanted.Keys) { if (-not $done[$key]) { $out.Add("$key=$($wanted[$key])") } }
[IO.File]::WriteAllLines($envFile, $out)   # UTF-8 without BOM
Write-Host "Saved to .env."

Write-Host "Sending a test email to $gmail ..."
Set-Location $project
& $python manage.py sendtestemail $gmail
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Test email sent. Check your inbox (and the Spam folder)."
    Write-Host "Restart the server (Ctrl+C, then .\scripts\run_server.ps1) so the website uses real email too."
} else {
    Write-Host ""
    Write-Host "Sending failed. Most common causes:"
    Write-Host " - '535 Username and Password not accepted' or 'Connection unexpectedly closed':"
    Write-Host "   wrong App Password, or 2-Step Verification is off. Create a new App Password."
    Write-Host " - Timeout: the network blocks port 587 (some office networks do). Try another network."
    Write-Host "Run this script again to enter a new password."
}
