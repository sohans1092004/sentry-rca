# Phase 3, Day 1 (DEV only), started after the Gemini free-tier daily reset (midnight Pacific = 12:30 IST):
#   1. iteration C, one dev pass at N=1 with the hosted model (tag iterC);
#   2. injection check: each dev injection fixture 3 times with and 3 times without its planted lines
#      (rca eval --n 3 runs both and compares rank 1 run by run), tag injcheck.
# Nothing here touches TEST fixtures; the freeze is done after the results are reviewed.
#   powershell -File tools/day1_runs.ps1 [-StartAt "12:35"]
param([string]$StartAt = "12:35")
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$log = "runs/day1.log"
$start = [datetime]::ParseExact($StartAt, "HH:mm", $null)
if ($start -lt (Get-Date)) { $start = $start.AddDays(1) }
"$(Get-Date -Format o) waiting until $($start.ToString('o'))" | Add-Content $log
while ((Get-Date) -lt $start) { Start-Sleep 60 }
$url = "https://generativelanguage.googleapis.com/v1beta/openai"
"$(Get-Date -Format o) iteration C dev pass" | Add-Content $log
& powershell -NoProfile -ExecutionPolicy Bypass -File tools/model_selection.ps1 -Models gemini-3.5-flash-lite `
    -Tag iterC -Provider hosted -BaseUrl $url -MinIntervalS 4 -MaxTokens 150000
"$(Get-Date -Format o) iteration C done: $(Get-Content runs/selection.log -Tail 1)" | Add-Content $log
$env:LLM_API_KEY = [Environment]::GetEnvironmentVariable("LLM_API_KEY", "User")
$env:LLM_BASE_URL = $url
$env:LLM_MIN_INTERVAL_S = "4"
"$(Get-Date -Format o) injection check" | Add-Content $log
& uv run rca eval --ranker agent --provider hosted --model gemini-3.5-flash-lite --llm record --split dev --n 3 `
    --wall-s 600 --max-tokens 150000 --tag injcheck --out runs/injcheck.json `
    dependency_outage_injection_001 slow_query_injection_002 > runs/injcheck.out 2> runs/injcheck.err
"$(Get-Date -Format o) injection check exit $LASTEXITCODE" | Add-Content $log
