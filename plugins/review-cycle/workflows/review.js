export const meta = {
  name: "round",
  description: "One review-cycle round: parallel finders, blind verifiers, tie-break and sweep.",
  whenToUse: "Started by the review-cycle skill with arguments from review-cycle-state.",
  phases: ["Find", "Verify", "Tie-break", "Sweep"],
};

// Orchestrates one review round. Input: `args` (ST-3, object or JSON string) produced by
// `review-cycle-state`. Output: the ST-11 result object; `merge` validates it, including the
// checksum. The script decides nothing about keeping findings: it returns every verdict.
// A bare or malformed invocation returns `{started: false, reason, next}` and starts no agent.

const PROVENANCE = "review-cycle/workflows/review.js";
const NEXT_RUN_SKILL = "Run /review-cycle; this workflow needs arguments from review-cycle-state.";
const NEXT_MODEL = "Pass --model to /review-cycle, or use a level whose verifier models are not haiku.";
// Largest batch a verifier gets; keeps one agent's reading and reply bounded.
const BATCH_MAX = 8;
const DEDUP_SNIPPET_CHARS = 120;
const CODE_CATEGORIES = [
  "intent", "logic", "edge-case", "concurrency", "error-handling", "rule", "stale", "regression",
  "contract",
];
const DOC_CATEGORIES = [
  "ambiguity", "contradiction", "gap", "code-claim", "unneeded", "inconsistency",
];
const FINDER_FIELDS = [
  "category", "class", "path", "line", "symbol", "snippet", "claim", "trigger", "evidence",
  "expected", "broken_by", "scope_note",
];

const logs = [];
const stats = { agents_started: 0, agents_returned: 0, finders_null: 0, verifiers_null: 0 };

const STR = { type: "string" };

const VERIFIER_SCHEMA = {
  type: "object",
  properties: {
    verdicts: {
      type: "array",
      items: {
        type: "object",
        properties: {
          item_id: STR,
          holds: { type: "boolean" },
          severity: { type: "string", enum: ["important", "nit", ""] },
          reason: STR,
          evidence: STR,
          trigger: STR,
          prevented_by: STR,
          needs_decision: {
            type: "object",
            properties: {
              criterion: { type: "integer", enum: [0, 1, 2, 3] },
              before: STR,
              after: STR,
              intent_quote: STR,
              options: {
                type: "array",
                items: {
                  type: "object",
                  properties: { label: STR, observable: STR },
                  required: ["label", "observable"],
                },
              },
            },
            required: ["criterion", "before", "after", "intent_quote", "options"],
          },
        },
        required: [
          "item_id", "holds", "severity", "reason", "evidence", "trigger", "prevented_by",
          "needs_decision",
        ],
      },
    },
  },
  required: ["verdicts"],
};

// Checksum (WF-13). Must stay a plain declaration with no outside references: the test harness
// extracts it by name and runs it alone.
function fnv1a32(s) {
  let h = 0x811c9dc5;
  for (const ch of s) {
    h ^= ch.codePointAt(0);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

function text(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "1" : "0";
  return String(value);
}

function record(fields) {
  return fields.map(text).join("\x1f") + "\x1e";
}

function checksumText(result) {
  const parts = [];
  for (const c of result.candidates) {
    parts.push(record([
      "C", c.id, c.category, c.class, c.path, c.line, c.symbol, c.snippet, c.claim, c.trigger,
      c.evidence, c.expected, c.lens, c.finder, c.broken_by.path, c.broken_by.line, c.scope_note,
      c.of_class,
    ]));
  }
  for (const v of result.verdicts) {
    const nd = v.needs_decision;
    const options = nd.options.map((o) => o.label + "\x1d" + o.observable).join("\x1c");
    parts.push(record([
      "V", v.item_id, v.kind, v.role, v.slot, v.model, v.batch, v.holds, v.severity, v.reason,
      v.evidence, v.trigger, v.prevented_by, nd.criterion, nd.before, nd.after, nd.intent_quote,
      options,
    ]));
  }
  for (const d of result.dropped) parts.push(record(["D", d.id, d.dup_of]));
  for (const m of result.missing) parts.push(record(["M", m.item_id, m.role, m.slot]));
  return parts.join("");
}

function note(message) {
  logs.push(message);
  log(message);
}

function notStarted(reason, next) {
  return { provenance: PROVENANCE, v: 1, started: false, reason, next };
}

// --- Arguments (WF-2) ---------------------------------------------------------------------

function isAbsolute(p) {
  return typeof p === "string" && (p.startsWith("/") || /^[A-Za-z]:[\\/]/.test(p));
}

function isText(v) {
  return typeof v === "string" && v !== "";
}

function isOptionalText(v) {
  return v === undefined || v === null || typeof v === "string";
}

function isOptionalTextArray(v) {
  return v === undefined || v === null || (Array.isArray(v) && v.every(isText));
}

/** Returns the normalised args, or null when a required field is missing or malformed. */
function normaliseArgs(a) {
  const textFields = ["plan_id", "plan", "repo_root", "level", "lens_file", "verify_dir", "state_dir",
    "intent_file", "recheck_file"];
  if (!textFields.every((k) => isText(a[k]))) return null;
  if (a.mode !== "code" && a.mode !== "document") return null;
  const pathFields = ["plan", "repo_root", "lens_file", "verify_dir", "state_dir", "intent_file", "recheck_file"];
  if (!pathFields.every((k) => isAbsolute(a[k]))) return null;
  if (!Array.isArray(a.finders) || a.finders.length === 0) return null;
  const finderOk = (f) => f && isText(f.lens) && (f.order === "forward" || f.order === "reverse");
  if (!a.finders.every(finderOk)) return null;
  if (!Array.isArray(a.votes) || a.votes.length === 0 || !a.votes.every(isText)) return null;
  if (!isOptionalText(a.tiebreak) || !isOptionalText(a.sweep)) return null;
  if (!isOptionalText(a.finder_model) || !isOptionalText(a.depth)) return null;
  if (!isOptionalText(a.verifier_section)) return null;
  if (!isOptionalText(a.focus)) return null;
  if (!isOptionalTextArray(a.paths)) return null;
  if (a.review_md !== undefined && a.review_md !== null && !isAbsolute(a.review_md)) return null;
  const rules = a.rules_files ?? [];
  if (!Array.isArray(rules) || !rules.every(isAbsolute)) return null;
  const recheck = a.recheck ?? [];
  if (!Array.isArray(recheck) || !recheck.every((r) => r && isText(r.id) && isText(r.path))) {
    return null;
  }
  return {
    ...a,
    tiebreak: a.tiebreak || null,
    sweep: a.sweep || null,
    focus: a.focus || null,
    paths: a.paths ?? null,
    review_md: a.review_md || null,
    rules_files: rules,
    recheck,
    depth: a.depth || "",
    verifier_section: a.verifier_section || "## Verifier",
    model_override: a.model_override === true,
  };
}

/** Returns {args} when usable, else {reason} (`no-args` or `bad-args`). */
function parseArgs(raw) {
  let value = raw;
  if (typeof value === "string") {
    if (value.trim() === "") return { reason: "no-args" };
    try {
      value = JSON.parse(value);
    } catch {
      return { reason: "bad-args" };
    }
  }
  if (value === undefined || value === null) return { reason: "no-args" };
  if (typeof value !== "object" || Array.isArray(value)) return { reason: "bad-args" };
  if (Object.keys(value).length === 0) return { reason: "no-args" };
  const normalised = normaliseArgs(value);
  return normalised ? { args: normalised } : { reason: "bad-args" };
}

// --- Candidates ---------------------------------------------------------------------------

function norm(s) {
  return s
    .split("\n")
    .map((line) => line.trim().replace(/\s+/g, " "))
    .filter((line) => line !== "")
    .join("\n");
}

// The key has no category: two lenses labelling one bug differently is the common case.
function dedupKey(c) {
  return c.path + "|" + c.symbol + "|" + norm(c.snippet).slice(0, DEDUP_SNIPPET_CHARS);
}

function str(v) {
  return typeof v === "string" ? v : "";
}

function toCandidate(raw, id, lens, finder, ofClass) {
  const broken = raw.broken_by && typeof raw.broken_by === "object" ? raw.broken_by : {};
  const natural = (n) => (Number.isInteger(n) && n >= 0 ? n : 0);
  return {
    id,
    category: str(raw.category),
    class: str(raw.class),
    path: str(raw.path),
    line: natural(raw.line),
    symbol: str(raw.symbol),
    snippet: str(raw.snippet),
    claim: str(raw.claim),
    trigger: str(raw.trigger),
    evidence: str(raw.evidence),
    expected: str(raw.expected),
    broken_by: { path: str(broken.path), line: natural(broken.line) },
    scope_note: raw.scope_note === "outside-goal" ? "outside-goal" : "",
    lens,
    finder,
    of_class: ofClass,
  };
}

/** Why a finder or sweep item is unusable (ST-9), or null. Such items get no id. */
function itemProblem(c, mode) {
  const categories = mode === "document" ? DOC_CATEGORIES : CODE_CATEGORIES;
  if (c.path === "") return "empty path";
  if (c.claim === "") return "empty claim";
  if (!categories.includes(c.category)) return `category "${c.category}" not allowed in ${mode} mode`;
  return null;
}

function finderSchema(mode, withOfClass) {
  const categories = mode === "document" ? DOC_CATEGORIES : CODE_CATEGORIES;
  const properties = {
    category: { type: "string", enum: categories },
    class: STR,
    path: STR,
    line: { type: "integer", minimum: 0 },
    symbol: STR,
    snippet: STR,
    claim: STR,
    trigger: STR,
    evidence: STR,
    expected: STR,
    broken_by: {
      type: "object",
      properties: { path: STR, line: { type: "integer", minimum: 0 } },
      required: ["path", "line"],
    },
    scope_note: { type: "string", enum: ["", "outside-goal"] },
  };
  const required = [...FINDER_FIELDS];
  if (withOfClass) {
    properties.of_class = STR;
    required.push("of_class");
  }
  return {
    type: "object",
    properties: { findings: { type: "array", items: { type: "object", properties, required } } },
    required: ["findings"],
  };
}

function agentOptions(label, phaseName, schema, model) {
  const opts = { label, phase: phaseName, schema };
  if (model) opts.model = model;
  return opts;
}

async function call(prompt, opts) {
  stats.agents_started += 1;
  const reply = await agent(prompt, opts);
  if (reply === null || reply === undefined) return null;
  stats.agents_returned += 1;
  return reply;
}

function rootLine(a) {
  return `Repository root: ${a.repo_root}. Every path below is relative to it.`;
}

/** The owner's focus line (RPT-19): finder and sweep prompts only, never verifiers. */
function focusLine(a) {
  return `Owner's focus (look harder here; still report every other real problem): ${JSON.stringify(a.focus)}`;
}

/** The sweep's search-scope sentence: the whole repository, or just `--path`'s paths (RPT-20(c)). */
function sweepScopeLine(a) {
  if (a.paths && a.paths.length > 0) {
    return `Verified findings belong to the defect classes below. Search only within ${JSON.stringify(a.paths)}, not the whole repository, for further instances of exactly these classes.`;
  }
  return "Verified findings belong to the defect classes below. Search the WHOLE repository, not only the plan scope, for further instances of exactly these classes.";
}

function finderPrompt(a, finder) {
  const subject = a.mode === "document" ? "document" : "code";
  const lines = [
    `You are a finder in a ${subject} review round.`,
    rootLine(a),
    `Plan file: ${a.plan}. Read it first: scope, no-repeat list (known[]), rules files, intent.`,
    `Your lens is "${finder.lens}". Read "## Finder rules" and then "## Lens: ${finder.lens}" in ${a.lens_file}, and follow them.`,
  ];
  if (finder.order === "reverse") {
    lines.push("Take the in-scope files (or sections) in reverse order, last one first.");
  }
  if (a.focus) lines.push(focusLine(a));
  lines.push(
    "This task is read-only: use Read, Grep, Glob, read-only git and read-only gh; never edit files, never run code or tests.",
    "Report only findings within the plan scope. A defect in unchanged code that you meet while tracing the change may be reported (it is classified Pre-existing). Skip everything in the no-repeat list.",
    "Reply with the findings list; no findings means an empty list.",
  );
  return lines.join("\n");
}

async function runFinders(a) {
  const replies = await parallel(a.finders.map((finder, i) => () => {
    const label = `find:${finder.lens}${finder.order === "reverse" ? ":rev" : ""}`;
    const opts = agentOptions(label, "Find", finderSchema(a.mode, false), a.finder_model);
    return call(finderPrompt(a, finder), opts);
  }));
  const candidates = [];
  const dropped = [];
  const seen = new Map();
  replies.forEach((reply, i) => {
    const finder = a.finders[i];
    if (!reply || !Array.isArray(reply.findings)) {
      stats.finders_null += 1;
      note(`finder ${i + 1} (${finder.lens}) returned nothing usable`);
      return;
    }
    let kept = 0;
    reply.findings.forEach((raw, k) => {
      if (!raw || typeof raw !== "object") {
        note(`finder ${i + 1} item ${k + 1} is not an object; dropped`);
        return;
      }
      const candidate = toCandidate(raw, `N${i + 1}.${kept + 1}`, finder.lens, i + 1, "");
      const problem = itemProblem(candidate, a.mode);
      if (problem) {
        note(`finder ${i + 1} item ${k + 1} dropped: ${problem}`);
        return;
      }
      kept += 1;
      const id = candidate.id;
      if (a.mode === "code") {
        const key = dedupKey(candidate);
        if (seen.has(key)) {
          dropped.push({ id, dup_of: seen.get(key) });
          note(`${id} dropped as duplicate of ${seen.get(key)}`);
          return;
        }
        seen.set(key, id);
      }
      candidates.push(candidate);
    });
  });
  return { candidates, dropped };
}

// --- Verification -------------------------------------------------------------------------

/** Verifier-visible view of a candidate: the only fields a verifier may see (WF-8). */
function blind(c) {
  return { item_id: c.id, path: c.path, line: c.line, symbol: c.symbol, snippet: c.snippet, claim: c.claim };
}

/** Groups items by path (sorted), splits groups over the batch size, packs first-fit. */
function makeBatches(items, firstNumber) {
  const byPath = new Map();
  for (const it of items) {
    if (!byPath.has(it.path)) byPath.set(it.path, []);
    byPath.get(it.path).push(it);
  }
  const groups = [];
  for (const path of [...byPath.keys()].sort()) {
    const members = byPath.get(path);
    for (let i = 0; i < members.length; i += BATCH_MAX) groups.push(members.slice(i, i + BATCH_MAX));
  }
  const batches = [];
  for (const group of groups) {
    let target = batches.find((b) => b.items.length + group.length <= BATCH_MAX);
    if (!target) {
      target = { n: firstNumber + batches.length, items: [] };
      batches.push(target);
    }
    target.items.push(...group);
  }
  return batches;
}

function verifierPrompt(a, items, role) {
  const fresh = items.filter((it) => it.kind === "new");
  const recheck = items.filter((it) => it.kind === "recheck");
  const lines = [
    role === "tiebreak"
      ? "You are the tie-break verifier. Judge each item independently from the code."
      : "You are an independent verifier.",
    rootLine(a),
    "Your objective is to refute each item below; confirm one only after proving it yourself from what you read.",
    "Allowed tools: Read, Grep, Glob and read-only git (log, blame, show, diff). Never run code, tests, builds or scripts.",
    `Depth: ${a.depth}`,
    `Read the section "${a.verifier_section}" in ${a.lens_file} (the lens file) and follow it.`,
  ];
  if (a.rules_files.length > 0) lines.push(`Project rules files: ${a.rules_files.join(", ")}`);
  if (a.review_md) lines.push(`REVIEW.md copy from the base branch: ${a.review_md}`);
  lines.push(
    `Stated intent file: ${a.intent_file}`,
    `Read only the repository files, the lens file named above, and the files in ${a.verify_dir}; do not open anything else under ${a.state_dir}.`,
  );
  if (fresh.length > 0) {
    lines.push("Items to verify (one JSON object per line):");
    for (const it of fresh) lines.push(JSON.stringify(blind(it.candidate)));
  }
  if (recheck.length > 0) {
    lines.push(`Re-check items: read each one's entry in ${a.recheck_file} (entries are matched by their "id" field):`);
    for (const it of recheck) lines.push(JSON.stringify({ item_id: it.id, path: it.path }));
  }
  lines.push("Return exactly one verdict per listed item_id.");
  return lines.join("\n");
}

function normaliseVerdict(row, task, item) {
  const nd = row.needs_decision && typeof row.needs_decision === "object" ? row.needs_decision : {};
  const options = Array.isArray(nd.options) ? nd.options : [];
  return {
    item_id: item.id,
    kind: item.kind,
    role: task.role,
    slot: task.slot,
    model: task.model,
    batch: task.batch,
    holds: row.holds === true,
    severity: row.severity === "important" || row.severity === "nit" ? row.severity : "",
    reason: str(row.reason),
    evidence: str(row.evidence),
    trigger: str(row.trigger),
    prevented_by: str(row.prevented_by),
    needs_decision: {
      criterion: [0, 1, 2, 3].includes(nd.criterion) ? nd.criterion : 0,
      before: str(nd.before),
      after: str(nd.after),
      intent_quote: str(nd.intent_quote),
      options: options.map((o) => ({ label: str(o && o.label), observable: str(o && o.observable) })),
    },
  };
}

/** Moves one agent's reply into `verdicts`; every expected row not returned goes to `missing`. */
function collect(task, reply, verdicts, missing) {
  const byId = new Map(task.items.map((it) => [it.id, it]));
  const seen = new Set();
  if (reply && Array.isArray(reply.verdicts)) {
    for (const row of reply.verdicts) {
      const id = row && row.item_id;
      if (!byId.has(id)) {
        note(`${task.label}: verdict for ${text(id)} is not in this batch; dropped`);
      } else if (seen.has(id)) {
        note(`${task.label}: duplicate verdict for ${id}; first kept`);
      } else {
        seen.add(id);
        verdicts.push(normaliseVerdict(row, task, byId.get(id)));
      }
    }
  } else {
    stats.verifiers_null += 1;
    note(`${task.label} returned nothing usable`);
  }
  for (const it of task.items) {
    if (seen.has(it.id)) continue;
    if (reply && Array.isArray(reply.verdicts)) note(`${task.label}: no verdict for ${it.id}`);
    missing.push({ item_id: it.id, role: task.role, slot: task.slot });
  }
}

async function runTasks(a, tasks, phaseName, verdicts, missing) {
  const replies = await parallel(tasks.map((task) => () => {
    const opts = agentOptions(task.label, phaseName, VERIFIER_SCHEMA, task.model);
    return call(verifierPrompt(a, task.items, task.role), opts);
  }));
  tasks.forEach((task, i) => collect(task, replies[i], verdicts, missing));
}

function voteTasks(a, batches) {
  const tasks = [];
  for (const batch of batches) {
    a.votes.forEach((model, slot) => {
      tasks.push({
        role: "vote", slot, model, batch: batch.n, items: batch.items,
        label: `verify:b${batch.n}:${slot}:${model}`,
      });
    });
  }
  return tasks;
}

/** Items with at least one holding vote that did not hold on every slot (missing = not holding). */
function splitItems(items, verdicts, voteCount) {
  return items.filter((it) => {
    const holds = new Array(voteCount).fill(false);
    for (const v of verdicts) {
      if (v.item_id === it.id && v.role === "vote") holds[v.slot] = v.holds;
    }
    return holds.some((h) => h) && !holds.every((h) => h);
  });
}

function holdingVotes(id, verdicts) {
  return verdicts.filter((v) => v.item_id === id && v.role === "vote" && v.holds).length;
}

// --- Sweep (WF-10) ------------------------------------------------------------------------

function sweepPrompt(a, groups) {
  const lines = [
    `You are a sweep finder in a ${a.mode === "document" ? "document" : "code"} review round.`,
    rootLine(a),
    `Plan file: ${a.plan}. Read it for the rules files, the intent and the no-repeat list (known[]).`,
    sweepScopeLine(a),
    "Defect classes, with the instances already reported (do not report these again):",
  ];
  for (const g of groups) {
    lines.push(`- ${g.cls}`);
    for (const c of g.known) lines.push(`    already reported: ${c.path}:${c.line} ${c.symbol}`.trimEnd());
  }
  if (a.focus) lines.push(focusLine(a));
  lines.push(
    `Field and evidence rules: "## Finder rules" in ${a.lens_file}. Report only instances you proved from code you read in this run.`,
    "Each item follows the findings schema; set of_class to the class from the list above that the item is an instance of.",
    "This task is read-only: use Read, Grep, Glob and read-only git; never edit files, never run code or tests.",
    "Also skip everything in the no-repeat list. No further instances means an empty list.",
  );
  return lines.join("\n");
}

async function runSweep(a, candidates, verdicts) {
  const classes = [];
  for (const c of candidates) {
    if (c.class && holdingVotes(c.id, verdicts) >= 2 && !classes.includes(c.class)) classes.push(c.class);
  }
  if (classes.length === 0) {
    note("sweep skipped: no class with at least 2 holding votes");
    return { hits: [], dropped: [] };
  }
  const groups = classes.map((cls) => ({ cls, known: candidates.filter((c) => c.class === cls) }));
  const opts = agentOptions("sweep", "Sweep", finderSchema(a.mode, true), a.sweep);
  let reply = null;
  try {
    reply = await call(sweepPrompt(a, groups), opts);
  } catch {
    reply = null;
  }
  if (!reply || !Array.isArray(reply.findings)) {
    note("sweep agent returned nothing usable");
    return { hits: [], dropped: [] };
  }
  const seen = new Map(candidates.map((c) => [dedupKey(c), c.id]));
  const hits = [];
  const dropped = [];
  reply.findings.forEach((raw, k) => {
    if (!raw || typeof raw !== "object") {
      note(`sweep item ${k + 1} is not an object; dropped`);
      return;
    }
    const probe = toCandidate(raw, "", "sweep", 0, str(raw.of_class));
    const problem = itemProblem(probe, a.mode);
    if (problem) {
      note(`sweep item ${k + 1} dropped: ${problem}`);
      return;
    }
    const key = dedupKey(probe);
    if (seen.has(key)) {
      const id = `SD${k + 1}`;
      dropped.push({ id, dup_of: seen.get(key) });
      note(`sweep item ${id} dropped as duplicate of ${seen.get(key)}`);
      return;
    }
    probe.id = `S${hits.length + 1}`;
    seen.set(key, probe.id);
    hits.push(probe);
  });
  return { hits, dropped };
}

// --- Round --------------------------------------------------------------------------------

function compare(x, y) {
  return x < y ? -1 : x > y ? 1 : 0;
}

async function runRound(a) {
  const found = await runFinders(a);
  const candidates = found.candidates;
  const dropped = found.dropped;
  const verdicts = [];
  const missing = [];

  const items = [
    ...candidates.map((c) => ({ id: c.id, kind: "new", path: c.path, candidate: c })),
    ...a.recheck.map((r) => ({ id: r.id, kind: "recheck", path: r.path })),
  ];
  const batches = makeBatches(items, 1);
  let nextBatch = batches.length + 1;
  await runTasks(a, voteTasks(a, batches), "Verify", verdicts, missing);

  if (a.tiebreak) {
    const tied = makeBatches(splitItems(items, verdicts, a.votes.length), nextBatch);
    nextBatch += tied.length;
    const tasks = tied.map((b) => ({
      role: "tiebreak", slot: 0, model: a.tiebreak, batch: b.n, items: b.items,
      label: `tiebreak:b${b.n}:${a.tiebreak}`,
    }));
    await runTasks(a, tasks, "Tie-break", verdicts, missing);
  }

  if (a.sweep) {
    const swept = await runSweep(a, candidates, verdicts);
    candidates.push(...swept.hits);
    dropped.push(...swept.dropped);
    const sweepItems = swept.hits.map((c) => ({ id: c.id, kind: "new", path: c.path, candidate: c }));
    await runTasks(a, voteTasks(a, makeBatches(sweepItems, nextBatch)), "Sweep", verdicts, missing);
  }

  verdicts.sort((x, y) =>
    compare(x.batch, y.batch) || compare(x.role, y.role) || compare(x.slot, y.slot) ||
    compare(x.item_id, y.item_id));

  const result = {
    provenance: PROVENANCE,
    v: 1,
    started: true,
    plan_id: a.plan_id,
    echo: {
      level: a.level,
      mode: a.mode,
      finders: a.finders,
      votes: a.votes,
      tiebreak: a.tiebreak,
      recheck_ids: a.recheck.map((r) => r.id),
    },
    candidates,
    dropped,
    verdicts,
    missing,
    stats,
    log: logs,
    checksum: "",
  };
  result.checksum = fnv1a32(checksumText(result));
  return result;
}

const parsed = parseArgs(args);
if (!parsed.args) return notStarted(parsed.reason, NEXT_RUN_SKILL);
if (!parsed.args.model_override) {
  const verifierModels = [...parsed.args.votes, parsed.args.tiebreak || ""];
  if (verifierModels.some((m) => /haiku/i.test(m))) return notStarted("haiku-verifier", NEXT_MODEL);
}
return await runRound(parsed.args);
