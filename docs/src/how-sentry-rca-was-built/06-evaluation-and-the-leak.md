
## 6. Evaluation, and the fixtures that leaked the answer

> **The first eval scored 1.00 because the fixtures named their own faults. Making the data honest dropped the baseline to 0.842 on dev and 0.438 on held-out test, and everything after that was measured against a frozen baseline on a split nobody had tuned on.**

### 6.1 The leak (postmortem 001)

The Phase 2 baseline eval scored top-1 1.00 over 19 fixtures and 5 runs (`docs/measurements/phase2.md`, P1). The write-up called it optimistic at the time. Three leaks explained it, found in turn:

1. **The answer key was in the injector's words.** The fault code paths logged what they did:
   - `pool acquire timeout after …` ([[6482a38:services/demo_db.py#pool acquire timeout after]]);
   - `slow query … took over … ms` ([[6482a38:services/demo_db.py#slow query %s took over]]);
   - `KeyError 'currency' (version …)` for a bad deploy ([[6482a38:services/faults.py#KeyError 'currency']]).

   The Phase 2 baseline mapped those strings to cause kinds ([[7fb7ac4:investigation/baseline.py#"pool acquire timeout": "pool_exhaustion",.."provider charge failed": "dependency_outage",]]). In the v2 datasets each string appears only in its own scenario's fixtures: `pool acquire timeout` 198 times, `slow query` 2,164, `KeyError 'currency'` 164. In v3 they are gone, or present in every scenario (`docs/measurements/phase4/leak-history.txt`, from `tools/leak_history.py`).
2. **The `faults.py` attribute.** Planted lines, deploy announcements and the bad-deploy error were logged by the fault module's own logger ([[6482a38:services/faults.py#log = logging.getLogger("faults")]]). The OpenTelemetry handler records each line's source file, so 325 v2 log lines carried `code.file.path` = `…/faults.py`, a perfect label for "injected". In v3: none.
3. **The batchjob trace.** After the first two were fixed, the new leak test failed 96 items on dev, all from one marker. The injector started noisy_neighbor's CPU job with `POST /_fault` to `batchjob`, leaving a request span and request metrics only noisy_neighbor fixtures had (A31, commit `e17c0ff`). The job now starts with `docker exec` inside the container.

A fourth shortcut was in the corpus: 55 of 70 runbook citations pointed at a sibling fixture's postmortem, which describes the same fault (`docs/measurements/phase2.md`, P3).

### 6.2 The hardening that followed (Phase 2.5)

| Change | What it prevents | Amendment |
|---|---|---|
| Faults surface only through normal code paths; healthy traffic emits the same vocabulary | a string identifying the scenario | A21 |
| A log pattern counts only if it at least doubled against the window before | presence of shared vocabulary passing as evidence | A24 |
| Confounders (harmless deploy, mild anomaly, sampling) in about half the fixtures | a ranker that blames the first deploy it sees | A22 |
| A held-out test split with four scenarios the baseline was never built for | measuring on the data the rules were written against | A22, A27 |
| The baseline frozen before test, its sha256 checked; any later change needs a post-hoc amendment | quietly tuning on test | A27, A32 |
| Same-scenario postmortems excluded from runbook search during a fixture's eval | the corpus stating the answer | A25, A34 |
| The leak test: every log template (source file, function, line, severity), attribute, span, metric and deploy shape never seen in healthy traffic must appear with 2+ scenarios, not only one, and not only with confounders | markers nobody thought to look for | A28 |
| Backend agreement: every tool call re-run on Parquet must give a byte-identical snapshot | an eval that measures the database, not the method | A26 |

The leak test passes: 18,340 items across 35 datasets, 101 never seen in healthy traffic, 0 that identify a scenario or a confounder (`docs/measurements/phase2_5.md`, Q2). Tests: `test_markers_are_caught_and_shared_vocabulary_is_not` and `test_corpus_leaks_are_caught`. Its limit: it checks single items, not combinations (postmortem 001, Notes).

### 6.3 How the agent was compared (Phase 3)

- **Dev for every choice, test once.** Model, prompt, budget and parsing were all chosen on dev. Before the test run:
  - a pre-registered analysis plan was committed, with the decision rule, the noise reporting and the only version allowed on test (`docs/analysis-plan-phase3.md`);
  - the agent was tagged `agent-frozen` (commit `62dfc92`);
  - `rca eval` refuses a live agent run on test fixtures unless HEAD carries that tag ([[cli#if "agent-frozen" not in tags.split():]]).
- **Paired by fixture.** For each fixture, agent and baseline are compared over the same runs in the same investigation ([[harness#def paired(]]). The decision rule: the agent beats the baseline if wins − losses ≥ 3 and its mean is higher; it loses in the mirror case; otherwise there is no measurable difference. The exact sign test is reported for description only ([[harness#def sign_test(]]).
- **Noise at N=1.** The free tier allowed one agent run per fixture (A41). The measured stand-in for spread: identical dev runs changed rank 1 in 4 of 6 pairs. So no difference of one or two fixtures is called meaningful.
- **One deviation, recorded** (A43). The single test run was killed from outside after 13 of 16 fixtures; the cause is not in the logs. It was completed with the identical command and commit. The 13 finished fixtures replayed from their recordings (no second draw) and were checked identical; only the 3 unfinished fixtures called the model.
