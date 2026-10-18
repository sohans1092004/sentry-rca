#!/usr/bin/env bash
# Memory of the compose stack: RSS per container, total, and free memory in the Docker VM and host.
#   bash tools/memory.sh <label>
set -euo pipefail
echo "## memory: ${1:-snapshot} @ $(date -u +%FT%TZ)"
echo '$ docker stats --no-stream (sentry-rca-*)'
docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}' | grep sentry-rca- | sort
docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}' | grep sentry-rca- | awk -F'\t' '
  { split($2, a, " / "); v = a[1]; n = v + 0
    if (v ~ /GiB/) n *= 1024; else if (v ~ /KiB/) n /= 1024; else if (v ~ /[0-9]B$/ && v !~ /MiB/) n /= 1048576
    total += n }
  END { printf "TOTAL\t%.1f MiB (%d containers)\n", total, NR }'
echo '$ docker run --rm alpine:3.20 free -m   (the Docker Desktop WSL2 VM)'
docker run --rm alpine:3.20 free -m
echo '$ powershell (Get-CimInstance Win32_OperatingSystem) free/total physical memory (host)'
powershell.exe -NoProfile -Command '$o = Get-CimInstance Win32_OperatingSystem; "host free {0:N0} MiB of {1:N0} MiB" -f ($o.FreePhysicalMemory/1KB), ($o.TotalVisibleMemorySize/1KB)'
