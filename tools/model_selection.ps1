# Phase 3 model selection, DEV fixtures only: each candidate records one agent run per dev fixture
# (N=1) through `rca eval`, with a memory watchdog that stops the run below 1 GB Available.
#   powershell -File tools/model_selection.ps1 [-Models qwen2.5:3b,llama3.2:3b,qwen2.5:1.5b] [-WallS 600]
param([string[]]$Models = @("qwen2.5:3b", "llama3.2:3b", "qwen2.5:1.5b"), [int]$WallS = 600, [int]$N = 1,
      [string]$Tag = "", [string]$Split = "dev", [string]$Provider = "ollama", [string]$BaseUrl = "",
      [string]$MinIntervalS = "0", [int]$MaxTokens = 60000)
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force runs | Out-Null
if ($Provider -eq "hosted") {  # the key is read from the user environment, never passed on a command line
    $env:LLM_API_KEY = [Environment]::GetEnvironmentVariable("LLM_API_KEY", "User")
    $env:LLM_BASE_URL = $BaseUrl
    $env:LLM_MIN_INTERVAL_S = $MinIntervalS
    if (-not $env:LLM_API_KEY) { "$(Get-Date -Format o) no LLM_API_KEY in the user environment" | Add-Content runs/selection.log; exit 1 }
}
foreach ($m in ($Models -join "," -split ",")) {  # -File passes a list as one string
    $slug = $m.Replace(":", "_").Replace("/", "_") + $(if ($Tag) { "-$Tag" } else { "" })
    $out = "runs/selection-$slug.json"
    "$(Get-Date -Format o) start $m" | Add-Content runs/selection.log
    $evalArgs = @("run", "rca", "eval", "--ranker", "agent", "--model", $m, "--llm", "record", "--split", $Split,
        "--n", "$N", "--wall-s", "$WallS", "--max-tokens", "$MaxTokens", "--out", $out)
    if ($Tag) { $evalArgs += @("--tag", $Tag) }
    if ($Provider -eq "hosted") { $evalArgs += @("--provider", "hosted") }
    $p = Start-Process -FilePath uv -ArgumentList $evalArgs `
        -RedirectStandardOutput "runs/selection-$slug.out" -RedirectStandardError "runs/selection-$slug.err" `
        -NoNewWindow -PassThru
    $w = Start-Process -FilePath uv -ArgumentList @("run", "python", "tools/memwatch.py", "$($p.Id)",
        "runs/memory-$slug.csv", "1024", "30") -NoNewWindow -PassThru
    $p.WaitForExit()
    # the watchdog notices the exit within one interval and writes its last row; a STOP row is written
    # after it kills the eval, so wait for it before reading the log
    if (-not $w.WaitForExit(90000)) { Stop-Process -Id $w.Id -Force }
    "$(Get-Date -Format o) end $m exit $($p.ExitCode)" | Add-Content runs/selection.log
    if (Select-String -Path "runs/memory-$slug.csv" -Pattern "STOP" -Quiet) {
        "$(Get-Date -Format o) memory floor hit during $m; stopping the selection" | Add-Content runs/selection.log
        break
    }
    if ($Provider -eq "ollama") { & "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" stop $m }  # free it before the next loads
}
"$(Get-Date -Format o) selection done" | Add-Content runs/selection.log
