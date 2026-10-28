# Jalankan test, cek konstanta, lalu pipeline penuh. Pakai: .\run.ps1  (HASH_SALT harus sudah di-set)
$ErrorActionPreference = "Stop"
if (-not $env:HASH_SALT) { Write-Error "Set dulu `$env:HASH_SALT (salt tim). Jangan ditulis ke file." }
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m anmedsos_prep check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $py -m anmedsos_prep run
exit $LASTEXITCODE
