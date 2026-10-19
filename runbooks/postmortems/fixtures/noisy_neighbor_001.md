title: Postmortem: noisy neighbor incident (noisy_neighbor_001)
kind: postmortem
fixture_id: noisy_neighbor_001
---
Incident on gateway opened 2026-10-18 23:11:42.387404+00:00 (17 s after the fault began).
Root cause: a CPU-heavy batch job sharing a core with payments and inventory starved them of CPU.
Symptoms: payments, inventory, orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
