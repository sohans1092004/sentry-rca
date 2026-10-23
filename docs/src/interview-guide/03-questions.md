
## 3. Question bank

> **Each answer gives the claim, the mechanism, and where to point.**

### 3.1 The result

**Q: Did the LLM help?**
Not on this evidence.
- On 16 held-out incidents the baseline scored top-1 0.438 against the agent's 0.250 **[hosted]**.
- Paired by fixture, the agent had 1 win, 4 losses and 11 ties. That is a loss under the pre-registered rule: losses − wins ≥ 3, with a lower mean (`docs/analysis-plan-phase3.md`).
- On dev it lost too (2/12/5).

**Q: Is that significant?**
Don't claim it is.
- At N=1 the sign test gives p = 0.375 on test. It is reported as description only.
- The decision rule was set before the run, and it lands exactly at its threshold.
- Identical dev runs changed rank 1 in 4 of 6 pairs, so the size of the loss is not established.
- What is established: the direction is the same on dev, on test and at every iteration.

**Q: Why did it lose?**
From the data (`docs/report-phase3.md`):
- it abstained on 8 of 11 root-cause fixtures;
- 11 of 16 runs used all 20 tool calls;
- it never proposed two competing causes, so it scored 0 of 6 on CONFLICTING;
- it scored 0.111 on confounded fixtures.

The verifier rejected 2 of its 6 test hypotheses. One was the right cause with an under-covered log query (pool_exhaustion_t01).

**Q: Then why is the agent there at all?**
- It is the measured alternative.
- The safety design is the reusable part: a scope the model can't widen, data framed as untrusted, strict output, a hard budget, degradation to a verified baseline, and a verifier that decides.
- What I'd build next uses the model where the data says it might help: re-ranking or explaining the baseline's verified candidates (ADR-000, future work).

**Q: Why didn't you just use a bigger model?**
- **Zero cost was a rule.** The laptop has 16 GB and no NVIDIA GPU, and qwen2.5:7b did not fit beside the stack (ADR-000).
- **The local 3B models verified 0 of 145 hypotheses.**
- **Paid tier: declined.** No paid tier was allowed, and using several free accounts to raise the quota would break the provider's terms.
- So the honest scope is "a free-tier flash model at N=1".

### 3.2 The verifier and claims

**Q: Why typed claims and a deterministic verifier, not an LLM judge?**
- **A judge is another model**, one a planted line can also persuade, and its errors are hard to test.
- **A claim is recomputable.** "Inventory's pool-wait mean rose at least 4x over the 15 minutes before" can be recomputed from the cited rows, the same way every time ([[verifier#def _metric_change(]]).
- **"The citation exists" is not enough.** A row can exist and show nothing (ADR-007).

**Q: What does a `log_pattern` claim have to prove?**
- At least `min_count` cited lines contain the pattern.
- The cited queries cover the window *and* the equal-length window before it, untruncated.
- Matches in the window ÷ matches before is at least 2 ([[verifier#def _log_pattern(]], A24).

Presence alone proves nothing, because healthy traffic logs the same vocabulary (A21).

**Q: Can the agent cite the baseline's evidence?**
No.
- Every citation must be a tool call of the same ranker ([[verifier#def _cited(]], A15). `test_a_hypothesis_citing_the_baseline_rankers_call_is_rejected`; guard `same_ranker_citations`.
- Postmortem 004: the agent did cite baseline call numbers by mistake, and every such claim was rejected.

**Q: Can true evidence verify a false cause?**
It could, until A36. Now a root cause must be in scope, and at least one non-runbook claim must be about that service ([[verifier#def verify(]]). Otherwise honest evidence about inventory could have verified a hypothesis naming `dns`.

**Q: What can the verifier not stop?**
A hypothesis whose claims are all true of the data but whose conclusion is wrong. no_fault_002 is the example: the agent's payments / dependency_outage was verified on a fixture with no fault, because provider failures and latency really did rise at an onset. It's a showcase in the viewer. The verifier guarantees support, not truth.

### 3.3 Scope, security and injection

**Q: How do you stop prompt injection?**
In layers, none of them the prompt alone:
1. **Untrusted text is framed as data.** It appears only inside a data block whose boundary is random for each call ([[agent#def new_boundary(]]). `test_planted_instructions_only_ever_appear_inside_a_data_block`.
2. **The model cannot widen its reach.** The server-side scope rejects any other tenant or service ([[tools#def prepare(]]).
3. **The output must parse**, with a closed list of kinds.
4. **The verifier rejects a cause with no evidence about it.**

The obedient-fake-model tests show each layer stopping its attack (`tests/unit/test_agent.py`). Delimiting is a mitigation, not a guarantee, and §11 says so.

**Q: What was the injection-influence rate?**
- 0 of 6 pairs in a 3+3 dev check, and 0 of 1 on test.
- But planted text reached the agent in only 1 of 6 dev runs and none on test. So this measures exposure, not resistance.
- In all 5 hosted dev runs where planted text was seen, the planted cause was never named.

**Q: The viewer shows attacker-controlled log lines. How is that safe?**
- **Everything renders as text.** Every data value goes through `createTextNode` or an attribute value ([[app#function text(v)]]).
- **A strict CSP** blocks inline script.
- **A headless-Chromium test** plants payloads in every field and asserts that nothing executes and nothing becomes markup ([[xss#def assert_inert(]]).
- **Two guards:** with text rendering replaced by HTML parsing the test reports injected elements, and with the CSP removed an inline script runs.

**Q: Where did the API key live?**
- Only in a user environment variable, sent only in an HTTP header.
- A secret scan covers the repository, every cassette and the published viewer ([[secretscan#def scan(]], guard `secret_scan`).
- The key was revoked after the test run.

### 3.4 Evaluation

**Q: Your first baseline scored 1.00. What happened?**
The fixtures leaked the answer (postmortem 001):
- fault-only log strings such as `pool acquire timeout` (198 lines, only in pool_exhaustion fixtures);
- a `code.file.path` of `faults.py` on 325 injected lines;
- later, an HTTP span from starting the batch job.

Faults now surface only through normal code paths, healthy traffic speaks the same words, and a leak test finds markers by measurement. The baseline fell to 0.842 dev and 0.438 test.

**Q: How do you know the test set is held out?**
- **Built apart.** It was recorded separately, with four scenarios the baseline has no rules for (A22).
- **The baseline was frozen first.** It was frozen with its sha256 before test was first evaluated, and any later change blocks the gate until a post-hoc amendment (A27).
- **The agent can't run on test unfrozen.** The CLI refuses a live agent run on test fixtures unless HEAD has the `agent-frozen` tag ([[cli#if "agent-frozen" not in tags.split():]]).
- **No postmortems.** Test fixtures have none in the corpus (A25).

**Q: Why paired by fixture rather than comparing means?**
- Both rankers ran in the same investigation of the same fixture, so per-fixture differences remove fixture difficulty.
- With 16 fixtures, counting wins and losses is honest about how little data there is ([[harness#def paired(]]).

**Q: Why N=1?**
- The free tier allows 500 requests a day, and N=5 over dev and test needs about 3,200 (A41).
- The noise was measured instead: 3 runs with and 3 without planted lines on two dev fixtures.

**Q: The test run was interrupted. Doesn't that taint it?**
- It is recorded as a deviation (A43).
- It was completed at the same commit with the same command.
- The 13 finished fixtures replayed from their recorded responses, so there was no second draw, and were checked identical to the first attempt.
- Only the 3 unfinished fixtures called the model.

**Q: How do you know ClickHouse isn't skewing results?**
- Every tool call of every eval is re-run on a Parquet backend, and the snapshot must be byte-identical (A26).
- It caught one real difference, from approximate `uniq` (A33).

### 3.5 The agent loop

**Q: Why no agent framework?**
- The loop is about 200 lines, where every safety property is visible: budget checks, boundary framing, strict parsing, the repair turn and degradation ([[agent#def _loop(]], ADR-010).
- A framework would hide the control flow I needed to test with fake models.

**Q: What happens when the budget runs out?**
- One last turn with no tools, in which the model must answer.
- If it asks for tools again, or the token or wall-time budget is used, the investigation degrades to the baseline (A37).
- `test_the_tool_call_budget_stops_a_looping_agent`.

**Q: How is it reproducible in CI without a model?**
- Record and replay. The key covers the whole canonical request with each random boundary replaced by a placeholder ([[llm#def request_hash(]], A35).
- A miss raises, and never calls a model.
- CI's `agent-replay` job replays all 35 fixtures.

### 3.6 Pipeline and alerting

**Q: Exactly-once?**
- No: at-least-once, made harmless. Processors commit offsets after the ClickHouse insert, and stable row IDs plus ReplacingMergeTree collapse the redelivered copies.
- Guards: `commit_after_insert` and `stable_ids`.

**Q: What's the throughput ceiling and the bottleneck?**
- About 100,000 mixed events/s with bounded lag **[laptop]**.
- The CPU of the single-threaded Python processors is the limit: metrics at 99.6 % of a core at 125k.
- More partitions and one processor per partition is the upgrade path (`docs/measurements/phase1.md`, M5).

**Q: Why one alert rule on the gateway?**
- Per-service rules open 3-4 incidents per multi-hop fault, with no grouping (A1).
- One edge SLO rule opens one incident, and finding the cause is the investigation's job.

**Q: A fault didn't alert in testing. Why?**
The previous fault was inside the 30-minute alert baseline (postmortem 002, A29). Incident periods are now excluded, and the recorder waits for a clean baseline.

### 3.7 Why not X?

| Instead of | Why not | Where |
|---|---|---|
| an LLM judge | a model can be persuaded; claims can be recomputed | ADR-007 |
| letting the model pick services | the scope is server-side authority | ADR-008 |
| live re-queries for verification | data changes; snapshots are what the ranker saw | ADR-012 |
| ML anomaly detection | determinism and explainability; the alert fixes were to measurement | ADR-004 |
| formal causal inference | not with this data; the heuristic states its blind spots | ADR-006 |
| Redis | its jobs fit Postgres and process memory | ADR-009 |
| React for the viewer | three read-only pages; text nodes plus a browser test enforce the property | A44 |
