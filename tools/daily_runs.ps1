# Phase 3 daily runner, started by the Windows scheduled task "SentryRCA-Phase3-daily" at 12:35 IST, just
# after the Gemini free tier's daily reset (midnight Pacific). Each day it runs the next stage that is due,
# once:
#   stage 1 (DEV): iteration C, one dev pass at N=1; then the injection check (each dev injection fixture
#            3 times with and 3 times without its planted lines). Marker: runs/stage1.done
#   stage 2 (TEST): only when HEAD carries the agent-frozen tag (the freeze is a reviewed, manual step):
#            the frozen agent on the test split, N=1, once. Marker: runs/stage2.done
# Otherwise it logs that nothing is due. A lock file stops two runs overlapping.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force runs | Out-Null
$log = "runs/daily.log"
function Log($m) { "$(Get-Date -Format o) $m" | Add-Content $log }
if (Test-Path runs/daily.lock) { Log "a run is already in progress (runs/daily.lock); skipping"; exit 0 }
New-Item runs/daily.lock -ItemType File | Out-Null
try {
    $url = "https://generativelanguage.googleapis.com/v1beta/openai"
    $model = "gemini-3.5-flash-lite"
    $env:LLM_API_KEY = [Environment]::GetEnvironmentVariable("LLM_API_KEY", "User")
    $env:LLM_BASE_URL = $url
    $env:LLM_MIN_INTERVAL_S = "4"
    if (-not $env:LLM_API_KEY) { Log "no LLM_API_KEY in the user environment; nothing run"; exit 1 }
    $frozen = (git tag --points-at HEAD) -contains "agent-frozen"
    if (-not (Test-Path runs/stage1.done)) {
        Log "stage 1: iteration C dev pass"
        if (Test-Path runs/selection.log) { Move-Item runs/selection.log "runs/selection-$(Get-Date -Format yyyyMMddHHmm).log" }
        & powershell -NoProfile -ExecutionPolicy Bypass -File tools/model_selection.ps1 -Models $model `
            -Tag iterC -Provider hosted -BaseUrl $url -MinIntervalS 4 -MaxTokens 150000
        $done = Select-String -Path runs/selection.log -Pattern "selection done" -Quiet
        $floor = Select-String -Path runs/selection.log -Pattern "memory floor" -Quiet
        Log "stage 1: dev pass finished (memory floor hit: $floor); $(Get-Content runs/selection.log -Tail 1)"
        Log "stage 1: injection check"
        & uv run rca eval --ranker agent --provider hosted --model $model --llm record --split dev --n 3 `
            --wall-s 600 --max-tokens 150000 --tag injcheck --out runs/injcheck.json `
            dependency_outage_injection_001 slow_query_injection_002 > runs/injcheck.out 2> runs/injcheck.err
        Log "stage 1: injection check exit $LASTEXITCODE"
        if ($done -and -not $floor -and $LASTEXITCODE -le 1 -and (Test-Path runs/injcheck.json)) {
            New-Item runs/stage1.done -ItemType File -Force | Out-Null
            Log "stage 1 complete"
        } else { Log "stage 1 incomplete; it runs again at the next reset" }
    } elseif ($frozen -and -not (Test-Path runs/stage2.done)) {
        Log "stage 2: frozen agent on TEST, N=1, once"
        & uv run rca eval --ranker agent --provider hosted --model $model --llm record --split test --n 1 `
            --wall-s 600 --max-tokens 150000 --tag frozen --out runs/test-frozen.json > runs/test-frozen.out 2> runs/test-frozen.err
        Log "stage 2: test exit $LASTEXITCODE"
        if (Test-Path runs/test-frozen.json) { New-Item runs/stage2.done -ItemType File -Force | Out-Null; Log "stage 2 complete" }
    } else {
        Log "nothing due (stage1.done=$(Test-Path runs/stage1.done), frozen=$frozen, stage2.done=$(Test-Path runs/stage2.done))"
    }
} finally {
    Remove-Item runs/daily.lock -Force -ErrorAction SilentlyContinue
}
