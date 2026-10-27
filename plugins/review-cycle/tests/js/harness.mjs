// Runs workflows/review.js against a scenario with fake runtime hooks.
// Usage: node harness.mjs <path to review.js> < scenario.json
//
// Scenario (all keys optional):
//   args            value passed as `args`; key absent => undefined
//   find            { "<finder label>": {findings: [...]} | null }; absent label => {findings: []}
//   sweep           reply of the `sweep` agent (object | null); absent => {findings: []}
//   verdicts        { "<item id>": { "vote:<slot>" | "tiebreak:0": spec } }
//                   spec = "omit" | {...verdict fields; "_dup": true repeats the row flipped}
//   default_spec    spec for unlisted (item, role, slot); default {holds: true}
//   throw_calls     [{kind, label?, slot?}]: matching agents throw (parallel turns that into null)
//   null_calls      [{kind, slot?}]: matching verify/tiebreak agents return null
//   (a reply lacking a key listed in opts.schema.required becomes null, as the runtime does)
//   extra_rows      [{for_id, kind, slot, row}]: row appended to replies whose prompt lists for_id
//   probe_fnv       [strings]: skip the script, return fnv1a32 of each (declared `function fnv1a32`;
//                   `fnv: null` when the script has none)
// Output (stdout): { result, calls, logs, unclassified } or { fnv } for probe_fnv.
// Each recorded call: { prompt, opts, label, kind, slot, ids }.
import { readFileSync } from "node:fs";

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

const source = readFileSync(process.argv[2], "utf8").replace(/^export const meta/m, "const meta");
const scenario = JSON.parse(readFileSync(0, "utf8") || "{}");
const clone = (v) => (v === undefined ? v : JSON.parse(JSON.stringify(v)));

function extractFunction(src, name) {
  const m = new RegExp(`function\\s+${name}\\s*\\(`).exec(src);
  if (!m) return null;
  let depth = 0;
  let end = src.indexOf("{", m.index);
  for (; end < src.length; end++) {
    if (src[end] === "{") depth++;
    else if (src[end] === "}" && --depth === 0) break;
  }
  return src.slice(m.index, end + 1);
}

if (scenario.probe_fnv) {
  const code = extractFunction(source, "fnv1a32");
  if (!code) {
    process.stdout.write(JSON.stringify({ fnv: null, unclassified: [] }));
    process.exit(0);
  }
  const fnv = new Function(`${code}; return fnv1a32;`)();
  process.stdout.write(JSON.stringify({ fnv: scenario.probe_fnv.map((s) => fnv(s)) }));
  process.exit(0);
}

const calls = [];
const logs = [];
const unclassified = [];

// Candidate ids look like N<f>.<k> or S<k>; recheck ids come from args.recheck.
function idsInPrompt(prompt) {
  const args = typeof scenario.args === "object" && scenario.args ? scenario.args : {};
  const known = new Set((args.recheck ?? []).map((r) => r.id));
  const found = [];
  const seen = new Set();
  const re = /(?<![\w.])(N\d+\.\d+|S\d+|[A-Z]+\d+)(?!\w|\.\d)/g;
  for (const m of prompt.matchAll(re)) {
    const id = m[1];
    if (seen.has(id) || !(/^(N\d+\.\d+|S\d+)$/.test(id) || known.has(id))) continue;
    seen.add(id);
    found.push(id);
  }
  return found;
}

function classify(label) {
  if (/^sweep$/.test(label)) return { kind: "sweep", slot: 0 };
  if (/^find:/.test(label)) return { kind: "find", slot: 0 };
  if (/tie/i.test(label)) return { kind: "tiebreak", slot: 0 };
  const m = /^verify:b?\d+:(\d+)/.exec(label);
  if (m) return { kind: "verify", slot: Number(m[1]) };
  return null;
}

function verdictRow(id, spec) {
  return {
    item_id: id,
    holds: true,
    severity: "important",
    reason: "",
    evidence: "",
    trigger: "",
    prevented_by: "",
    needs_decision: { criterion: 0, before: "", after: "", intent_quote: "", options: [] },
    ...spec,
  };
}

function verifierReply(rec) {
  const role = rec.kind === "tiebreak" ? "tiebreak" : "vote";
  const key = `${role}:${rec.slot}`;
  const verdicts = [];
  for (const id of rec.ids) {
    const spec = scenario.verdicts?.[id]?.[key] ?? scenario.default_spec ?? {};
    if (spec === "omit") continue;
    const { _dup, ...fields } = spec;
    verdicts.push(verdictRow(id, fields));
    if (_dup) {
      verdicts.push(verdictRow(id, { ...fields, holds: !verdicts.at(-1).holds, reason: "dup-second" }));
    }
  }
  for (const e of scenario.extra_rows ?? []) {
    if (e.kind === rec.kind && e.slot === rec.slot && rec.ids.includes(e.for_id)) {
      verdicts.push(verdictRow(e.row.item_id, e.row));
    }
  }
  return { verdicts };
}

const agent = async (prompt, opts) => {
  const label = opts?.label ?? "";
  const cls = classify(label);
  const rec = { prompt, opts: clone(opts), label, kind: cls?.kind ?? "other", slot: cls?.slot ?? 0 };
  rec.ids = rec.kind === "verify" || rec.kind === "tiebreak" ? idsInPrompt(prompt) : [];
  calls.push(rec);
  if (!cls) {
    unclassified.push(label);
    return null;
  }
  const throws = (scenario.throw_calls ?? []).some(
    (t) =>
      t.kind === rec.kind &&
      (t.label === undefined || t.label === label) &&
      (t.slot === undefined || t.slot === rec.slot),
  );
  if (throws) throw new Error(`harness: agent ${label} failed`);
  return schemaGuard(opts, reply(rec, label));
};

const schemaGuard = (opts, value) => {
  if (value === null || value === undefined) return null;
  const required = opts?.schema?.required ?? [];
  return required.every((k) => value && typeof value === "object" && k in value) ? value : null;
};

const reply = (rec, label) => {
  if (rec.kind === "find") {
    const find = scenario.find ?? {};
    return label in find ? clone(find[label]) : { findings: [] };
  }
  if (rec.kind === "sweep") {
    return "sweep" in scenario ? clone(scenario.sweep) : { findings: [] };
  }
  const isNull = (scenario.null_calls ?? []).some(
    (n) => n.kind === rec.kind && (n.slot === undefined || n.slot === rec.slot),
  );
  return isNull ? null : verifierReply(rec);
};

// Failed thunks resolve to null; thunks start together and the call returns after all settle.
const parallel = (thunks) =>
  Promise.all(thunks.map((t) => Promise.resolve().then(t).catch(() => null)));
// Each item flows through the stages in order without waiting for other items.
const pipeline = (items, ...stages) =>
  Promise.all(
    items.map(async (item, i) => {
      let value = item;
      for (const stage of stages) {
        try {
          value = await stage(value, i);
        } catch {
          return null;
        }
        if (value === null) return null;
      }
      return value;
    }),
  );
const log = (msg) => logs.push(String(msg));
const phase = (title) => logs.push(`phase: ${title}`);
const budget = {};
const workflow = () => {
  throw new Error("workflow() is not supported by the harness");
};

const run = new AsyncFunction(
  "agent", "parallel", "pipeline", "log", "phase", "args", "budget", "workflow",
  source,
);
const args = "args" in scenario ? clone(scenario.args) : undefined;
const result = await run(agent, parallel, pipeline, log, phase, args, budget, workflow);
process.stdout.write(JSON.stringify({ result, calls, logs, unclassified }));
