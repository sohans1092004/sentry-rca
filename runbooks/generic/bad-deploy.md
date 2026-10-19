title: Regression after a deploy
kind: runbook
---
Symptom: errors or latency start minutes after a deploy finished.
Correlate the anomaly onset with deploy finish times per service; a deploy that finished within about 30 minutes before the onset, on the service whose spans dominate the slow traces, is the prime suspect. Roll back the version and confirm recovery.
