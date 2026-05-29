---
name: finish-slices
description: Use after run-slices has delivered every slice of a story and the story branch needs final verification and a delivery decision — push and open a PR, keep the branch, run a heavyweight review, or stop.
---

# Finish Slices

Close out a story once `run-slices` has accepted every slice. Run final verification on the whole story branch, summarise what shipped, assemble a PR body, and let the user choose how to deliver it.

Final step of the local spec pipeline: `/to-prd → /to-slices → /run-slices → /finish-slices`.

This skill finishes a *story*, not a slice. Per-slice acceptance is `check-before-done` + `slice-review`, already done inside `run-slices`. Here the unit of work is the whole branch.

## Autonomous mode

If invoked with `autonomous` (or `afk`) among its arguments — usually because `run-slices` ran autonomously and is closing out the story — do not pause for the step 5 delivery choice. Run steps 1–4 as normal, then take the **non-outward-facing** default: keep the branch as-is, present the assembled PR body together with the exact push / PR commands, and stop with a report.

Never `git push` or open a PR in autonomous mode — that is an outward-facing action and stays an explicit human decision. An autonomous run leaves the branch verified and delivery-ready; the human runs the final push.

Stop and report — never work around it — on any genuine blocker: a dirty tree (step 1), red verification (step 2), or a missing acceptance report. A blocker is a real stop, not a pause for permission; everything else runs straight through, with no "should I continue?" check-ins.

## 1. Confirm preconditions

- The current branch is the story branch — never `main` / `master`.
- Every slice is accepted. If `run-slices` passed a slice acceptance report, trust it and confirm no slice is unfinished. If there is no report — `finish-slices` was invoked standalone, or the session was interrupted — ask the user to confirm every slice is done before proceeding; never assume it.
- `git status --short` is clean. If dirty, stop and ask — uncommitted work must not ride into the delivery decision.

## 2. Run final verification

Run the project's full verification freshly — the whole test suite, plus lint / build if the project has them. Read the complete output: exit codes, pass/fail counts, actual failures.

- All green → continue.
- Anything red → stop. Report the failures. Do NOT offer a PR or merge on a red branch. Hand the failures back so the user can re-open `run-slices` or apply `debug-slice-failure`.

## 3. Summarise what shipped

Determine the branch point (`git merge-base` with the base branch). Prefer the slice acceptance report passed by `run-slices`; it contains the exact `BASE_SHA..HEAD` range for each accepted slice.

If no acceptance report is available because the session was interrupted or `finish-slices` is being run later, reconstruct a best-effort summary:

- Read the slice files for slice number, title, and HITL / AFK type.
- Read `git log --oneline --reverse <base>..HEAD` and the whole-branch diffstat.
- Match commits to slices only when commit messages or changed files make the mapping clear.
- If a per-slice range cannot be reconstructed confidently, write `range unknown` instead of inventing one.

Build the summary from the available evidence:

- Each slice — number, title, commit range, HITL / AFK.
- The whole-branch diffstat (`git diff --stat <base>..HEAD`).

## 4. Assemble the PR body

Write a PR body with these sections:

- **Summary** — what the story delivers, in the project's domain language.
- **Slices shipped** — one line per slice: `NNN — Title`.
- **Test plan** — the verification commands from step 2 and their result.
- **Known risks** — residual risk, edge cases left for later, follow-ups. Only real items — never invent risks to fill the section; write "None identified" if there are none.

Present it. Offer to save it to a temp file (`mktemp`) so it can be passed to `gh pr create --body-file`.

## 5. Offer delivery options

In autonomous mode, skip this question — take option 2 (keep the branch as-is), present the step 4 PR body together with option 1's exact push / PR commands, and stop with a report (see *Autonomous mode* above). Otherwise, ask the user to choose:

1. **Push and open a PR** — give the exact commands: `git push -u origin <branch>` and `gh pr create --base <base> --title "<title>" --body-file <file>`. If a safety hook blocks `git push`, hand the commands to the user to run with the `!` prefix; do not retry the push yourself.
2. **Keep the branch as-is** — report the branch name and stop.
3. **Run a heavyweight review first** — suggest `/ultrareview` or `/review` over the whole branch, then return here.
4. **Stop** — report state and stop.

## Red flags — never

- Offer a PR or merge while verification is red.
- Push to `main` / `master`.
- Invent risks or test steps that did not happen.
- Claim "all slices done" without a `run-slices` acceptance report or explicit user confirmation.
- Retry a `git push` yourself when a safety hook blocks it — hand the command to the user.

## Notes

- Single-branch delivery: there is no worktree to clean up. The story branch *is* the deliverable.
- This skill prepares delivery; it does not merge to `main` on its own. The user makes the final call.
