---
name: run-slices
description: Use when the user wants to implement, ship, run, or build vertical slices produced by /to-slices under docs/specs/<slug>/slices/.
---

# Run Slices

Execute the vertical slices of a story on one story branch. Each slice runs through: fresh implementer sub-agent -> TDD implementation -> commit -> check-before-done -> slice-review -> next slice. Fresh sub-agents keep context from leaking between slices; the single story branch keeps git mechanics simple and predictable.

Execution half of the local spec pipeline: `/to-prd → /to-slices → /run-slices → /finish-slices`.

**Core principle:** fresh sub-agent per slice + TDD + two gates - does it meet the slice spec (`check-before-done`), then is the code good (`slice-review`) - gives Superpowers-style delivery for vertical slices.

## 1. Locate the slices

Determine the story slug (from the argument, or list `docs/specs/` and ask). Slices live at `docs/specs/<slug>/slices/NNN-*.md`. If the directory is missing or empty, stop and tell the user to run `/to-slices` first.

Read every slice file. Build execution order from each slice's `Blocked by` field using a topological sort:

- Missing blocker reference -> stop and ask for clarification.
- Dependency cycle -> stop and report the cycle.
- Independent slices with no ordering constraint -> run by filename order.

Note each slice's `Type` (HITL / AFK). Create a TodoWrite with one item per slice.

## 2. Ask the execution mode

Ask the user, once:

- **Step-by-step** — run one slice, then stop and report; continue on the user's go-ahead. Maximum control.
- **Autonomous** — run every slice back-to-back; pause only at a HITL slice, or on a failure that survives the retry budget. Hands-off.

No parallel mode. Slices commonly touch overlapping files and later slices build on earlier ones. Both modes are sequential - one slice at a time. The mode controls only whether the loop pauses after a slice is accepted; the two gates always run for every slice in both modes.

## 3. Confirm the branch

Confirm the current branch is the story branch. If not, ask the user. Never run a slice on `main` / `master`.

Before the first slice and before every later slice, run a clean working-tree check:

```bash
git status --short
git rev-parse --abbrev-ref HEAD
```

If the working tree is dirty before starting a slice, stop and ask. Do not mix user changes or planning artifacts into slice commits.

## 4. Per-slice loop

For each slice, in execution order:

### 4a. Implement (sub-agent)

Record the slice base:

```bash
BASE_SHA=$(git rev-parse HEAD)
```

Spawn a fresh implementer sub-agent in the current story-branch checkout. Do not create a worktree. Do not reuse the previous slice's implementer.

Use `implementer-prompt.md` in this skill directory as the dispatch template.

Construct its context - do not just point it at the slice file. Give it:

- The full slice spec, including `## What to build` and `## Acceptance criteria`.
- The project test command and any lint/build commands known from CLAUDE.md.
- The current branch name and `BASE_SHA`.
- Any interfaces or decisions from already-accepted slices it needs.

A sub-agent starts with zero session history; it gets exactly what you hand it.

The implementer must follow TDD:

1. Write a failing test for the slice behavior.
2. Run the targeted test and confirm it fails for the expected reason.
3. Write the minimal implementation.
4. Run the targeted test and the project verification command.
5. Refactor only while tests stay green.
6. Commit the slice on the story branch using the project's commit format.
7. Self-review, then return one status (see Implementer status), the commit SHA, commands run, and RED/GREEN evidence.

After the implementer returns, verify commit integrity before any gate:

```bash
git status --short
git rev-list --count "$BASE_SHA"..HEAD
git diff --stat "$BASE_SHA"..HEAD
```

`git status --short` must be empty, `rev-list --count` must be at least 1, and the diff must not include planning artifacts unless the user or project explicitly tracks/updates them as part of delivery. If this fails, dispatch a fresh fix sub-agent on the same branch with the integrity failure and require a clean commit before continuing. Use `fix-agent-prompt.md` for fix dispatches.

The implementer result must include the machine-readable YAML block from `implementer-prompt.md` with top-level keys: `status`, `commit_sha`, `commands_run`, `red_green_evidence`, `issues`, and `fix_request`. If the block is missing, malformed, or internally inconsistent, treat it as a protocol failure: re-dispatch a fresh implementer-role sub-agent with the instruction to return a valid YAML block only. Do not count protocol failures against code fix budgets.

### 4b. Check before done

Runs automatically for every slice, in both modes. Invoke the **`check-before-done`** skill. Give it the full slice spec, acceptance criteria, current branch, `BASE_SHA..HEAD` diff range, verification commands, and the latest implementer/fix-agent YAML result. It dispatches its own fresh verification sub-agent.

Any item fails -> dispatch a fresh fix sub-agent on the same branch with the verifier's report, the slice spec, the current diff, and the fix-round number. Use `fix-agent-prompt.md`. The fix sub-agent applies the **`handle-review-feedback`** discipline: verify each item against the code, push back on wrong or out-of-scope items with evidence, fix one at a time. On the **second** consecutive failure of this gate it applies **`debug-slice-failure`** instead - root cause before any further patch.

Handle the fix result. First confirm whether code changed — compare `git rev-parse HEAD` against HEAD before the dispatch; a committed fix means the fix-agent's `commit_sha` is a real new commit.

- **Code changed** -> re-run `check-before-done`. The fresh re-run is the gate's independent verdict on the fix.
- **Pushback only** (`status: DONE_WITH_CONCERNS`, no commit, HEAD unchanged) -> do not re-run the gate; nothing changed, so its verdict would be identical. The orchestrator resolves the dispute itself — never re-run the gate with the fix-agent's argument as context.

Adjudicate every pushed-back item yourself:

- Convincing evidence -> the item is **resolved by pushback**, and stays resolved for the rest of the slice even if a later re-run re-raises it.
- Unconvincing -> the item is still a **failed gate item**.
- Pushback is legitimate only for judgement calls — a criterion read wrongly, a criterion marked unproven that the evidence does satisfy, a requirement outside the slice scope. A red test, a non-zero command, or a missing required command cannot be pushed back; that needs a code or test change. Treat such a pushback as unconvincing.
- Uncertain -> stop and ask the user.

The gate is satisfied when every failed item is either fixed (the re-run confirms it) or resolved by pushback. Otherwise continue the fix loop.

Budget: 2 fix rounds — a pushback-only round counts. Still failing -> stop and report to the user.

The verifier result must include the machine-readable YAML block from `verifier-prompt.md` with top-level keys: `status`, `commit_sha`, `commands_run`, `red_green_evidence`, `issues`, and `fix_request`. If the block is missing or malformed, treat it as a protocol failure: re-dispatch the verifier with the instruction to return a valid YAML block only. Do not send malformed verifier output to a fix-agent and do not count it against code fix budgets. If the YAML is valid but says anything other than `status: PASS`, the gate failed — enter the fix-result handling above.

### 4c. Slice review

Runs automatically for every slice, in both modes - only after 4b passes. Invoke the **`slice-review`** skill. Give it the `BASE_SHA..HEAD` diff, the full slice spec, current branch, repo root, and relevant CLAUDE.md path(s). It dispatches its own fresh code-review sub-agent.

Issues -> dispatch a fresh fix sub-agent on the same branch with the review report, the slice spec, the current diff, and the fix-round number. Use `fix-agent-prompt.md`. The fix sub-agent applies the **`handle-review-feedback`** discipline: verify each review item, push back on out-of-scope or wrong comments with evidence instead of complying blindly. On the **second** consecutive failure of this gate it applies **`debug-slice-failure`** instead - root cause before any further patch.

Handle the fix result the same way as 4b — first confirm whether code changed:

- **Code changed** -> re-run `check-before-done` first (a review fix can break behaviour), then re-run `slice-review`.
- **Pushback only** (`status: DONE_WITH_CONCERNS`, no commit, HEAD unchanged) -> do not re-run either gate. The orchestrator adjudicates the dispute itself.

Adjudicate every pushed-back review item yourself: convincing evidence -> **resolved by pushback**; unconvincing -> still a **failed gate item**; uncertain -> stop and ask the user. Code-quality feedback is judgement, so a pushback here can be legitimate — but a real bug the reviewer found is not a difference of opinion.

The gate is satisfied when every review item is either fixed (the re-runs confirm it) or resolved by pushback. Budget: 2 rounds — a pushback-only round counts. Still failing -> stop and report to the user.

The reviewer result must include the machine-readable YAML block from `reviewer-prompt.md` with top-level keys: `status`, `commit_sha`, `commands_run`, `red_green_evidence`, `issues`, and `fix_request`. If the block is missing or malformed, treat it as a protocol failure: re-dispatch the reviewer with the instruction to return a valid YAML block only. Do not send malformed reviewer output to a fix-agent and do not count it against code fix budgets. If the YAML is valid but says anything other than `status: APPROVED`, the gate failed — enter the fix-result handling above.

### 4d. HITL gate

If the slice's `Type` is HITL, stop and ask the user to review and approve before accepting the slice - regardless of execution mode.

### 4e. Accept the slice

The code is already committed on the story branch. Record the accepted commit range (`BASE_SHA..HEAD`) in the session's slice acceptance report, mark the slice complete in TodoWrite, and keep going.

### 4f. Next

Step-by-step: stop here and report; continue on the user's go-ahead. Autonomous: continue immediately. Either way the next slice gets a brand-new sub-agent - no sub-agent context carries over.

## 5. After all slices

Invoke the **`finish-slices`** skill. Give it the session's slice acceptance report if available. It runs final verification on the whole story branch, summarises what shipped with slice commit ranges, assembles a PR body, and offers the delivery options (push and open a PR, keep the branch, heavyweight review, stop).

## Implementer status

The implementer sub-agent returns one of:

- **DONE** — proceed to 4b.
- **DONE_WITH_CONCERNS** — read the concerns; address any correctness or scope issue before 4b; otherwise note and proceed.
- **NEEDS_CONTEXT** — supply the missing information and re-dispatch.
- **BLOCKED** — assess the blocker: supply context, use a more capable model, split the slice, or escalate to the user. Never ignore an escalation; never re-dispatch the same model with no change.

Status is not enough by itself. A DONE-like status must include a valid machine-readable YAML block with `status`, `commit_sha`, `commands_run`, `red_green_evidence`, `issues`, and `fix_request`. If any required field is missing, treat it as NEEDS_CONTEXT or failed commit integrity.

## Model selection

Use the least powerful model that fits each role. Mechanical slices → a fast model for the implementer; judgment-heavy slices and the reviewer → a more capable model.

## Red flags — never

- Run a slice on `main` / `master`.
- Skip `check-before-done` or `slice-review`, or run them in only one mode.
- Start `slice-review` before `check-before-done` passes.
- Accept a slice with an unresolved failed item from either gate — an item resolved by pushback is not unresolved.
- Trust the implementer's success claim instead of verifying.
- Dispatch implementer sub-agents for multiple slices in parallel.
- Make a sub-agent read the PRD or other slice files — construct its context yourself.
- Carry context from one slice's sub-agent into the next.
- Continue after a review fix that changed code without re-running `check-before-done`.
- Start a slice while `git status --short` is dirty.
- Patch the same gate a third time instead of escalating to `debug-slice-failure`.
- Re-run a gate with the fix-agent's pushback argument as context — adjudicate disputes in the orchestrator, keep the gate independent.

## Notes

- Single branch delivery: every accepted slice is represented by one or more commits on the story branch. The orchestrator uses `BASE_SHA..HEAD` as the slice boundary.
- Commit style: follow explicit user/project instructions first. If none exist, use a plain imperative message.
- Planning artifacts: treat `docs/specs/<slug>/` as uncommitted planning output by default. If the project intentionally tracks specs/docs, follow that project convention instead.
