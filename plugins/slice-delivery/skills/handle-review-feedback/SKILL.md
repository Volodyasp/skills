---
name: handle-review-feedback
description: Use when a fix sub-agent must act on check-before-done or slice-review feedback — verify each item against the code, fix the valid ones, dispute the wrong or out-of-scope ones with evidence. Invoked by run-slices on a failed gate.
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
   - **Wrong, or outside the slice spec** → do not change the code. Record it as a dispute: `file:line`, what was suggested, and the evidence (code, test, or slice spec) for why it is wrong or out of scope.
   - **Unclear** → ask; do not guess.
4. **Fix one item, then verify it.** Run the targeted test for that item before moving to the next. Never batch several fixes into one unverified change.

## Disputes go to the user, not to you

A dispute is for **judgement** calls — a criterion the gate read wrongly, a criterion it marked unproven that the evidence does satisfy, a requirement outside the slice's `## What to build`, a code-quality opinion not in the slice spec.

You do not resolve a dispute. You surface it: report it with `file:line` evidence, and `run-slices` escalates it to the user, who decides. Do not argue it in a loop, and do not silently comply with something you believe is wrong.

A dispute does **not** fit objective failures. A red test, a command that exits non-zero, or a missing required command is not a difference of opinion — it is fixed with a code or test change. If you believe a *test* is wrong, correcting the test is still a change, not a dispute. You cannot leave a gate's objective failure in place and call the slice done.

## Scope discipline

Every fix must trace to a gate item and to the slice's `## What to build`. A "nicer" or "more professional" suggestion that is not in the slice spec is scope creep — dispute it, do not silently comply. Scope expansion belongs in a new slice, not this fix round.

## Result

Report in prose, ending with the `Status:` line from `fix-agent-prompt.md`. For each feedback item, say whether it was **fixed** (name the commit and the passing test) or **disputed** (give the `file:line` evidence). Set `Status: DONE_WITH_CONCERNS` when any item was disputed, so `run-slices` escalates it. If you disputed every item and changed no code, make no commit and report `Commit: none`.

## Escalation

This is the default discipline for the first fix attempt at a gate. If a previous fix attempt on the same gate did not hold, patching is no longer working — switch to `debug-slice-failure` and root-cause the failure before changing more code.

## Red flags — never

- Change code to satisfy a feedback item you have not verified.
- Performative agreement — "good catch", "you're right" — instead of evidence.
- Batch multiple fixes into one untested commit.
- Let a review comment expand the slice beyond its spec.
- Silently comply with a feedback item you believe is wrong — dispute it with evidence.
- Argue a dispute in a loop — surface it once, with evidence, and let the user decide.
