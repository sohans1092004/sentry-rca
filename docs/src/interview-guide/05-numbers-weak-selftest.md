
## 6. Numbers cheat sheet

| Number | Value | Tag and source |
|---|---|---|
| Test top-1 judged, agent vs baseline | 0.250 vs 0.438 | [hosted] `docs/report-phase3.md` |
| Test paired top-1, agent W/L/T | 1 / 4 / 11 | [hosted] same |
| Dev top-1 judged, agent vs baseline | 0.316 vs 0.842 | [hosted] same |
| Dev paired, agent W/L/T | 2 / 12 / 5 | [hosted] same |
| Test top-3, agent vs baseline | 0.250 vs 0.500 | [hosted] same |
| Agent abstentions on root-cause test fixtures | 8 of 11 | [hosted] same |
| Runs using all 20 tool calls (test) | 11 of 16 | [hosted] same |
| Identical dev runs changing rank 1 | 4 of 6 pairs | [hosted] `docs/measurements/phase3/iterations/iterC-day1.md` |
| Agent hypotheses verified (test) | 4 of 6 | [hosted] `docs/report-phase3.md` |
| Gold claims rejected (verifier false negatives) | 0 of 54 dev, 0 of 41 test | [laptop] `docs/measurements/phase2_5.md` |
| Baseline before and after the leak fix | 1.00 → 0.842 dev, 0.438 test | [laptop] `docs/measurements/phase2.md`, `phase2_5.md` |
| Leak test | 18,340 items, 101 never healthy, 0 leaks | [laptop] `docs/measurements/phase2_5.md` |
| Local models' verified hypotheses | 0 of 145 | [laptop] ADR-000 |
| Ingestion ceiling | ~100,000 events/s; Python processors CPU-bound | [laptop] `docs/measurements/phase1.md` |
| Alert latency, fast-onset | 13.0-26.7 s (target < 30 s) | [laptop] `docs/measurements/phase2_5.md` |
| Baseline time to outcome | 1.3-3.5 s | [laptop] same |
| Agent model time per test run | 118 s median, 213 s max | [hosted] `docs/report-phase3.md` |
| Agent tokens per test run | 102k median, 126k max | [hosted] same |
| Budget | 20 tool calls, 150,000 tokens, 600 s | A41, A42 |
| Stack memory | 2.07 GB, 17 containers; qwen2.5:3b runner 2.2-2.4 GB | [laptop] `docs/measurements/phase2_5.md`, ADR-000 |
| Fixtures | 35 (19 dev, 16 test); injection 3 of 5 | A22, A44 |
| Guard checks | 69, all pass | `tools/guard_checks.out` |
| Tests | 189 unit, 33 integration, 4 viewer | [CI] |

## 7. Weak spots, and honest answers

| They ask | Say |
|---|---|
| "N=1? That's nothing." | Agreed: it's what the free tier allowed. The noise was measured (4 of 6 pairs flip), the rule was fixed in advance, and I don't claim the size of the loss, only its direction. |
| "Your agent is just a bad prompt." | Possibly: iteration was capped at one dev pass a day. But iteration C traded accuracy for budget compliance knowingly. The failure modes (abstaining, running out of calls, no conflicting answers) are structural, and they point to re-ranking, not more prompting. |
| "35 synthetic fixtures from your own demo system?" | Yes, and that's why the leak work matters: the data was made honest before anything was measured on it, and test was held out. It's still one demo system; I don't claim it generalizes. |
| "The verifier passed a false positive." | Yes, no_fault_002. The verifier guarantees support, not truth. That's stated and shown in the viewer. |
| "Injection 0 of 6 proves nothing." | Right: planted text barely reached the agent, so it measures exposure. The layered defences are shown by the adversarial unit tests, not by that rate. |
| "You skipped the UI and observability." | Deferred in A44, with reasons. The result doesn't depend on them. |
| "Who wrote the code?" | An AI coding agent, under my spec and ground rules; the decisions at the gaps were mine (section 2). |

## 8. Self-test

1. What makes a `log_pattern` claim fail even when the line really is in the logs?
2. Why can't the agent cite the baseline's tool calls, and what went wrong when it tried?
3. Name the three leaks found in the fixtures, in order.
4. What is the replay key, and why does it contain a placeholder?
5. What happens when the agent's tool-call budget runs out?
6. State the pre-registered decision rule and apply it to 1 / 4 / 11.
7. Why is the injection-influence rate weak evidence here?
8. Which fixture shows that the verifier guarantees support, not truth?
9. What is the throughput bottleneck, and what would you change first?
10. What would you build next, and how would you evaluate it?

### Answer key

1. The pattern must at least double against the equal-length window before. The cited queries must cover both windows, untruncated (A24).
2. The verifier requires every cited call to have the hypothesis's ranker (A15). Small models cited low numbers that belonged to the baseline; the fix was local numbering (A39, postmortem 004).
3. Fault-only log strings; `code.file.path` = `faults.py` on injected lines; the HTTP span from starting the batch job (postmortem 001).
4. sha256 of model, digest, canonical request and run index. The data boundaries are random per call, so they are replaced by a placeholder, or no request would ever repeat (A35).
5. One answer-only turn. Asking for tools again, or running out of tokens or time, degrades to the baseline's verified answer (A37).
6. Beats if wins − losses ≥ 3 and the mean is higher; loses in the mirror case; otherwise no measurable difference. 1 / 4 / 11: losses − wins = 3 and the mean is lower, so it loses.
7. Planted text reached the agent in 1 of 6 dev runs and 0 on test, so the with and without runs were mostly identical.
8. no_fault_002.
9. The CPU of the single-threaded Python processors, at ~100k events/s. Add partitions and one processor per partition.
10. The model re-ranks or explains the baseline's verified candidates. Frozen, pre-registered, test once, paired by fixture (ADR-000).
