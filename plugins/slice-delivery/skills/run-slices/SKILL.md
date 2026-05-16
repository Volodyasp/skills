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
- **Autonomous** — run every slice back-to-back; pause only at a HITL slice, or when a gate, a fix, or a sub-agent escalates (a blocker, a dispute, or a gate that stops making progress). Hands-off.

No parallel mode. Slices commonly touch overlapping files and later slices build on earlier ones. Both modes are sequential - one slice at a time. The mode controls only whether the loop pauses after a slice is accepted; the two gates always run for every slice in both modes.

## 3. Confirm the branch

Confirm the current branch is the story branch. If not, ask the user. Never run a slice on `main` / `master`.

**Exclude the state file first.** Before anything inspects the tree, make sure the resume state file is git-ignored: if `git check-ignore docs/specs/<slug>/.run-slices-state.md` does not already report it ignored, append that path to `.git/info/exclude` (per-clone, idempotent — never the shared `.gitignore`). This must run before any clean-tree check — otherwise an existing state file reads as a dirty tree and stops the run.

Run a clean working-tree check before starting:

```bash
git status --short
git rev-parse --abbrev-ref HEAD
```

If the working tree is dirty, stop and ask. Do not mix user changes or planning artifacts into slice commits.

**Resume an interrupted run.** `run-slices` tracks progress in one state file, `docs/specs/<slug>/.run-slices-state.md` (git-excluded — see above) — a table of the slices, each accepted one recording the commit it was accepted at. It lives on disk, never gets committed, and does not touch the slice files.

- First run for a story: create the state file with one `pending` row per slice, in execution order — see *State file format* below.
- State file already exists → a prior run was interrupted. Take the longest unbroken prefix of slices it marks `accepted`.
- Verify before trusting — the file is a hint, not proof: confirm each accepted slice's recorded commit is an ancestor of the current branch HEAD (`git merge-base --is-ancestor`), then run the project verification command once against HEAD — it must be green. A mismatch or a red suite → the state is stale; stop and report.
- Branch HEAD equals the last accepted slice's recorded commit → resume at the next slice; mark the resumed-past slices complete in the TodoWrite.
- Branch HEAD is ahead of it → an interrupted slice left commits behind. Resume needs the branch at a known-good accepted commit, so stop and ask the user to either reset the branch to that commit and let `run-slices` redo the slice, or keep the commits and finish that slice by hand — `run-slices` then resumes at the next slice once the user confirms the branch is good. Never `git reset` yourself.
- Every slice already accepted → nothing to run; tell the user and suggest `/finish-slices`.
- No state file, or no slice accepted → start at slice 1, as normal.

**State file format.** A markdown table, one row per slice in execution order, with exactly these columns:

```markdown
# run-slices state — <slug>

| slice | file | status | base_sha | accepted_sha |
|-------|------|--------|----------|--------------|
| 001 | 001-add-jwt.md | accepted | a1b2c3d | e4f5a6b |
| 002 | 002-refresh-token.md | pending | - | - |
```

`status` is `accepted` or `pending`; a `pending` row has `-` for both SHAs. Write the columns exactly as named and in this order — a later session parses this file to resume, so the format is a contract, not freeform notes.

**Commit style discovery.** Before dispatching the first implementer, infer the project's commit style from explicit instructions first (`CLAUDE.md`, `AGENTS.md`, user prompt), then from `git log --oneline -20`. Pass the discovered style and 2-3 representative examples as `Commit format`. If no clear style exists, use a short imperative subject. Never impose a slice-specific syntax by default. Commit subjects describe the actual code/product change, not delivery machinery.

## 4. Per-slice loop

For each slice, in execution order.

### 4a. Implement (sub-agent)

Run the clean working-tree check first — `git status --short` must be empty. A dirty tree mid-run means uncommitted work; stop and ask. Then record the slice base:

```bash
BASE_SHA=$(git rev-parse HEAD)
```

Spawn a fresh implementer sub-agent in the current story-branch checkout. Do not create a worktree. Do not reuse the previous slice's implementer.

Dispatch it with `implementer-prompt.md` in this skill directory — fill every field in its `## Inputs` block. A sub-agent starts with zero session history; it gets exactly what you hand it, so construct its context yourself: the full slice spec, the project commands, the branch and `BASE_SHA`, the commit format, and any interfaces or decisions from already-accepted slices it needs. Do not just point it at the slice file.

The implementer follows TDD — failing test, confirm it fails, minimal implementation, verify, refactor green, commit — and reports in prose ending with a `Status:` line.

After it returns, verify commit integrity before any gate:

```bash
git status --short
git rev-list --count "$BASE_SHA"..HEAD
git diff --stat "$BASE_SHA"..HEAD
```

`git status --short` must be empty, `rev-list --count` must be at least 1, and the diff must not include planning artifacts unless the user or project explicitly tracks them. If this fails, run the **Fix loop** with the integrity failure as the gate feedback and require a clean commit before continuing.

Then handle the implementer's `Status:` (see *Implementer status*). On `DONE` / `DONE_WITH_CONCERNS` proceed to 4b.

### 4b. Check before done

Runs automatically for every slice, in both modes. Invoke the **`check-before-done`** skill. Give it the full slice spec and acceptance criteria, the current branch, the `BASE_SHA..HEAD` diff range, the verification commands, and the latest implementer/fix-agent report. It dispatches its own fresh verification sub-agent.

- `PASS` → go to 4c.
- `FAIL` → run the **Fix loop** for this gate.
- `BLOCKED` → verification could not run. Supply what the verifier reports as missing and re-invoke `check-before-done`, or escalate to the user. Do not run the Fix loop on a `BLOCKED` gate.

### 4c. Slice review

Runs automatically for every slice, in both modes - only after 4b passes. Invoke the **`slice-review`** skill. Give it the `BASE_SHA..HEAD` diff, the full slice spec, the current branch, the repo root, and the relevant CLAUDE.md path(s). It dispatches its own fresh code-review sub-agent.

- `APPROVED` → go to 4d. If the reviewer noted Minor remarks, record them in the slice acceptance report; they do not block the slice.
- `CHANGES_REQUESTED` → run the **Fix loop** for this gate. A review fix can break behaviour, so after any fix that changed code, re-run `check-before-done` before re-running `slice-review`; if that `check-before-done` re-run fails, run the Fix loop for `check-before-done` until it is green again, then return to `slice-review`.
- `BLOCKED` → the review could not run. Supply what is missing and re-invoke `slice-review`, or escalate. Do not run the Fix loop on a `BLOCKED` gate.

### Fix loop

Used by 4a and the two gates when a check fails. Repair the slice until the check passes.

1. Capture HEAD before the fix: `PRE_FIX=$(git rev-parse HEAD)`.
2. Dispatch a fresh fix sub-agent with `fix-agent-prompt.md` — fill every field in its `## Inputs` block: the gate report, the slice spec, the `BASE_SHA..HEAD` diff, `PRE_FIX` as `Current HEAD`, the commit format, and whether any earlier fix attempt on this gate did not hold. It applies the **`handle-review-feedback`** discipline.
3. Read the fix agent's `Status:`:
   - `NEEDS_CONTEXT` / `BLOCKED` → handle as under *Implementer status*: supply the missing context and re-dispatch, or escalate to the user. Never re-dispatch unchanged. Do not continue to step 4.
   - `DONE_WITH_CONCERNS` → the fix agent disputes a gate item. Escalate the dispute to the user with the agent's `file:line` evidence and settle it before continuing — never adjudicate it yourself, never loop on a disputed item. Then continue to step 4.
   - `DONE` → continue to step 4.
4. Did code change? Compare `git rev-parse HEAD` with `PRE_FIX`:
   - **New commit** → confirm `git status --short` is empty, then re-run the gate — a fresh, independent verdict on the fix.
   - **No new commit** → with a dispute, the gate verdict already stands while the user settles it; with neither a dispute nor a blocker, it is a protocol miss — re-dispatch once with explicit instructions.
5. Gate passes → the gate is satisfied; leave the loop. Gate still fails → did this attempt make progress (a previously-failed item now resolved, or the failure genuinely narrower)? Yes → loop from step 1. No → stop and report to the user. Backstop: after 3 fix attempts on one gate without it passing, stop and report regardless.

Once an attempt on a gate has not held, tell the next fix agent — it switches to `debug-slice-failure` and root-causes instead of patching blind.

### 4d. HITL gate

If the slice's `Type` is HITL, stop and ask the user to review and approve before accepting the slice - regardless of execution mode.

### 4e. Accept the slice

The code is already committed on the story branch. In the git-excluded state file `docs/specs/<slug>/.run-slices-state.md`, update this slice's row — `status` to `accepted`, `base_sha` to the slice's `BASE_SHA`, `accepted_sha` to `git rev-parse HEAD` (see *State file format* in step 3). This is the durable resume state, and the only file `run-slices` writes outside the implementation code. Record the accepted commit range (`BASE_SHA..HEAD`) and any Minor review remarks in the session's slice acceptance report, mark the slice complete in TodoWrite, and keep going.

### 4f. Next

Step-by-step: stop here and report; continue on the user's go-ahead. Autonomous: continue immediately. Either way the next slice gets a brand-new sub-agent - no sub-agent context carries over.

## 5. After all slices

Invoke the **`finish-slices`** skill. Give it the session's slice acceptance report if available. It runs final verification on the whole story branch, summarises what shipped with slice commit ranges, assembles a PR body, and offers the delivery options (push and open a PR, keep the branch, heavyweight review, stop).

## Implementer status

The implementer sub-agent ends its report with a `Status:` line carrying one of:

- **DONE** — committed, RED/GREEN evidence shown, verification green. Proceed to 4b.
- **DONE_WITH_CONCERNS** — committed, but the implementer flagged a doubt. Read the concern; address any correctness or scope issue before 4b, otherwise note it and proceed.
- **NEEDS_CONTEXT** — supply the missing information and re-dispatch.
- **BLOCKED** — assess the blocker: supply context, use a more capable model, split the slice, or escalate to the user. Never ignore an escalation; never re-dispatch the same model with no change.

A `DONE` / `DONE_WITH_CONCERNS` report with no commit SHA, or one that fails the integrity check in 4a, is a failed commit — run the Fix loop for a clean commit before continuing.

## Model selection

Use the least powerful model that fits each role. Mechanical slices → a fast model for the implementer; judgment-heavy slices and the reviewer → a more capable model.

## Red flags — never

- Run a slice on `main` / `master`.
- Skip `check-before-done` or `slice-review`, or run them in only one mode.
- Start `slice-review` before `check-before-done` passes.
- Accept a slice while a gate still fails.
- Trust the implementer's success claim instead of verifying.
- Dispatch implementer sub-agents for multiple slices in parallel.
- Make a sub-agent read the PRD or other slice files — construct its context yourself.
- Carry context from one slice's sub-agent into the next.
- Continue after a review fix that changed code without re-running `check-before-done`.
- Start a slice while `git status --short` is dirty.
- Adjudicate a fix agent's dispute yourself instead of escalating it to the user.
- Keep dispatching fix agents at a gate that is not making progress instead of escalating.
- Use process-only commit subjects like "fix review feedback", "address verifier", "slice done", or "run-slices changes".

## Notes

- Single branch delivery: every accepted slice is represented by one or more commits on the story branch. The orchestrator uses `BASE_SHA..HEAD` as the slice boundary.
- Commit style: discover and follow the project's existing style; if none is clear, use a short imperative subject.
- Planning artifacts: treat `docs/specs/<slug>/` as uncommitted planning output by default. If the project intentionally tracks specs/docs, follow that project convention instead.
