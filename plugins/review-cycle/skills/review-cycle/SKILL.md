---
name: review-cycle
description: Reviews the current branch, a PR or a commit range (code mode), or a Markdown plan or spec (document mode), in rounds - parallel finders, blind verifiers that vote, state kept between rounds, so a re-review after fixes can check only what changed and re-check open findings - and prints a short report that singles out findings needing the owner's decision. A round can be focused on a concern or limited to paths. Use when the user asks for review-cycle, a multi-round review, a re-review after fixes, or a review of a plan or spec .md file, or wants to show, mark or fix a finding (F<n>) from an earlier round. For a one-off review with no saved state, /code-review fits better.
argument-hint: "[low|medium|high|xhigh|max] [--incremental|--full|--fresh] [--focus <text>] [--path <dir>]... [--model <alias>] [--intent <path|text>] [target] | show [<target>/]F<n> | [<target>/]F<n> <intentional|wontfix|wrong|superseded|open|fix> [reason]"
allowed-tools:
  - Bash(review-cycle-state *)
  - Workflow
  - Workflow(review-cycle:round)
---

# Review cycle

Review in rounds until nothing important is left: review → the user decides and you fix → re-review what changed. `review-cycle-state` (on PATH) plans each round, counts votes, keeps state and renders the report; the `review-cycle:round` workflow runs the finders and blind verifiers. You drive both and work with the user between rounds.

## Invariants
These always hold. The first keeps permissions working; the rest keep the review trustworthy.
- Run each helper call as one standalone Bash command that starts with `review-cycle-state`, with `--data-dir "${CLAUDE_PLUGIN_DATA}"` and tokens quoted as in Start: no `cd`, `&&`, `;`, `|`, redirects or env prefixes. The permission rule `Bash(review-cycle-state *)` matches only this shape.
- The helper prints `key: value` lines. Do what `next:` says (sections below). Remember the `state:` path and the round number from `round:`; the merge needs them.
- Findings come only from the workflow. Never run finders or verifiers yourself with other tools.
- Report text sits between `=== report ===` and `=== end report ===`. Print it verbatim. Never add, drop, reorder, merge or reword findings, and never change a verdict, severity or status: status changes only through the user's marks or the next round's re-check.
- Never write or edit state files. The one file you may Write is the fallback result file (Merge).
- Never pick a level or scope for the user. When one is missing, the helper asks (`next: choose`).

## Judgement
Adapt the rest to the user.
- Speak the user's language. Translate questions and option descriptions; never translate option labels, tokens or report text.
- After a report, add at most 3 lines: what needs the user's decision, what you can fix, the next step. Do not re-judge findings.
- `next: stop` with an `error:` or `reason:` → print that line as is, then explain the cause in one line and propose a way out (for example `git checkout <branch>`, `--fresh`, `<base>...HEAD` as the target, another `--path`). Run git or edit files only after the user agrees. Never work around the helper.
- A usage error (exit code 2) on tokens you mapped from the user's words → fix the mapping and run once more. Any other usage error → as `next: stop` above.
- `F<n> exists in several review targets: …` → ask the user which one (AskUserQuestion, the listed `<target>/F<n>` ids as options), then run the command again with that id.
- Edit REVIEW.md or CLAUDE.md only when the user asks. A `rule-suggestion:` line alone is not a request.

## Start
1. Collect the tokens.
   - `/review-cycle <arguments>` written with flags → split `$ARGUMENTS` as a shell would: quoted text is one token, quotes removed.
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
   | extra intent: a file or text | `--intent <path or text>` |
   | what to review | a branch, `#<PR>`, `<base>...HEAD` or a `.md` path |
   | details or a decision on a finding | `show F<n>`, `F<n> <verb> [reason]`; `<target>/F<n>` when the helper asks which target |
2. Wrap every token in single quotes; write a `'` inside a token as `'\''`. Never double-quote or leave a token bare, so `$( )`, backticks and `$VAR` reach the helper as plain text.
3. Run `review-cycle-state cli --data-dir "${CLAUDE_PLUGIN_DATA}" <quoted tokens>`.

Examples:
- `/review-cycle` → `review-cycle-state cli --data-dir "${CLAUDE_PLUGIN_DATA}"`
- `/review-cycle low --intent docs/plan.md` → `review-cycle-state cli --data-dir "${CLAUDE_PLUGIN_DATA}" 'low' '--intent' 'docs/plan.md'`
- "re-review only what I changed in src/auth, high, watch the token refresh" → `review-cycle-state cli --data-dir "${CLAUDE_PLUGIN_DATA}" 'high' '--incremental' '--path' 'src/auth' '--focus' 'watch the token refresh'`
- `/review-cycle F7 wrong "it's checked in auth.py"` → `review-cycle-state cli --data-dir "${CLAUDE_PLUGIN_DATA}" 'F7' 'wrong' 'it'\''s checked in auth.py'`

## next: choose
The helper needs the level, the scope, or both before it plans the round.
1. Call AskUserQuestion once, with one question per `question-level:` / `question-scope:` line, in printed order (headers `Level`, `Scope`). Its options are the matching `option-level:` / `option-scope:` lines, in printed order: label = the word before ` | `, with ` (Recommended)` added to the first; description = the text after ` | `.
2. Run the Start command again with the answers appended as tokens, quoted as in Start step 2: a level word as is; scope `incremental` → `--incremental`, `full` → `--full`, `fresh` → `--fresh`. An "Other" answer → map it to one of these tokens; still unclear → ask again.
   Example: Start ran `review-cycle-state cli --data-dir "${CLAUDE_PLUGIN_DATA}" '--intent' 'docs/plan.md'`; the user picked `high` and `incremental` → `review-cycle-state cli --data-dir "${CLAUDE_PLUGIN_DATA}" '--intent' 'docs/plan.md' 'high' '--incremental'`.
3. No AskUserQuestion tool → append the tokens after `recommended:` instead, and say in one line that the recommended values were used.

## next: workflow
1. Print the plan lines as printed: `round:`, then `base:`, `paths:`, `base changed:`, `warning:`, `agents:`, `small-diff:`, `focus:`, `intent:` when present. The user sees the agent count before anything starts.
2. Call the Workflow tool with `name` = the `workflow-name:` value and `args` = the JSON after `workflow-args: `, verbatim: no edits, no reformatting, no dropped fields.
3. Workflow tool not in this session, or the call is refused → print this line, then offer `/code-review` for a one-off review without rounds, and stop:
   `review-cycle needs the Workflow tool (dynamic workflows); enable it in /config and restart. No review was run.`
   The call returns an error → print it in one line, say no review was run, and offer to run the same command again; run it only after the user agrees.
4. Launched → say in one line that the review is running and the report follows when it finishes, then end your turn. Do not poll, sleep or wait.

## Merge
When the workflow's completion notice arrives:
- The notice names an output file → run `review-cycle-state merge --data-dir "${CLAUDE_PLUGIN_DATA}" --state-dir '<state>' --result '<that file>'`. Pass the file as it is; the helper reads the result inside it. Never open, copy or edit it.
- It names no file → Write the returned JSON exactly as returned to `<state>/result-round-<n>.json`, then run the same merge with that path.
- The workflow failed with no result → print its error in one line, say no report was written, and offer to run the round again (the Start command); run it only after the user agrees.

Then follow `next:`. A merge `error:` → print it and stop; never edit the result file, and re-run the workflow only after the user agrees.

## next: print-report
1. Print the text between the report markers verbatim inside one ```text block, then your note of at most 3 lines (Judgement).
2. For each `report-findings: <JSON>` line, call the ReportFindings tool once with that JSON as its input, unchanged. No ReportFindings tool → skip.

## next: ask
Call AskUserQuestion with the `question:` text (translated if needed) and the options from `options:` (`reconsider`, `continue`) as labels.
- `continue` → run the command after `on-continue:` exactly as printed (its paths are already quoted). It prints the new-round lines → `next: workflow`.
- `reconsider` → say in one line that no round was run, and stop.

## Fix cycle
The user asks you to fix ("fix what you can", "исправь"):
1. Fix the findings under "Agent can fix", plus those the user moved there with `F<n> fix`. Leave "Needs your decision" items until the user decides; ask about them if the fix depends on it.
2. Do not mark anything fixed. The next round's re-check closes a finding only when its verifiers see the problem gone.
3. Offer the next round with `/review-cycle`. The helper recommends a scope and asks for anything the user did not state.

## Marks and questions
- The user decides on a finding in their own words ("F7 — intentional, because …"): run `review-cycle-state cli --data-dir "${CLAUDE_PLUGIN_DATA}" 'F7' 'intentional' '<reason in the user's words>'`, quoted as in Start. One command per finding.
  Verbs: `intentional`, `wontfix`, `wrong` (needs a reason), `superseded`, `open` (reopen), `fix` (move from "needs your decision" to "agent can fix"). Verb unclear → ask which one.
- Print the `marked:` line (or the `error:` line) and any `rule-suggestion:` line as printed.
- The user asks for a finding's details → run `review-cycle-state cli --data-dir "${CLAUDE_PLUGIN_DATA}" 'show' 'F<n>'`, print the report text verbatim, then answer from it.
