title: Postmortem: log volume full on a database node
kind: postmortem
---
Verbose query logging left on after debugging filled the log volume in two days; the database stopped accepting writes. Fix: log rotation, a disk usage alert.
