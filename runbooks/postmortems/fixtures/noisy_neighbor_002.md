title: Postmortem: noisy neighbor incident (noisy_neighbor_002)
kind: postmortem
fixture_id: noisy_neighbor_002
---
Incident on gateway, alert 20 s after the fault began.
Root cause: a CPU-heavy batch job on the core shared with payments and inventory starved both of CPU. A deploy to gateway shortly before was unrelated.
Symptoms: payments, inventory, orders, gateway slowed or failed as a result.
Resolution: the fault was removed and the incident resolved on its own.
