$ErrorActionPreference = "Stop"

# Force UTF-8 output for this session to avoid garbled text in Windows consoles.
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::UTF8
$env:PYTHONUTF8 = "1"
chcp 65001 | Out-Null

ms-agent ui @args
