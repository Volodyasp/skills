# review-cycle

A skill that reviews a branch (code mode) or a Markdown plan/spec (document mode) in rounds. It is modelled on the process described in [How the Claude Code team does code review](https://claude.dev/blog/solving-code-review-at-anthropic/).

- **Finders** run in parallel, one lens each (bugs, intent, project rules, history, ...).
- **Blind verifiers** try to refute every candidate. They get the claim, the location, the anchor, the project rules and the stated intent, never the finder's reasoning or evidence. Votes decide what is kept; a tie-break or a sweep runs at higher levels.
- **State between rounds** lives on disk. A re-review does not repeat findings you already decided, closes the ones that were fixed, and skips code that did not change.
- **The report is short** and printed in the CLI. Only findings that need your decision are shown in detail.

It only reports. It never edits your code; fix with your normal flow and run the next round.

## Requirements

- Claude Code with dynamic workflows enabled (`/config`). If they are off, the skill stops and says so; there is no fallback, because a fallback would lose the verifier blindness.
- Python 3.10 or newer on `PATH` as `python3` (the state script uses only the standard library).
- `git`.
- `gh` is optional. With it, the PR body is used as stated intent and the PR's base branch as the diff base. Without it, the skill continues with commit messages and a default base.

## Install

```bash
claude plugin marketplace add Volodyasp/skills
claude plugin install review-cycle@skills
```

Restart Claude Code after install.

### Permission rule

The skill runs the helper `review-cycle-state` (the plugin puts it on `PATH` while enabled). Add this allow rule to your settings once:

```
Bash(review-cycle-state *)
```

The `allowed-tools` line in the skill frontmatter covers only the current message and clears on the next one, and a rule on the versioned plugin cache path would break on every update. Without the rule, every later turn of a review asks for permission.

When Claude starts the skill itself, because you asked in a message instead of typing `/review-cycle`, it calls the Skill tool, and that call needs permission too. In `claude -p` nobody can approve it, so the skill silently does not load. For a headless run, or to skip the prompt, also allow:

```
Skill(review-cycle:review-cycle)
```

## Usage

```
/review-cycle [level] [--incremental|--full|--fresh] [--focus <text>] [--path <dir>]... [--model <alias>] [--intent <path|text>] [target]
/review-cycle show F4
/review-cycle F7 intentional "reason"
```

You can also ask in plain words, in any language: "run review-cycle at high on the whole branch", "review only src/auth", "review the last 3 commits", "only what I have not committed", "everything since the v1.2 tag". Claude maps what you said to these flags and targets and passes nothing you did not say. For a date or a tag it finds the commit with read-only git and tells you which one it picked. Each explicit range or path set is its own review cycle with its own rounds.

When the level is missing, or the scope is missing from round 2 on, the skill asks before it starts. Each option shows how many agents it would run, and the recommended one comes first:

- level: the last round's level on this branch, else the last level you used, else `high`;
- scope: `--incremental`, or `--full` in the cases listed under [Rounds](#rounds).

Without the question tool, for example in `claude -p`, the recommended values are used and the skill says so.

| Part | Meaning |
|---|---|
| `level` | `low`, `medium`, `high`, `xhigh` or `max`. |
| `--incremental` | From round 2: review only what changed since the last round. |
| `--full` | Review the whole branch or document this round. |
| `--fresh` | Archive the saved state and start over as round 1 with no known findings. |
| `--focus <text>` | A concern the finders should look at harder, up to 500 characters. Every other real problem is still reported, and verifiers never see the focus. On unchanged code it starts a new round over the whole target. |
| `--path <dir>` | Code mode: review only branch files under this path. Repeat for several paths. A path-limited review is its own cycle, with its own rounds and findings. |
| `--model <alias>` | Use this model for every role, verifiers and tie-break included. The flag wins over the level table. |
| `--intent <path\|text>` | Extra stated intent: an existing file, or literal text. It adds to PR body, commits and linked docs; it never replaces them. |
| `target` | See below. |

Targets:

| Target | Mode | Reviews |
|---|---|---|
| none | code | the current branch against its base |
| a branch name | code | that branch; it must be checked out |
| `#N` or `N` | code | pull request N; it must be the checked-out branch; needs `gh` |
| `<base>...HEAD` | code | the current branch against `<base>` (any local ref, relative forms such as `HEAD~3` included) |
| `HEAD...HEAD` | code | only uncommitted changes |
| `path/to/file.md` | document | that Markdown file, inside the repo |

### Show and decide

- `/review-cycle show F4` prints every field of a finding and its vote history.
- `/review-cycle F7 intentional "reason"` records a decision. Verbs: `intentional`, `wontfix`, `wrong` (reason required), `superseded`, `open` (reopen), `fix` (move an item out of "needs your decision" to "agent can fix"). In the same session you can also say it in plain words and the skill runs the command.
- A decided finding is not raised again unless the code at its anchor changes; then it appears once under "Reopen?".
- Ids are numbered per review target, so a branch with a `--path` or document review can have two F1s. Then the helper lists them as `<target>/F1`, and Claude asks you which one you mean.

### Fix and re-review

The report is the same for everyone, and Claude never edits it. After it, Claude adds at most three lines in your language: what needs your decision, what it can fix, and the next step.

Ask Claude to fix, and it fixes the "Agent can fix" items plus anything you moved there with `F<n> fix`. Items under "Needs your decision" wait for you. Claude never marks a finding fixed: the next round's re-check closes it when the verifiers see the problem gone. Then run `/review-cycle` again; for a re-review the skill recommends `--incremental`.

When the helper stops with an error, Claude explains the cause and proposes a way out, such as checking out the branch or using `--fresh`. It runs git or edits files only after you agree. It edits REVIEW.md or CLAUDE.md only when you ask; a rule suggestion alone is not a request.

## Levels

Finders always run on Sonnet. Code and document mode share the same table; the finder names differ.

| level | code finders | doc finders | votes | keep rule | tie-break | verify depth | sweep |
|---|---|---|---|---|---|---|---|
| low | bugs, intent | contradictions-gaps, code-claims | sonnet, sonnet | all2 | - | anchor and its file | - |
| medium | + rules | + ambiguity | sonnet, sonnet | all2 | - | + callers and callees | - |
| high | + history | + unneeded | sonnet, opus | all2_tiebreak | opus | + tests and config | - |
| xhigh | + bugs/reverse | + contradictions-gaps/reverse | sonnet, sonnet, opus | maj3 | - | name a concrete trigger or the line that prevents it | - |
| max | + system-fit | + consistency-links | opus, opus, opus | maj3 | - | as xhigh | sonnet |

Each row adds to the one above it. That gives 2, 3, 4, 5 and 6 finders for `low` to `max`, and about 6, 7, 9, 11 and 12-14 agents per round.

Keep rules, with H = the number of verifiers that say the finding holds:

- `all2`: both votes hold, kept. One holds and the other returned nothing, kept as Uncertain. Otherwise rejected.
- `all2_tiebreak`: both hold, kept. Neither holds, rejected. They split: the Opus tie-break decides (Uncertain if it returns nothing).
- `maj3`: 2 or 3 hold, kept. 1 holds, Uncertain. None, rejected.
- With no vote returned at all, a finding is Uncertain, never rejected.
- Severity is Important if any confirming verifier says so, otherwise Nit.
- `max` adds a sweep: for every confirmed class, one agent looks for every other instance.
- Verifiers read code only. They never run it, at any level.

`low` means "few findings, the most confident", as in the bundled `/code-review`. It is not the cheapest possible run.

Without `--model`, Haiku is never used as a verifier or tie-break.

### Small-diff rule (code mode only)

When the round's scope is at most 50 changed lines in at most 3 files (lock and generated files excluded), only the first 2 finders of the level run. Document mode never reduces finders. The start values are round numbers with no data behind them and will be tuned from real runs. The plan line shows `small-diff: <from> → <to> finders` when it applies.

## What the report looks like

Names, paths and the bug below are invented.

```
review-cycle · round 2 · high · since 04bc916 · 9 agents
1 needs your decision · 1 agent can fix · 1 Nit · 1 Pre-existing · 6 rejected
Closed since round 1: F1, F2 (fixed) · not shown: 4 nits over the cap

Needs your decision
 F7  src/billing/refund.ts:58 · refund of a partly paid order returns the full sum
     Trigger:  order paid 30 of 100, user cancels -> refund 100
     Evidence: refund.ts:58 takes order.total, not the paid sum (refund.ts:41)
     Why you:  fix options differ in behaviour
     Options:  refund the paid sum · refuse partial refunds · mark intentional

Agent can fix
 F4  src/billing/charge.ts:142 · retry after a timeout charges twice (class: retries without idempotency key)

Nit (1)
 F10 src/billing/format.ts:9 · ...

Pre-existing (1)
 F13 src/billing/tax.ts:12 · rounding uses float

Details: /review-cycle show F4 (or ask in this session)
```

Sections, in order (empty ones are omitted):

- **Needs your decision**: a verifier flagged it with evidence. The fix changes a business rule or public contract (before -> after), or the finding contradicts the stated intent (quoted), or the fix options differ in observable behaviour. No evidence, no flag.
- **Agent can fix**: Important, no decision needed. Each names its class ("every instance of X").
- **Uncertain**: kept, but the votes did not agree or a verifier returned nothing.
- **Nit**: capped (default 5, or the cap in REVIEW.md); the rest stay in state and are counted as "nits over the cap".
- **Pre-existing** (document mode: **Out of scope**): not introduced by the change. Non-blocking.
- **Reopen?**: a decided finding whose anchored code changed.

If nothing needs fixing the report says `Nothing to fix.` If a run finds no change since the last round, it prints the previous report and says it is not a new round.

When the host supports `ReportFindings`, the findings are also reported through it.

### Statuses

`open`, `fixed` (a re-check shows the problem gone), `intentional`, `wontfix`, `wrong`, `superseded`. Open findings are re-checked every round.

### Rounds

- Round 1: the whole branch.
- Round 2 and later: you choose `--incremental` (only files whose own diff changed since the last round) or `--full` (the whole branch). Either way, open findings are re-checked and known findings go to the finders as a no-repeat list.
- The skill recommends `--incremental`, except after a base change, when saved file ids are missing, or when the level is higher than in every earlier round: the new level has not seen the rest of the branch. With `--incremental` at a raised level the plan prints a `warning:` line.
- A different level or `--full` on unchanged code runs a new round over the whole branch.
- Before round 4 or later, if an open Important finding has survived a fix round, the skill asks whether to reconsider the approach. "Continue" runs the round.
- A rebase, a clean base merge, an empty commit or committing unchanged work does not count as a new round.
- Uncommitted changes are always included.

## What it does not report

- Style, naming and cleanup.
- Anything a linter, type checker or compiler catches.
- Issues silenced in the code (ignore comments).
- Generated and lock files.
- Paths that REVIEW.md excludes.

There is no security lens. Use `/security-review` for that.

## Project guidance

- Rules are read from `CLAUDE.md`, `AGENTS.md` and `.claude/CLAUDE.md` at the repo root, when present.
- `REVIEW.md` is read as of the merge-base, never from the branch under review, so a branch cannot weaken its own review. Its skip paths, severity recalibration and nit cap are honoured.
- Stated intent comes from the PR body (`gh`), commit messages, Markdown files they link, and `--intent`. If there is none, the report says so.
- When the same class of finding is marked `wrong` several times in a repo, the report suggests one `REVIEW.md` line. It never writes the file.

## State

Per branch and target:

```
agents/TEMP/<branch-dir>/review-cycle/<target>/
```

- `<branch-dir>` is the branch name without the part up to the first `/`.
- `<target>` is `code`, `doc-<slug of the path>`, `code-path-<slug of the paths>-<short hash>` for a `--path` review, or `code-range-<slug of the base>[-path-<slug>]-<short hash>` for an explicit range such as `HEAD~3...HEAD`.
- Files: `plan.json`, `state.json`, `round-N.md` (every finding in full, plus a hand-off block for the coding flow), `verify/` (the only files verifiers may read), and a `.gitignore` containing `*`.
- Only `review-cycle-state` writes these files.

The plugin data dir (`${CLAUDE_PLUGIN_DATA}`) holds `last-level` and `outcomes.jsonl`: one line per decided finding with `ts, repo, branch, mode, level, finding_id, category, class, severity, status, response_type, round, first_round, moved_from_decision`. `repo` is the origin URL with any credentials removed, or the absolute local path when there is no origin. No code, claim or reason text is stored; `class` is a short label of at most 80 characters.

## Things to know

- The base branch is a local ref and is never fetched. If `origin/main` is stale, fetch first. The `base:` line of the plan shows which ref was used and why.
- To see the branch, the tool snapshots the work tree into a temporary index and writes loose git objects only. Refs, the index and the work tree are untouched.
- One run starts roughly 6 to 14 agents. The plan prints the estimate before the run starts. Claude may start the skill when you ask for a review in a message, but it never picks the level or scope for you: anything you did not state is asked first.
- The skill has to be run from a checked-out branch, not a detached HEAD.

## Developer

Run in `plugins/review-cycle/`:

```bash
uv run --with pytest --with pytest-cov python -m pytest tests/ -v --cov=review_cycle --cov-report=term-missing
uv run --with ruff ruff check .
uv run --with ruff ruff format --check .
mypy .
```

The pytest command writes `.coverage` into the plugin dir; it is git-ignored. JS tests for `workflows/review.js` are skipped when `node` is not on `PATH`.
