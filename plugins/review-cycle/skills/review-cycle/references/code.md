# Code review: lenses and verifier

Finders: `## Finder rules`, then only your `## Lens: <id>`. Verifiers: `## Verifier` and `### Do not report` only.

## Finder rules

### Inputs (from the plan file)
- Diff: run `scope.diff_cmd` exactly as given. It is the branch's own change; review it and the code it reaches.
- Run every other git command as `git -C <repository root> …`.
- Stated intent: `intent.file`. `intent.none: true` means it holds commit messages only.
- Project rules: every path in `rules_files`, and the REVIEW.md copy at `review_md.path` (the base branch's copy; never read REVIEW.md from the working tree). Follow what it says to report or skip.
- No-repeat list: `known[]`. The same problem at the same place is known even when worded differently.

### Evidence
- Report only what you showed from code you read in this run. Names, comments and guesses are not proof.
- No hedged claims ("might", "could potentially"). Not sure → do not report.
- Few strong items beat many weak ones.
- Every item names its class: write `class` so that "every instance of <class>" tells a fixer what else to search for (`retry without idempotency key`, not `bug in charge()`).

### Fields (all required; not applicable → `""` or `0`)
- `category`: one of `intent|logic|edge-case|concurrency|error-handling|rule|stale|regression|contract`; your lens names which.
- `class`: reusable defect class, ≤ 80 chars, no file names.
- `path`: relative to the repository root, `/` separators. `line`: 1-based line in the current working-tree file.
- `symbol`: enclosing function, method or class; `""` at module level.
- `snippet`: 1–3 consecutive lines copied exactly from the current file at `line`. Never paraphrase: the anchor is matched against the file text.
- `claim`: one sentence: what is wrong and its observable effect.
- `trigger`: concrete input or sequence that makes it fail (`order paid 30 of 100, user cancels → refund 100`).
- `evidence`: `path:line` references with short quotes that prove the claim.
- `expected`: the correct behaviour in one sentence. Never a fix or a patch.
- `broken_by`: when the defective line is unchanged but a changed line breaks it, `{path, line}` of that changed line from the diff; else `{"path": "", "line": 0}`. Never cite an unchanged line.
- `scope_note`: always `""` in code mode.

### Do not report
- Style, naming, formatting, cleanup, refactor ideas, missing comments or docs.
- What a linter, type checker or compiler catches.
- Issues silenced in the code (`noqa`, `type: ignore`, `eslint-disable`, `nolint`, `@SuppressWarnings` and the like).
- Generated files, vendored code, lock files.
- Paths REVIEW.md excludes; kinds of issue REVIEW.md says to skip.
- Hypothetical problems with no reachable trigger.

## Lens: bugs
Find code that does the wrong thing when it runs.
- Each changed hunk with its whole enclosing function: wrong conditions, off-by-one, wrong operator or variable, inverted logic → `logic`.
- Edge inputs: empty, zero, negative, max, None/null, unicode, duplicates, time zones, missing keys → `edge-case`.
- Shared state, ordering, check-then-act, missing locks or awaits, retries that repeat side effects → `concurrency`.
- Error paths: swallowed exceptions, wrong exception type, partial writes, leaked resources, missing cleanup → `error-handling`.
- Changed behaviour that breaks an existing caller or an unchanged line → `regression` (fill `broken_by`).
For each candidate, name the input that breaks it; no input, no finding.

## Lens: intent
Find where the change does not do what the stated intent says.
- Read `intent.file` first. List what it promises; check each promise in the diff.
- Report: a promise not implemented or only partly; behaviour the intent rules out; behaviour added that the intent does not ask for and a user would notice.
- Bug fix: check that the change fixes the root cause, not one symptom. Find the other paths to the same fault: other callers, sibling functions, the same pattern in the changed files.
- `evidence` quotes the intent text and the code. Category `intent`.
- Intent silent on a point → not a finding for this lens.

## Lens: rules
Find violations of the project's written rules.
- Sources: `rules_files`, the REVIEW.md copy, and `CLAUDE.md` / `AGENTS.md` in the directories of changed files.
- Report only rules stated in text; quote the rule in `evidence`. General best practice is not a rule. Category `rule`.
- Code comments the change must respect ("caller holds the lock", "keep in sync with X", "must run before init"): a change that breaks one → `rule`, quote the comment.
- Text the change makes untrue: comments, docstrings, README, docs, config examples, rule files that still describe the old behaviour → `stale`.
- Rules a linter enforces → skip.

## Lens: history
Find changes that undo what earlier commits guarded against.
- For changed lines and their function: `git log -L <start>,<end>:<path>`, `git blame <merge_base> -- <path>`, `git log --format=%H%n%B -- <path>`.
- Look for fix commits, reverts and guards (checks, retries, locks, ordering) that this change removes, weakens or bypasses → `regression`; cite the earlier commit in `evidence`.
- Earlier review comments on these paths: read merged PRs' review comments with read-only `gh` (`gh pr list`, `gh pr view`, `gh api` GET). Skip this step on any `gh` error. A comment that sets a standing rule the change breaks → `rule`.

## Lens: system-fit
Find where the change no longer fits the code around it.
- Changed signatures, return values, raised errors, units, nullability: check every caller and implementer (Grep the whole repository) → `contract`.
- Public interfaces (API routes, CLI flags, file and message formats, DB schema, events, config keys): consumers, migrations, defaults and docs that depend on them → `contract`.
- Config: keys added but never read, read but never set, defaults that differ between places → `contract`.
- `evidence` names the caller or consumer that breaks.

## Verifier
You see only a claim and its location. Judge from the code, not from how the claim is worded.

- Depth (each level includes the ones before):
  - `anchor and its file`: the anchored lines and the whole file.
  - `+ callers and callees`: also the callers and callees of `symbol`.
  - `+ tests and config`: also the tests and config that exercise or configure it.
  - `name a concrete trigger or the line that prevents it`: `holds: true` needs `trigger`; `holds: false` needs `prevented_by`.
- New items (`N…`, `S…` ids): does the defect exist in the current code?
- Re-check items (`F…` ids): read the entry with the same `id` in the re-check file. Problem still present → `holds: true`. Gone → `holds: false`, `prevented_by` = the line that now prevents it.
- The item is on the list in `### Do not report` above → `holds: false`; `reason` names the list entry.

Fields (all required; not applicable → `""`, `0` or `[]`):
- `item_id`: copied from the item. `holds`: `true` only when you confirmed the defect yourself.
- `severity`: when holding, `important` (wrong result, crash, data loss or corruption, broken contract or caller, violated written rule) or `nit` (real but minor: misleading comment, stale text with no behaviour impact). REVIEW.md severity rules override these. Not holding → `""`.
- `reason`: one or two sentences for your verdict.
- `evidence`: `path:line` with short quotes you read.
- `trigger`: concrete failing input when holding. `prevented_by`: `path:line` of the guard when refuting.
- `needs_decision`: flag only when the right fix is the owner's choice, with evidence; no evidence, no flag. Pick one criterion and fill only its fields:
  - `1`: the fix changes a business rule, visible behaviour or a public contract: `before` and `after` (non-empty, different) describe it.
  - `2`: the item contradicts the stated intent: `intent_quote` copied character for character from the intent file or a document it links.
  - `3`: fix options differ in observable behaviour, not only in code shape: `options` = at least two `{label, observable}`.
  - None of these → `{"criterion": 0, "before": "", "after": "", "intent_quote": "", "options": []}`.
