# Postmortems

Written in the format of Reliant's incident reports: summary, impact, root cause, fix, verification, notes.
Each one is the story behind a SPEC amendment.

| # | Problem | Amendments |
|---|---|---|
| [001](001-fixture-answer-key-leak.md) | The fixtures carried the answer key, so the baseline scored 1.00 | A21-A28, A31, A34 |
| [002](002-alert-baseline-contamination.md) | The previous fault hid the next one from the alert | A29 |
| [003](003-replay-key-could-never-match.md) | The replay key could never match a recorded request | A35 |
| [004](004-agent-cited-baseline-calls.md) | The agent cited the baseline's tool calls, and the verifier rejected every one | A39 |
