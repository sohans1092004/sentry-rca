"use strict";
// Sentry-RCA static viewer (A44). Every value in data/ is recorded telemetry or model output, so it is
// attacker-controlled (SPEC §11): it reaches the page only as text nodes and attribute values. Nothing in
// this file parses a string as HTML, and the page's CSP forbids inline script.

const REPO = "https://github.com/sohans1092004/sentry-rca/blob/main/";

function text(v) {
  return document.createTextNode(typeof v === "string" ? v : JSON.stringify(v));
}

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "onclick") e.addEventListener("click", v);
    else if (k === "class") e.className = v;
    else e.setAttribute(k, v);
  }
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    e.append(k instanceof Node ? k : text(k));
  }
  return e;
}

// replaceChildren, but skipping null/false and flattening arrays, as el() does
function fill(main, ...kids) {
  main.replaceChildren(el("div", {}, kids));
}

async function load(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

const invLink = (fid) => el("a", { href: "investigation.html?f=" + encodeURIComponent(fid) }, fid);
const pct = (x) => (x === null || x === undefined ? "—" : x.toFixed(3));
const cause = (rc) => (rc ? `${rc[0]} / ${rc[1]}` : "none");
const OUTCOMES = ["ROOT_CAUSE_IDENTIFIED", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE"];
const SHORT = { ROOT_CAUSE_IDENTIFIED: "root cause", INSUFFICIENT_EVIDENCE: "insufficient", CONFLICTING_EVIDENCE: "conflicting" };

function badge(kind, label) {
  const cls = { passed: "pass", win: "pass", allowed: "pass", failed: "fail", rejected: "fail", loss: "fail", clamped: "warn" };
  return el("span", { class: "badge " + (cls[kind] || "plain") }, label || kind);
}

function table(head, rows, rowClass) {
  return el("div", { class: "scroll" }, el("table", {},
    el("thead", {}, el("tr", {}, head.map((h) => el("th", {}, h)))),
    el("tbody", {}, rows.map((r, i) => el("tr", rowClass ? { class: rowClass(i) } : {}, r.map((c) => el("td", {}, c)))))));
}

function kv(pairs) {
  return el("dl", { class: "kv" }, pairs.filter((p) => p[1] !== null && p[1] !== undefined).map(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
}

function cell(v) {
  if (v === null || v === undefined) return "";
  if (typeof v !== "object") return String(v);
  if (Array.isArray(v)) return el("pre", {}, JSON.stringify(v));
  return el("pre", {}, Object.entries(v).map(([k, x]) => `${k}: ${typeof x === "object" ? JSON.stringify(x) : x}`).join("\n"));
}

function headline(ev) {
  const t = ev.splits.test;
  const p = t.paired.top1_tally;
  return `On ${t.fixtures} held-out test incidents the deterministic baseline beat the LLM agent: top-1 ` +
    `${pct(t.baseline_same_investigations.top1.mean)} against ${pct(t.top1.mean)}; paired by incident, the agent ` +
    `won ${p.win || 0}, lost ${p.loss || 0} and tied ${p.tie || 0}.`;
}

function provenance(meta) {
  return el("p", { class: "muted" }, "Recorded data only: eval run ", el("span", { class: "mono" }, meta.eval_run_id),
    " at commit ", el("a", { href: "https://github.com/sohans1092004/sentry-rca/commit/" + meta.git_sha }, meta.git_sha.slice(0, 7)),
    ", replayed from the committed cassettes of the frozen agent's model responses. There is no live endpoint.");
}

// ---------- index ----------

async function indexPage(main) {
  const [idx, ev] = await Promise.all([load("data/index.json"), load("data/eval.json")]);
  const shows = idx.investigations.filter((i) => i.showcase);
  fill(main, 
    el("h1", {}, "Sentry-RCA: recorded investigations"),
    el("p", { class: "lead" }, headline(ev)),
    el("p", {}, "Each investigation below ran the deterministic baseline first, then the LLM agent, and checked every " +
      "claim of both with the same deterministic verifier. Narratives from the model are shown as unverified explanation; " +
      "evidence opens from each claim's citations. ", el("a", { href: "eval.html" }, "Evaluation tables"), "."),
    provenance(idx),
    el("h2", {}, "Start here"),
    el("ul", { class: "showcase" }, shows.map((i) => el("li", {}, invLink(i.fixture), ` (${i.split}): `, i.showcase))),
    el("h2", {}, `All ${idx.investigations.length} investigations`),
    table(["fixture", "split", "expected", "baseline rank 1", "agent rank 1", "shown outcome", "top-1, agent vs baseline"],
      idx.investigations.map((i) => [invLink(i.fixture), i.split, SHORT[i.expected], cause(i.baseline_rank1),
        cause(i.agent_rank1), SHORT[i.outcome] || i.outcome, badge(i.top1)])));
}

// ---------- investigation ----------

const FIRST = ["ts", "service", "severity", "body", "metric", "value", "name", "kind", "status", "duration_ms"];

// rows: [{r, i}] with i the row's position in the snapshot
function evidenceTable(rows, cited, planted) {
  const keys = FIRST.filter((k) => rows.some(({ r }) => k in r));
  for (const { r } of rows) for (const k of Object.keys(r)) if (!keys.includes(k) && k !== "row_id") keys.push(k);
  keys.push("row_id");
  return table(["#", ...keys], rows.map(({ r, i }) => [String(i + 1), ...keys.map((k) => cell(r[k]))]),
    (j) => [cited.has(rows[j].r.row_id) ? "cited" : "", planted.has(rows[j].r.row_id) ? "planted" : ""].join(" "));
}

function openEvidence(inv, call, rowIds) {
  const box = document.getElementById("evidence");
  const planted = new Set(inv.label.planted_row_ids || []);
  box.replaceChildren(el("h2", {}, `Evidence: tool call #${call.seq}`), el("p", { class: "muted" }, "Loading snapshot…"));
  box.scrollIntoView({ behavior: "smooth", block: "start" });
  load(`data/snap/${encodeURIComponent(call.snapshot)}.json`).then((snap) => {
    const cited = new Set(rowIds);
    const all = snap.rows.map((r, i) => ({ r, i }));
    const some = all.filter(({ r }) => cited.has(r.row_id) || planted.has(r.row_id));
    const holder = el("div", {}, evidenceTable(some.length ? some : all, cited, planted));
    const toggle = el("button", { class: "cite", type: "button", onclick: () => {
      const showingAll = toggle.dataset.all === "1";
      holder.replaceChildren(evidenceTable(showingAll ? some : all, cited, planted));
      toggle.dataset.all = showingAll ? "0" : "1";
      toggle.textContent = showingAll ? `Show all ${all.length} rows` : "Show cited rows only";
    } }, `Show all ${all.length} rows`);
    box.replaceChildren(
      el("h2", {}, `Evidence: tool call #${call.seq} ${call.tool} (${call.ranker})`),
      kv([["arguments", el("span", { class: "mono" }, JSON.stringify(call.args))],
        ["snapshot", el("span", { class: "mono" }, snap.id)],
        ["rows", `${snap.rows.length}${snap.truncated ? " (truncated at the row cap)" : ""}; ${rowIds.length} cited by this claim, highlighted`],
        planted.size ? ["planted rows", "marked with a red edge (injected text that names a false cause)"] : null].filter(Boolean)),
      el("p", { class: "muted" }, "Rows are shown exactly as stored, as text. Log bodies and attributes are untrusted input."),
      some.length && some.length < all.length ? toggle : null,
      holder);
  }).catch((e) => box.replaceChildren(el("p", {}, "Could not load the snapshot: " + e.message)));
}

function claimView(inv, c) {
  const calls = new Map(inv.tool_calls.map((t) => [t.seq, t]));
  const params = Object.fromEntries(Object.entries(c.params).filter(([k]) => k !== "type" && k !== "cites"));
  return el("div", { class: "claim" },
    badge(c.result), " ", el("strong", {}, c.type), " ", el("span", { class: "mono" }, JSON.stringify(params)),
    c.reason ? el("div", { class: "reason" }, "Verifier: ", c.reason) : el("div", { class: "muted" }, "Verifier: recomputed from the cited rows and passed."),
    el("div", {}, c.cites.map((ct) => {
      const call = calls.get(ct.seq);
      if (!call || !call.snapshot) return el("span", { class: "badge plain" }, `call #${ct.seq} (no snapshot)`);
      return el("button", { class: "cite", type: "button", onclick: () => openEvidence(inv, call, ct.row_ids) },
        `call #${ct.seq} ${call.tool}: ${ct.row_ids.length} rows cited`);
    })));
}

function hypothesisView(inv, h) {
  return el("div", { class: "hyp" },
    el("div", { class: "title" }, `#${h.rank} ${h.service} / ${h.kind} `, badge(h.status)),
    el("div", { class: "muted" }, `${h.role.replaceAll("_", " ")}, score ${h.score.toFixed(3)}`),
    h.narrative ? el("div", { class: "narrative" }, el("div", { class: "label" }, "Unverified explanation"), h.narrative) : null,
    h.claims.map((c) => claimView(inv, c)));
}

function rankerColumn(inv, ranker) {
  const hs = inv.hypotheses.filter((h) => h.ranker === ranker);
  const outcome = inv.results[ranker];
  return el("div", {},
    el("h3", {}, ranker === "agent" ? "LLM agent" : "Deterministic baseline", " ",
      outcome ? badge("plain", SHORT[outcome]) : badge("plain", "no result")),
    hs.length ? hs.map((h) => hypothesisView(inv, h)) : el("p", { class: "muted" }, "No hypotheses."));
}

async function investigationPage(main) {
  const fid = new URLSearchParams(location.search).get("f");
  if (!fid || !/^[a-z0-9_]+$/.test(fid)) {
    fill(main, el("p", {}, "No such investigation. "), el("a", { href: "index.html" }, "All investigations"));
    return;
  }
  const inv = await load(`data/inv/${fid}.json`);
  const L = inv.label;
  document.title = `${fid} · Sentry-RCA`;
  const timeline = inv.timeline_snapshot ? await load(`data/snap/${encodeURIComponent(inv.timeline_snapshot)}.json`) : null;
  const plantedSeen = inv.planted_in_agent_results;
  fill(main, 
    el("p", {}, el("a", { href: "index.html" }, "All investigations")),
    el("h1", {}, fid),
    inv.showcase ? el("p", { class: "note" }, inv.showcase) : null,
    el("div", { class: "panel" }, kv([
      ["split", L.split + (L.split === "test" ? " (held out: never used to build the baseline or the prompt)" : "")],
      ["scenario", L.scenario],
      ["labelled cause", L.root_cause ? `${L.root_cause.service} / ${L.root_cause.cause_kind}` : "none (no fault)"],
      ["expected outcome", L.expected_outcome],
      ["shown outcome", `${inv.outcome} (from the ${inv.shown_ranker}, status ${inv.status})`],
      ["incident", `${inv.incident.service}, first anomaly ${inv.incident.first_anomaly_at}`],
      ["scope", `${(inv.scope.services || []).join(", ")}; ${inv.scope.start} to ${inv.scope.end}`],
      ["confounders", L.confounders && L.confounders.length ? L.confounders.map((c) => `${c.kind} on ${c.service}`).join("; ") : "none"],
      inv.budget.agent ? ["agent budget used", `${inv.budget.agent.tool_calls} tool calls, ` +
        `${Math.round((inv.budget.agent.tokens_in + inv.budget.agent.tokens_out) / 1000)}k tokens, ${inv.llm_exchanges} model calls ` +
        `(${inv.budget.agent.repairs} repair), ${(inv.model_ms / 1000).toFixed(0)} s recorded model time`] : null,
      L.planted_injection ? ["injection", `${L.planted_row_ids.length} planted log rows naming a false cause; ` +
        (plantedSeen.length ? `returned to the agent by its calls ${plantedSeen.map((s) => "#" + s).join(", ")}` : "never returned to the agent's queries")] : null,
    ].filter(Boolean))),
    L.notes ? el("p", { class: "muted" }, "Label note: ", L.notes) : null,
    el("h2", {}, "Timeline"),
    timeline ? table(["#", "kind", "time", "detail"], timeline.rows.map((r, i) => [String(i + 1), r.kind, r.ts,
      el("pre", {}, JSON.stringify(Object.fromEntries(Object.entries(r).filter(([k]) => !["kind", "ts", "row_id"].includes(k)))))]))
      : el("p", { class: "muted" }, "No timeline call."),
    el("h2", {}, "Hypotheses, side by side"),
    el("p", { class: "muted" }, "Every claim was recomputed by the deterministic verifier from the rows it cites. A rejected hypothesis is never shown as a finding."),
    el("div", { class: "cols" }, rankerColumn(inv, "baseline"), rankerColumn(inv, "agent")),
    el("section", { id: "evidence", class: "evidence" }),
    L.out_of_scope_evidence.length || inv.scope_rejections.length ? [
      el("h2", {}, "Out-of-scope evidence"),
      el("p", {}, "True evidence the label records but no ranker may cite, because its service is outside the investigation's scope (§5.2)."),
      table(["claim", "service", "metric", "why out of scope"], L.out_of_scope_evidence.map((e) => [e.type, e.service, e.metric || "", e.reason || ""])),
      inv.scope_rejections.length ? [el("h3", {}, "The scope check rejecting it"),
        table(["tool", "arguments", "decision", "reason"], inv.scope_rejections.map((t) => [t.tool, el("pre", {}, JSON.stringify(t.args)), badge(t.decision), t.reason || ""]))] : null,
    ] : null,
    el("h2", {}, `Audit: all ${inv.tool_calls.length} tool calls`),
    table(["#", "ranker", "tool", "scope", "rows", "ms", "arguments", "reason"], inv.tool_calls.map((t) => [String(t.seq), t.ranker, t.tool,
      badge(t.decision), t.rows === null ? "" : String(t.rows), t.ms === null ? "" : String(t.ms), el("pre", {}, JSON.stringify(t.args)), t.reason || ""])));
}

// ---------- evaluation ----------

const diag = (m) => OUTCOMES.reduce((n, o) => n + ((m[o] || {})[o] || 0), 0);

function confusion(m) {
  return table(["expected \\ given", ...OUTCOMES.map((o) => SHORT[o])], OUTCOMES.map((o) => [SHORT[o], ...OUTCOMES.map((g) => String((m[o] || {})[g] || 0))]));
}

function splitSection(name, s) {
  const b = s.baseline_same_investigations;
  const p = s.paired;
  const rows = [
    ["top-1 judged", pct(s.top1.mean), pct(b.top1.mean)],
    ["top-1 exact (service, kind)", pct(s.top1_exact.mean), pct(b.top1_exact.mean)],
    ["top-1 service only", pct(s.top1_service.mean), pct(b.top1_service.mean)],
    ["top-3 judged", pct(s.top3.mean), pct(b.top3.mean)],
    ["outcome correct", `${s.agent.outcome_correct} / ${s.fixtures}`, `${diag(b.confusion)} / ${s.fixtures}`],
    [`clean fixtures (${s.clean.fixtures}), top-1`, pct(s.clean.top1.mean), pct(b.clean.top1.mean)],
    [`confounded fixtures (${s.confounded.fixtures}), top-1`, pct(s.confounded.top1.mean), pct(b.confounded.top1.mean)],
  ];
  const t = p.top1_tally;
  return el("section", {},
    el("h2", {}, `${name === "test" ? "Test (held out)" : "Dev"}: ${s.fixtures} fixtures, one run each`),
    table(["", "agent", "baseline"], rows),
    el("h3", {}, "Paired by fixture, top-1 judged"),
    el("p", {}, `Agent ${t.win || 0} wins, ${t.loss || 0} losses, ${t.tie || 0} ties (exact sign test p = ${p.top1_sign_test_p === null ? "—" : p.top1_sign_test_p.toFixed(3)}, descriptive only).`),
    table(["fixture", "agent rank 1", "baseline rank 1", "top-1", "outcome"], Object.entries(p.per_fixture).map(([fid, r]) =>
      [invLink(fid), cause(r.agent_rank1[0]), cause(r.baseline_rank1[0]), badge(r.top1.verdict), badge(r.outcome.verdict)])),
    el("div", { class: "cols" },
      el("div", {}, el("h3", {}, "Outcome confusion, agent (shown result)"), confusion(s.confusion)),
      el("div", {}, el("h3", {}, "Outcome confusion, baseline"), confusion(b.confusion))),
    el("h3", {}, "Verifier"),
    kv([["agent hypotheses", `${s.rejections_agent.hypotheses.passed || 0} verified, ${s.rejections_agent.hypotheses.rejected || 0} rejected`],
      ["rejection reasons", el("ul", {}, Object.entries(s.rejections_agent.failed_claims_by_type).flatMap(([type, rs]) =>
        Object.entries(rs).map(([why, n]) => el("li", {}, `${type}: ${why} (${n})`))))],
      ["gold claims rejected", String(s.gold_rejected.length ?? s.gold_rejected)],
      ["agent tokens per run, median / max", `${Math.round(s.agent.tokens.median / 1000)}k / ${Math.round(s.agent.tokens.max / 1000)}k`],
      ["degraded runs / parse failures", `${s.agent.degraded} / ${s.agent.parse_failures}`]]));
}

async function evalPage(main) {
  const ev = await load("data/eval.json");
  fill(main, 
    el("h1", {}, "Evaluation: agent against baseline"),
    el("p", { class: "lead" }, headline(ev)),
    el("p", { class: "note" }, "Noise: every agent number here is one run per fixture (the free tier allowed no more). On dev, identical " +
      "repeated runs changed their top answer in 4 of 6 pairs, so no difference of one or two fixtures is meaningful. Under the " +
      "rule registered before the test run the agent loses on test (losses − wins = 3, mean lower), exactly at the threshold. ",
      el("a", { href: REPO + "docs/analysis-plan-phase3.md" }, "Analysis plan"), ", ",
      el("a", { href: REPO + "docs/report-phase3.md" }, "Phase 3 report"), "."),
    el("p", { class: "muted" }, `Agent: ${ev.model}, budget ${JSON.stringify(ev.budget)}. `, provenance(ev).textContent),
    ["test", "dev"].filter((n) => ev.splits[n]).map((n) => splitSection(n, ev.splits[n])));
}

document.addEventListener("DOMContentLoaded", () => {
  const main = document.getElementById("main");
  const page = { index: indexPage, investigation: investigationPage, eval: evalPage }[document.body.dataset.page];
  page(main).catch((e) => fill(main, el("p", {}, "Could not load the recorded data: " + e.message)));
});
