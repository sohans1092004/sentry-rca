title: Postmortem: expired certificate on api.internal
kind: postmortem
---
The certificate of api.internal expired at 00:00 UTC; every call to it failed TLS handshakes. Renewal automation had been disabled during a migration. Fix: re-enabled automation, expiry alert 14 days ahead.
