---
name: handle-review-feedback
description: Use when a fix sub-agent must act on check-before-done or slice-review feedback — verify each item against the code, push back on wrong or out-of-scope items with evidence, fix one at a time. Invoked by run-slices on a failed gate.
---

# Handle Review Feedback

Act on gate feedback (from `check-before-done` or `slice-review`) with technical rigour. Feedback is a hypothesis to evaluate, not an order to execute. Blind compliance turns a wrong review comment into a real bug and lets a reviewer pull the slice out of scope.

Invoked by `run-slices` when a gate fails and a fix sub-agent is dispatched.

## Process

Work the feedback one item at a time. For each item:

1. **Restate** the item in your own words. If you cannot, it is unclear — ask before touching code.
2. **Verify it against the code.** Is it correct for *this* codebase? Would the change break existing behaviour? Is there a reason the current code is the way it is? Read the code; do not assume the reviewer is right.
3. **Decide:**
   - **Valid** → fix it.
   - **Wrong, or outside the slice spec** → do not change the code. Return a structured pushback: `file:line`, what was suggested, and the evidence (code, test, or slice spec) for why it is wrong or out of scope.
   - **Unclear** → ask; do not guess.
4. **Fix one item, then verify it.** Run the targeted test for that item before moving to the next. Never batch several fixes into one unverified change.

## What you can push back on

Pushback fits **judgement** calls — a criterion the gate read wrongly, a criterion it marked unproven that the evidence does satisfy, a requirement outside the slice's `## What to build`, a code-quality opinion not in the slice spec.

It does **not** fit objective failures. A red test, a command that exits non-zero, or a missing required command is not a difference of opinion — it is fixed with a code or test change. If you believe a *test* is wrong, correcting the test is still a change, not a pushback. You cannot leave a gate's objective failure in place and call the slice done.

## Scope discipline

Every fix must trace to a gate item and to the slice's `## What to build`. A "nicer" or "more professional" suggestion that is not in the slice spec is scope creep — push back, do not silently comply. Scope expansion belongs in a new slice, not this fix round.

## Result

For each feedback item: **fixed** (with the commit) or **pushed back** (with evidence). Report both in the fix sub-agent's YAML result - fixes under `commands_run` / `commit_sha`, rejected items under `issues` with the evidence. Set `status: DONE_WITH_CONCERNS` when any item was pushed back, so `run-slices` can adjudicate.

Pushback-only result: if no code changes are required, make no commit. Return `commit_sha: null` and prove no code changed — `commands_run` must show `git rev-parse HEAD` still equal to the input `Current HEAD` and `git status --short` clean. Put the rejected items and their evidence under `issues`.

## Red flags — never

- Change code to satisfy a feedback item you have not verified.
- Performative agreement — "good catch", "you're right" — instead of evidence.
- Batch multiple fixes into one untested commit.
- Let a review comment expand the slice beyond its spec.
- Stay silent on a feedback item you believe is wrong — push back with evidence.

## Notes

- This is the default discipline for every fix round. On a *second consecutive* failure of the same gate, escalate to `debug-slice-failure` — patching is no longer working.
- Pushback is not refusal to work: it is returning a technical disagreement with evidence so the orchestrator, or the user, can decide.
