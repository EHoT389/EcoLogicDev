$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) { throw 'Сначала выполните установку из README.md' }
$apiProcess = Start-Process -FilePath "$taskRoot\.venv\Scripts\python.exe" -ArgumentList '-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru
try { npm.cmd run dev } finally { Stop-Process -Id $apiProcess.Id -ErrorAction SilentlyContinue }
