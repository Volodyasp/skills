---
name: debug-slice-failure
description: Use when a slice fails check-before-done or its tests a second consecutive time — stop patching and switch to root-cause debugging. Invoked by run-slices when a fix round did not hold.
---

# Debug Slice Failure

A second consecutive failure of the same gate means the fix sub-agent is guessing. Stop patching. A third speculative patch will not land the slice — it adds mess. Switch to root-cause debugging.

Invoked by `run-slices` when a slice fails `check-before-done` (or its tests) again after a fix round.

## Trigger

The same gate failed twice in a row on the same slice. The first fix was a guess, or fixed the wrong thing. Do not write another patch until you have a root cause.

## Process

1. **Reproduce.** Get one deterministic command that fails. Run it; read the *complete* output — exit code, the actual error, the failing assertion. Not a summary.
2. **Find the root cause.** Do not edit code yet. Read the error fully. Trace the bad value backward to where it originates. Check exactly what the previous fix changed — it may have masked or moved the symptom. Name the cause in one sentence.
3. **Hypothesise.** State one falsifiable hypothesis: "the failure is caused by X." Confirm it with a probe, a log, or a targeted test before fixing.
4. **Fix minimally, at the right seam.** Change one thing, where the root cause actually lives. Add a regression test that fails before the fix and passes after.
5. **Verify.** Re-run the gate's command. If green, return to `run-slices` with the root cause stated in the result.

## Escalate

If the root cause is architectural — the bug lives behind a missing seam, there is nowhere correct to put the regression test, or the fix would reach outside the slice — stop. Return `status: BLOCKED` with the root cause and escalate to the user. Suggest `/improve-codebase-architecture` for the seam, or `/diagnose` for a harder standalone investigation.

## Red flags — never

- Write another speculative patch "to see if it works".
- Widen the fix to cover symptoms you have not traced to the cause.
- Suppress the symptom — catch-and-ignore, a loosened assertion — instead of fixing the cause.
- Skip the regression test — an untested fix can silently regress in the next slice.
- Burn fix rounds guessing. `run-slices` stops the slice after the budget; a real root cause is worth more than another guess.

## Notes

- This is the escalation tier above `handle-review-feedback`: round one applies feedback with rigour; round two debugs the cause.
- Scoped cousin of `pocock-skills:diagnose`. For a hard bug that outgrows the slice, hand off to `/diagnose` and its full reproduce → minimise → hypothesise loop.
