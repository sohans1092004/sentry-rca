title: Disk full
kind: runbook
---
Symptom: write failures and crashes on one node.
Find the largest growing directory (logs, temp files, a database volume); rotate or expand, then add a usage alert at 80 percent.
