---
name: review-cycle
description: Reviews the current branch, a PR or a commit range (code mode), or a Markdown plan or spec (document mode), in rounds - parallel finders, blind verifiers that vote, state kept between rounds, so a re-review after fixes can check only what changed and re-check open findings - and prints a short report that singles out findings needing the owner's decision. A round can be focused on a concern or limited to paths. Use when the user asks for review-cycle, a multi-round review, a re-review after fixes, or a review of a plan or spec .md file, or wants to show, mark or fix a finding (F<n>) from an earlier round. For a one-off review with no saved state, /code-review fits better.
argument-hint: "[low|medium|high|xhigh|max] [--incremental|--full|--fresh] [--focus <text>] [--path <dir>]... [--model <alias>] [--intent <path|text>] [target] | show [<target>/]F<n> | [<target>/]F<n> <intentional|wontfix|wrong|superseded|open|fix> [reason]"
---

# Review cycle

Review in rounds until nothing important is left: review → the user decides and you fix → re-review what changed. `review-cycle-state` plans each round, counts votes, keeps state and renders the report. `workflows/cursor-round.mjs` splits the round into waves. You launch one Task subagent per wave entry and do not judge findings yourself.

Every finder, verifier, tie-break and sweep uses `grok-4.7-xhigh`, unless the user passed `--model`. Pass that model on every Task call. The value in the task's `model` field wins when it differs.

## Invariants
These always hold.
- Plugin root is the directory that contains `bin/review-cycle-state`. From this file that is `../../..`. Call the helper and the driver by absolute path.
- Data dir is `~/.cursor/review-cycle`, expanded to an absolute path. Pass it as `--data-dir`.
- Run each helper call as one command that starts with the absolute `bin/review-cycle-state`. No `cd`, `&&`, `;`, `|`, redirects or env prefixes. Quote every user token with single quotes; write a `'` inside a token as `'\''`.
- The helper prints `key: value` lines. Do what `next:` says. Remember `state:` and the round number from `round:`.
- Findings come only from the wave driver and the Task replies. Never review the diff yourself to add a finding.
- Verifier prompts are blind. Copy each task `prompt` into the Task call verbatim. Do not append finder output, your own notes, or another task's reply.
- Report text sits between `=== report ===` and `=== end report ===`. Print it verbatim. Never add, drop, reorder, merge or reword findings, and never change a verdict, severity or status.
- Never write state except the two files this skill names: `<state>/cursor-round-args.json` (the `workflow-args` JSON, verbatim) and each task's `reply` file (the subagent's final message, verbatim). `cursor-round.mjs` writes everything else under `<state>/cursor-round/`.
- Never pick a level or scope for the user. When one is missing, the helper asks (`next: choose`).

## Judgement
Adapt the rest to the user.
- Speak the user's language. Translate questions and option descriptions; never translate option labels, tokens or report text.
- After a report, add at most 3 lines: what needs the user's decision, what you can fix, the next step. Do not re-judge findings.
- `next: stop` with an `error:`, `reason:` or `next-step:` → print that line as is, then explain the cause in one line and propose a way out (for example `git checkout <branch>`, `--fresh`, `<base>...HEAD` as the target, another `--path`). Run git or edit files only after the user agrees. Never work around the helper.
- A usage error (exit code 2) on tokens you mapped from the user's words → fix the mapping and run once more. Any other usage error → as `next: stop` above.
- `F<n> exists in several review targets: …` → ask which one (the listed `<target>/F<n>` ids as options), then run the command again with that id.
- Edit REVIEW.md, CLAUDE.md or a file under `.cursor/rules` only when the user asks. A `rule-suggestion:` line alone is not a request.

## Start
1. Collect the tokens.
   - `/review-cycle <arguments>` written with flags → split the arguments as a shell would: quoted text is one token, quotes removed.
   - Plain words instead of flags (any language), or the user asked for the review in a message → map only what the user stated:

   | The user says | Token |
   |---|---|
   | a level | `low`, `medium`, `high`, `xhigh` or `max` |
   | only the changes since the last round | `--incremental` |
   | the whole branch or document | `--full` |
   | start over, forget earlier findings | `--fresh` |
   | look harder at a concern ("especially concurrency") | `--focus <their words>`, under 500 characters |
   | only some directories or files | `--path <path>`, once per path |
   | a model for every agent | `--model <alias>` |
   | (nothing about a model) | `--model grok-4.7-xhigh` |
   | extra intent: a file or text | `--intent <path or text>` |
   | what to review | a branch, `#<PR>`, `<base>...HEAD` or a `.md` path |
   | details or a decision on a finding | `show F<n>`, `F<n> <verb> [reason]`; `<target>/F<n>` when the helper asks which target. Do not add `--model` to show or mark commands. |
2. Run `<plugin>/bin/review-cycle-state cli --data-dir '<data-dir>' <quoted tokens>`.

Examples (plugin and data dir shortened):
- `/review-cycle` → `review-cycle-state cli --data-dir '<data-dir>'`
- `/review-cycle low --intent docs/plan.md` → `review-cycle-state cli --data-dir '<data-dir>' 'low' '--intent' 'docs/plan.md'`
- "re-review only what I changed in src/auth, high, watch the token refresh" → `review-cycle-state cli --data-dir '<data-dir>' 'high' '--incremental' '--path' 'src/auth' '--focus' 'watch the token refresh'`
- `/review-cycle F7 wrong "it's checked in auth.py"` → `review-cycle-state cli --data-dir '<data-dir>' 'F7' 'wrong' 'it'\''s checked in auth.py'`

## next: choose
The helper needs the level, the scope, or both before it plans the round.
1. Call AskQuestion once, with one question per `question-level:` / `question-scope:` line, in printed order. Its options are the matching `option-level:` / `option-scope:` lines, in printed order: label = the word before ` | `, with ` (Recommended)` added to the first; the rest of the line is the option description.
2. Run the Start command again with the answers appended as tokens, quoted as in Start: a level word as is; scope `incremental` → `--incremental`, `full` → `--full`, `fresh` → `--fresh`. An "Other" answer → map it to one of these tokens; still unclear → ask again.
3. No question tool → append the tokens after `recommended:` instead, and say in one line that the recommended values were used.

## next: workflow
1. Print the plan lines as printed: `round:`, then `base:`, `paths:`, `base changed:`, `warning:`, `agents:`, `small-diff:`, `focus:`, `intent:` when present. The user sees the agent count before anything starts.
2. Write the JSON after `workflow-args: ` verbatim to `<state>/cursor-round-args.json`. No edits.
3. Run `node '<plugin>/workflows/cursor-round.mjs' open --dir '<state>/cursor-round' --args-file '<state>/cursor-round-args.json'`.
4. `node` missing, or the call exits non-zero → print the error in one line, say no review was run, and stop. Do not review the diff yourself.
5. The driver prints `next: tasks` or `next: done` or `next: stop`. Follow that `next:`.

### Waves
While the driver prints `next: tasks`:
1. Read `tasks-file`. For every task, in one turn, call Task in parallel:
   - `description`: the task `label`
   - `subagent_type`: the task `agent` (`review-cycle-finder`, `review-cycle-verifier`, or `review-cycle-sweep`)
   - `model`: the task `model` (`grok-4.7-xhigh` unless `--model` replaced it)
   - `prompt`: the task `prompt`, verbatim
   - That subagent type is not available → `generalPurpose` with the same model and the same prompt
2. Write each subagent's final message, unchanged, to that task's `reply` path. Do not open the other reply files first and do not rewrite the JSON.
3. Run `node '<plugin>/workflows/cursor-round.mjs' fold --dir '<state>/cursor-round'`.
4. Repeat until `next: done` or `next: stop`. A `count: 0` line does not happen; the driver skips empty waves itself.

`next: done` → `result:` is the result file. Go to Merge. Say in one line that the review is running only before the first wave; after that, stay on the waves until merge.

## Merge
Run `review-cycle-state merge --data-dir '<data-dir>' --state-dir '<state>' --result '<result>'`. Pass the file as it is. Never open it to edit it.

Then follow `next:`. A merge `error:` → print it and stop; never edit the result file, and re-run the round only after the user agrees.

## next: print-report
1. Print the text between the report markers verbatim inside one ```text block, then your note of at most 3 lines (Judgement).
2. For each `report-findings: <JSON>` line, call ReportFindings once with that JSON unchanged. No ReportFindings tool → skip.

## next: ask
Call AskQuestion with the `question:` text (translated if needed) and the options from `options:` (`reconsider`, `continue`) as labels.
- `continue` → run the command after `on-continue:` exactly as printed (its paths are already quoted). It prints the new-round lines → `next: workflow`.
- `reconsider` → say in one line that no round was run, and stop.

## Fix cycle
The user asks you to fix ("fix what you can", "исправь"):
1. Fix the findings under "Agent can fix", plus those the user moved there with `F<n> fix`. Leave "Needs your decision" items until the user decides; ask about them if the fix depends on it.
2. Do not mark anything fixed. The next round's re-check closes a finding only when its verifiers see the problem gone.
3. Offer the next round with `/review-cycle`. The helper recommends a scope and asks for anything the user did not state.

## Marks and questions
- The user decides on a finding in their own words ("F7 — intentional, because …"): run `review-cycle-state cli --data-dir '<data-dir>' 'F7' 'intentional' '<reason in the user's words>'`, quoted as in Start. One command per finding.
  Verbs: `intentional`, `wontfix`, `wrong` (needs a reason), `superseded`, `open` (reopen), `fix` (move from "needs your decision" to "agent can fix"). Verb unclear → ask which one.
- Print the `marked:` line (or the `error:` line) and any `rule-suggestion:` line as printed.
- The user asks for a finding's details → run `review-cycle-state cli --data-dir '<data-dir>' 'show' 'F<n>'`, print the report text verbatim, then answer from it.
