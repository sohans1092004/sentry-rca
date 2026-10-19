title: Postmortem: retry storm from aggressive client timeouts
kind: postmortem
---
A client library upgrade lowered the default timeout to 200 ms and enabled three immediate retries. During a brief slowdown of the search service, callers tripled its request rate and kept it overloaded for twenty minutes after the original slowdown ended. Root cause: retries without backoff. Fix: exponential backoff with jitter and a retry budget.
