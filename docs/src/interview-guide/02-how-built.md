
## 2. How it was built, honestly

> **Spec-driven and AI-assisted: I owned the specification and every decision at its gaps; Claude Code wrote the code under fixed ground rules; the evidence is in the amendments, the guard checks and the measurements.**

**What to say, plainly:**
- "I owned the specification, `docs/SPEC.md`. It changed through 44 dated amendments, each landed with the code it governs and its reason." The repo does not record how the spec itself was drafted. If AI helped draft it too, say so in the same breath.
- "The code was written by an AI coding agent under ground rules I set:
  - stop and ask at every gap or contradiction;
  - never invent a number;
  - never weaken a test;
  - prove every safety guard by removing it and watching its test fail;
  - keep dev and test apart;
  - zero cost."
- "The decisions at the gaps were mine. Examples:
  - the replay-key placeholder (A35);
  - the cause-link verifier rule (A36);
  - a final answer turn before degrading (A37);
  - moving the evaluated agent to a hosted free tier (A41);
  - freezing iteration C for budget compliance rather than accuracy (A42);
  - completing the interrupted test run from its recordings (A43);
  - trimming Phase 4 (A44)."
- "The problems found along the way are on the record, with their fixes:
  - the 1.00 that was too good (postmortem 001);
  - a model-selection misread, corrected in ADR-000;
  - the agent citing the baseline's calls (postmortem 004)."

**If asked "what did you write yourself?"** Answer from the record, and claim no more than it shows. Yours: the spec, the ground rules, and the decisions at the gaps listed above. Written by the agent under your review: the code, the analysis plan and these documents. Then offer to walk through any part of the code, and do it from the links in this guide.

**If asked "would you trust the agent's result more if it had won?"** No. The frozen-plan discipline exists so that the answer doesn't depend on which way it came out. The same rule that called this a loss would have called a 3-fixture margin the other way a win, and I'd have reported the same caveat about N=1.
