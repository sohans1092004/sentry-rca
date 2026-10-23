
## 8. Results: the baseline beat the agent

> **On held-out test the frozen agent scored top-1 0.250 against the baseline's 0.438, and lost under the pre-registered rule (1 win, 4 losses, 11 ties). It was safe, and it was not useful: the verifier stopped its unproven claims, and what remained was mostly "insufficient evidence".**

### 8.1 Dev and test **[hosted]**, one run per fixture

| | dev agent | dev baseline | **test agent** | **test baseline** |
|---|---|---|---|---|
| top-1 judged | 0.316 | 0.842 | **0.250** | **0.438** |
| top-1 exact (service, kind) | 0.316 | 0.842 | 0.188 | 0.313 |
| top-3 judged | 0.316 | 0.842 | 0.250 | 0.500 |
| outcome correct | 7/19 | 13/19 | 5/16 | 8/16 |
| clean fixtures, top-1 | 0.400 | 1.000 | 0.429 | 0.571 |
| confounded fixtures, top-1 | 0.222 | 0.667 | 0.111 | 0.333 |
| paired top-1 (agent W/L/T) | 2/12/5 | | **1/4/11** | |
| sign test p (description only) | 0.013 | | 0.375 | |

Sources: `docs/report-phase3.md` and `docs/measurements/phase3/test/test-frozen.json`. The baseline's test numbers equal the accepted Phase 2.5 result exactly.

**Test, paired by fixture:**
- **The one win** is no_fault_t01. The agent correctly said nothing; the baseline blamed a harmless deploy.
- **The four losses:**
  - ambiguous_t01 and ambiguous_t02: the baseline named one of the two causes; the agent abstained;
  - cpu_throttling_t01: the baseline found the service; the agent abstained;
  - pool_exhaustion_t01: the agent named the right cause, but its log claim came from a query that did not cover the window before the fault, so the verifier rejected it. This is a showcase in the viewer.

**Outcome confusion on test** (rows expected, columns given):

| expected | agent: root cause | agent: insufficient | agent: conflicting | baseline: root cause | baseline: insufficient | baseline: conflicting |
|---|---|---|---|---|---|---|
| root cause (11) | 3 | 8 | 0 | 7 | 3 | 1 |
| insufficient (2) | 0 | 2 | 0 | 1 | 1 | 0 |
| conflicting (3) | 0 | 3 | 0 | 3 | 0 | 0 |

### 8.2 Why it lost (from the data)

- **It abstains.** 8 of 11 root-cause fixtures ended "insufficient evidence" on test (8 of 11 on dev too). Iteration C made it require a sharp rise at the anomaly onset before claiming anything. That removed false claims and budget overruns, and also most true ones.
- **It runs out of looking.** 11 of 16 test runs used all 20 tool calls and answered on the forced final turn; 7 used the repair turn.
- **It never says CONFLICTING_EVIDENCE** (0 of 6 such runs on dev and test). That outcome needs two competing verified causes, and the agent never proposed two.
- **Confounders hurt it most:** top-1 0.111 on the 9 confounded test fixtures, against 0.429 on the 7 clean ones.
- **The budget of a free tier.** N=1 and one dev pass a day meant few prompt iterations. The local models, which had no quota, never produced a verified hypothesis.

### 8.3 What held

| | dev (frozen) | test |
|---|---|---|
| agent hypotheses verified / rejected | 4 / 2 | 4 / 2 |
| gold claims rejected / out-of-scope citations allowed / backend mismatches | 0 / 0 / 0 | 0 / 0 / 0 |
| degraded runs / parse failures | 0 / 1 | 0 / 0 |
| tokens per run, median / max | 87k / 123k | 102k / 126k |
| model time per run, median / max **[hosted]** | 86 s / 371 s | 118 s / 213 s |

**Injection, as measured:**
- **Exposure was low.** Planted text reached the agent's prompt in 1 of 6 runs of a 3+3 dev check, and in 0 of 10 prompts on test. Iteration C's narrow log queries mostly didn't match the planted lines.
- **The influence rate measures exposure here, not resistance.** When nothing planted reaches the prompt, the "without" run's requests are identical and replay the "with" run's answers.
- **What was seen:** in all 5 hosted dev runs where planted text did reach the agent, the planted cause (gateway, DNS, TLS, certificate) was never named (`docs/measurements/phase3/iterations/iterC-day1.md`).

**Replay:** a local replay of all 35 fixtures with no key reproduced every recorded dev and test result **[replay]** (`docs/measurements/phase3/test/replay-check-all.json`).

### 8.4 How sure

The margin sits exactly on the rule's threshold (losses − wins = 3). At N=1, with identical runs changing rank 1 in 4 of 6 dev pairs, a re-run could land on "no measurable difference". It would not plausibly land on a win: the direction is the same on dev, on test and at every iteration. The hosted model has no digest, so a re-run on another day may differ. The cassettes, not a re-run, are the reference.
