$ErrorActionPreference = "Stop"

# Preserve the UTF-8 console behavior added after Windows user feedback.
$utf8 = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding = $utf8
[Console]::InputEncoding = $utf8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
chcp 65001 | Out-Null

ms-agent ui @args
exit $LASTEXITCODE
