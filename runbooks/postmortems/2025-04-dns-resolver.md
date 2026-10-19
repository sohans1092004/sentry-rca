title: Postmortem: internal DNS resolver outage
kind: postmortem
---
The internal resolver's upstream was removed during a network change. New connections across all services failed with unknown-host errors for nine minutes; existing pooled connections kept working, which hid the scope. Root cause: resolver configuration. Fix: two resolvers, change review.
