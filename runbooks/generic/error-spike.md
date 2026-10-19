title: Spike in 5xx errors
kind: runbook
---
Symptom: the share of 5xx responses jumps.
Find the deepest service returning 5xx in the failing traces; upstream services usually just propagate it (502/503). Read that service's ERROR logs around the onset; an exception repeated with the same message after a deploy usually means a code regression. Roll back first, investigate second.
