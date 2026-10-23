
## 10. The public viewer

> **A static site of recorded investigations, built in CI from the replayed cassettes: no server, no key, and telemetry rendered only as text under a strict CSP.**

**Live:** <https://sohans1092004.github.io/sentry-rca/> (A44).

- **What it shows:**
  - an index of all 35 investigations, with six showcases chosen to tell the real story;
  - an incident page: the timeline; baseline and agent hypotheses side by side; every claim with its verifier result and reason; the model's narrative labelled "unverified explanation"; evidence snapshots opened from each citation, with the cited rows highlighted and planted injection rows marked; out-of-scope evidence with the scope rejection; the full tool-call audit;
  - an evaluation page: the dev and test tables, the per-fixture paired comparison, both confusion matrices and the noise caveat.
- **How it is built:** `tools/export_viewer.py` reads one eval run's investigations from Postgres, plus the fixture labels. It writes JSON for each investigation and each cited snapshot ([[export#def investigation(]]). CI runs it after the agent-replay job, scans the output for secrets and publishes it from `main` only.
- **The showcases** ([[export#SHOWCASE = ]]):
  - pool_exhaustion_t01, a baseline win the agent missed;
  - bad_deploy_001, an agent hypothesis rejected with its reason;
  - noisy_neighbor_t01, INSUFFICIENT_EVIDENCE with out-of-scope evidence;
  - dependency_outage_injection_001, an injection fixture where planted text reached the agent;
  - ambiguous_t01, a conflicting fixture;
  - no_fault_002, the agent's verified false positive.
- **Untrusted text stays text.** Every value from the data reaches the page through `document.createTextNode` or an attribute value ([[app#function text(v)]]); nothing assigns HTML. Each page carries the §11 CSP, `default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'`, in a meta tag, because GitHub Pages cannot set headers.
- **Proved in a browser.** `test_a_script_payload_in_recorded_telemetry_never_executes_in_the_viewer` builds a synthetic export with four payloads in every field, loads all three pages in headless Chromium and opens every citation. It asserts that no payload ran, no dialog opened, no element was parsed from telemetry, no CSP violation fired, and the payload is visible as text ([[xss#def assert_inert(]]). `test_the_viewer_csp_blocks_inline_script` asserts the CSP is in force.
- **Why plain JavaScript and not React (the SPEC said React):** the site is read-only and three pages, so a build step would add a toolchain and nothing the pages need. React's escaping would have helped, but the text-node rule plus the browser test enforce the same property (A44).
