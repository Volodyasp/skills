// Cursor has no Workflow runtime. This driver loads the pure steps from review.js and
// walks one round as waves: the skill launches a Task subagent per task, writes the
// reply file, then calls `fold`. Blindness stays here: verifier prompts are built from
// the claim fields only. stdout is `key: value` lines, same shape as review-cycle-state.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const reviewPath = join(here, "review.js");

function loadLib() {
  let source = readFileSync(reviewPath, "utf8").replace(/^export const meta/m, "const meta");
  const marker = "// --- entry ---";
  const at = source.indexOf(marker);
  if (at < 0) throw new Error("review.js is missing the entry marker");
  source =
    source.slice(0, at) +
    `return {
      PROVENANCE, NEXT_MODEL, NEXT_RUN_SKILL, parseArgs,
      finderPrompt, finderSchema, verifierPrompt, sweepPrompt, VERIFIER_SCHEMA,
      absorbFinderReply, absorbSweepReply, absorbVerdictReply,
      makeBatches, voteTasks, splitItems, holdingVotes, dedupKey,
      fnv1a32, checksumText, compare,
    };`;
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const run = new AsyncFunction(
    "agent", "parallel", "pipeline", "log", "phase", "args", "budget", "workflow",
    source,
  );
  return run(async () => null, async () => [], async () => [], () => {}, () => {}, undefined, {}, () => {});
}

function flag(argv, name) {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : undefined;
}

function lines(pairs) {
  for (const [key, value] of pairs) process.stdout.write(`${key}: ${value}\n`);
}

function boxed(prompt, schema) {
  return (
    `${prompt}\n\nYour final message is one JSON object matching this schema, and nothing else:\n` +
    JSON.stringify(schema)
  );
}

function schemaOk(schema, value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  return (schema?.required ?? []).every((key) => key in value);
}

function readReply(file) {
  let text;
  try {
    text = readFileSync(file, "utf8").trim();
  } catch {
    return null;
  }
  if (!text) return null;
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) text = fence[1].trim();
  try {
    return JSON.parse(text);
  } catch {
    const start = text.indexOf("{");
    const end = text.lastIndexOf("}");
    if (start >= 0 && end > start) {
      try {
        return JSON.parse(text.slice(start, end + 1));
      } catch {
        return null;
      }
    }
    return null;
  }
}

function replyPath(dir, id) {
  return join(dir, "replies", `${id}.json`);
}

function finderTasks(lib, args, dir) {
  return args.finders.map((finder, i) => {
    const label = `find:${finder.lens}${finder.order === "reverse" ? ":rev" : ""}`;
    const schema = lib.finderSchema(args.mode, false);
    const id = `find-${i}`;
    return {
      id,
      agent: "review-cycle-finder",
      model: args.finder_model,
      label,
      phase: "Find",
      prompt: boxed(lib.finderPrompt(args, finder), schema),
      schema,
      reply: replyPath(dir, id),
      finder,
      finderOrdinal: i + 1,
    };
  });
}

function verifyTasks(lib, args, batches, dir, idPrefix, phase) {
  return lib.voteTasks(args, batches).map((task) => {
    const id = `${idPrefix}-b${task.batch}-s${task.slot}`;
    const schema = lib.VERIFIER_SCHEMA;
    return {
      id,
      agent: "review-cycle-verifier",
      model: task.model,
      label: task.label,
      phase,
      prompt: boxed(lib.verifierPrompt(args, task.items, task.role), schema),
      schema,
      reply: replyPath(dir, id),
      role: task.role,
      slot: task.slot,
      batch: task.batch,
      items: task.items,
    };
  });
}

function tieTasks(lib, args, batches, dir) {
  return batches.map((batch) => {
    const label = `tiebreak:b${batch.n}:${args.tiebreak}`;
    const id = `tiebreak-b${batch.n}`;
    const schema = lib.VERIFIER_SCHEMA;
    const items = batch.items;
    return {
      id,
      agent: "review-cycle-verifier",
      model: args.tiebreak,
      label,
      phase: "Tie-break",
      prompt: boxed(lib.verifierPrompt(args, items, "tiebreak"), schema),
      schema,
      reply: replyPath(dir, id),
      role: "tiebreak",
      slot: 0,
      batch: batch.n,
      items,
    };
  });
}

function reviewItems(state) {
  return [
    ...state.candidates.map((c) => ({ id: c.id, kind: "new", path: c.path, candidate: c })),
    ...state.args.recheck.map((r) => ({ id: r.id, kind: "recheck", path: r.path })),
  ];
}

function publish(state) {
  const dir = state.dir;
  const tasks = state.pending.map((task) => ({
    id: task.id,
    agent: task.agent,
    model: task.model,
    label: task.label,
    phase: task.phase,
    prompt: task.prompt,
    reply: task.reply,
  }));
  const tasksFile = join(dir, "wave-tasks.json");
  writeFileSync(tasksFile, `${JSON.stringify(tasks, null, 2)}\n`);
  const waveFile = join(dir, "wave.json");
  writeFileSync(waveFile, JSON.stringify(state));
  lines([
    ["next", "tasks"],
    ["wave", state.phase],
    ["count", String(tasks.length)],
    ["tasks-file", tasksFile],
  ]);
}

function emit(state, phase, tasks) {
  state.phase = phase;
  state.pending = tasks;
  state.stats.agents_started += tasks.length;
  publish(state);
}

function finish(lib, state) {
  state.verdicts.sort((x, y) =>
    lib.compare(x.batch, y.batch) || lib.compare(x.role, y.role) || lib.compare(x.slot, y.slot) ||
    lib.compare(x.item_id, y.item_id));
  const result = {
    provenance: lib.PROVENANCE,
    v: 1,
    started: true,
    plan_id: state.args.plan_id,
    echo: {
      level: state.args.level,
      mode: state.args.mode,
      finders: state.args.finders,
      votes: state.args.votes,
      tiebreak: state.args.tiebreak,
      recheck_ids: state.args.recheck.map((r) => r.id),
    },
    candidates: state.candidates,
    dropped: state.dropped,
    verdicts: state.verdicts,
    missing: state.missing,
    stats: state.stats,
    log: state.logs,
    checksum: "",
  };
  result.checksum = lib.fnv1a32(lib.checksumText(result));
  const resultPath = join(state.dir, "result.json");
  writeFileSync(resultPath, `${JSON.stringify(result)}\n`);
  state.phase = "done";
  state.pending = [];
  state.resultPath = resultPath;
  writeFileSync(join(state.dir, "wave.json"), JSON.stringify(state));
  lines([
    ["next", "done"],
    ["result", resultPath],
  ]);
}

function afterVerify(lib, state) {
  if (state.args.tiebreak) {
    const tied = lib.makeBatches(
      lib.splitItems(state.items, state.verdicts, state.args.votes.length),
      state.nextBatch,
    );
    state.nextBatch += tied.length;
    const tasks = tieTasks(lib, state.args, tied, state.dir);
    if (tasks.length > 0) return emit(state, "tiebreak", tasks);
  }
  return afterTie(lib, state);
}

function afterTie(lib, state) {
  if (!state.args.sweep) return finish(lib, state);
  const classes = [];
  for (const candidate of state.candidates) {
    if (
      candidate.class &&
      lib.holdingVotes(candidate.id, state.verdicts) >= 2 &&
      !classes.includes(candidate.class)
    ) {
      classes.push(candidate.class);
    }
  }
  if (classes.length === 0) {
    state.logs.push("sweep skipped: no class with at least 2 holding votes");
    return finish(lib, state);
  }
  const groups = classes.map((cls) => ({
    cls,
    known: state.candidates.filter((c) => c.class === cls),
  }));
  const schema = lib.finderSchema(state.args.mode, true);
  const id = "sweep";
  return emit(state, "sweep", [{
    id,
    agent: "review-cycle-sweep",
    model: state.args.sweep,
    label: "sweep",
    phase: "Sweep",
    prompt: boxed(lib.sweepPrompt(state.args, groups), schema),
    schema,
    reply: replyPath(state.dir, id),
  }]);
}

function afterFind(lib, state) {
  state.items = reviewItems(state);
  const batches = lib.makeBatches(state.items, 1);
  state.nextBatch = batches.length + 1;
  const tasks = verifyTasks(lib, state.args, batches, state.dir, "verify", "Verify");
  if (tasks.length > 0) return emit(state, "verify", tasks);
  return afterVerify(lib, state);
}

function takeReply(state, task) {
  let reply = readReply(task.reply);
  if (!schemaOk(task.schema, reply)) reply = null;
  else state.stats.agents_returned += 1;
  return reply;
}

function foldFind(lib, state) {
  const seen = new Map();
  for (const task of state.pending) {
    const reply = takeReply(state, task);
    const absorbed = lib.absorbFinderReply(reply, task.finder, task.finderOrdinal, state.args.mode, seen);
    if (absorbed.nullReply) state.stats.finders_null += 1;
    state.logs.push(...absorbed.notes);
    state.candidates.push(...absorbed.candidates);
    state.dropped.push(...absorbed.dropped);
  }
  afterFind(lib, state);
}

function foldVerdicts(lib, state, next) {
  for (const task of state.pending) {
    const reply = takeReply(state, task);
    const absorbed = lib.absorbVerdictReply(task, reply);
    if (absorbed.nullReply) state.stats.verifiers_null += 1;
    state.logs.push(...absorbed.notes);
    state.verdicts.push(...absorbed.verdicts);
    state.missing.push(...absorbed.missing);
  }
  next(lib, state);
}

function foldSweep(lib, state) {
  const task = state.pending[0];
  const reply = takeReply(state, task);
  const seen = new Map(state.candidates.map((c) => [lib.dedupKey(c), c.id]));
  const absorbed = lib.absorbSweepReply(reply, state.args.mode, seen);
  state.logs.push(...absorbed.notes);
  state.candidates.push(...absorbed.hits);
  state.dropped.push(...absorbed.dropped);
  const items = absorbed.hits.map((c) => ({ id: c.id, kind: "new", path: c.path, candidate: c }));
  const batches = lib.makeBatches(items, state.nextBatch);
  const tasks = verifyTasks(lib, state.args, batches, state.dir, "sweep-verify", "Sweep");
  if (tasks.length > 0) return emit(state, "sweep-verify", tasks);
  return finish(lib, state);
}

function fresh(lib, args, dir) {
  const state = {
    v: 1,
    dir,
    phase: "find",
    args,
    candidates: [],
    dropped: [],
    verdicts: [],
    missing: [],
    logs: [],
    stats: { agents_started: 0, agents_returned: 0, finders_null: 0, verifiers_null: 0 },
    nextBatch: 1,
    items: [],
    pending: [],
    resultPath: "",
  };
  emit(state, "find", finderTasks(lib, args, dir));
}

function loadArgs(argv) {
  const file = flag(argv, "--args-file");
  const inline = flag(argv, "--args-json");
  if (file) return JSON.parse(readFileSync(file, "utf8"));
  if (inline) return JSON.parse(inline);
  return undefined;
}

function stop(reason, next) {
  lines([
    ["next", "stop"],
    ["reason", reason],
    ["next-step", next],
  ]);
}

const argv = process.argv.slice(2);
const command = argv[0];
if (command !== "open" && command !== "fold") {
  process.stderr.write("usage: cursor-round.mjs open|fold --dir <abs> [--args-file <abs> | --args-json <json>]\n");
  process.exit(2);
}
const dirArg = flag(argv, "--dir");
if (!dirArg) {
  process.stderr.write("cursor-round: --dir is required\n");
  process.exit(2);
}
const dir = resolve(dirArg);
const lib = await loadLib();

if (command === "open") {
  let raw;
  try {
    raw = loadArgs(argv);
  } catch {
    stop("bad-args", lib.NEXT_RUN_SKILL);
    process.exit(0);
  }
  const parsed = lib.parseArgs(raw);
  if (!parsed.args) {
    stop(parsed.reason, lib.NEXT_RUN_SKILL);
    process.exit(0);
  }
  if (!parsed.args.model_override) {
    const models = [...parsed.args.votes, parsed.args.tiebreak || ""];
    if (models.some((model) => /haiku/i.test(model))) {
      stop("haiku-verifier", lib.NEXT_MODEL);
      process.exit(0);
    }
  }
  mkdirSync(join(dir, "replies"), { recursive: true });
  fresh(lib, parsed.args, dir);
  process.exit(0);
}

let state;
try {
  state = JSON.parse(readFileSync(join(dir, "wave.json"), "utf8"));
} catch {
  stop("bad-args", lib.NEXT_RUN_SKILL);
  process.exit(0);
}
state.dir = dir;
if (state.phase === "done") {
  lines([
    ["next", "done"],
    ["result", state.resultPath],
  ]);
  process.exit(0);
}
if (state.phase === "find") foldFind(lib, state);
else if (state.phase === "verify") foldVerdicts(lib, state, afterVerify);
else if (state.phase === "tiebreak") foldVerdicts(lib, state, afterTie);
else if (state.phase === "sweep") foldSweep(lib, state);
else if (state.phase === "sweep-verify") foldVerdicts(lib, state, finish);
else stop("bad-args", lib.NEXT_RUN_SKILL);
