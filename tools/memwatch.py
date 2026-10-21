"""Memory watchdog for live model runs (Phase 3 memory rule). Every `interval` seconds it logs the host's
Available memory (the figure Task Manager and `\\Memory\\Available MBytes` show) and the resident memory of
the Ollama model runner. If Available falls below `floor_mb` it kills the watched process and its children,
and writes STOP, so a run never pushes the laptop into swap. Windows only; stdlib only.

    python tools/memwatch.py <pid to watch> <log.csv> [floor_mb=1024] [interval_s=30]
"""

import csv
import ctypes
import subprocess
import sys
import time
from datetime import UTC, datetime


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]  # fmt: skip


def available_mb() -> int:
    s = _MemStatus()
    s.dwLength = ctypes.sizeof(_MemStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))  # type: ignore[attr-defined]
    return int(s.ullAvailPhys // 2**20)


def rss_mb(image: str) -> int:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout  # fmt: skip
    total = 0
    for row in csv.reader(out.splitlines()):
        if len(row) >= 5 and row[0].lower() == image.lower():
            total += int(row[4].replace(",", "").replace(".", "").split()[0])  # "2,365,000 K"
    return total // 1024


def alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True)
    return str(pid) in out.stdout


def main(pid: int, log: str, floor_mb: int = 1024, interval_s: float = 30.0) -> None:
    with open(log, "a", newline="") as f:
        w = csv.writer(f)
        w.writerow(["utc", "available_mb", "llama_server_rss_mb", "ollama_rss_mb", "python_rss_mb", "event"])
        while alive(pid):
            avail = available_mb()
            event = ""
            if avail < floor_mb:
                event = f"STOP: available {avail} MB < {floor_mb} MB, killed pid {pid}"
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            w.writerow([datetime.now(UTC).isoformat(timespec="seconds"), avail, rss_mb("llama-server.exe"),
                        rss_mb("ollama.exe"), rss_mb("python.exe"), event])  # fmt: skip
            f.flush()
            if event:
                return
            time.sleep(interval_s)
        w.writerow([datetime.now(UTC).isoformat(timespec="seconds"), available_mb(), "", "", "", "watched process ended"])


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2], *(int(a) for a in sys.argv[3:4]), *(float(a) for a in sys.argv[4:5]))
