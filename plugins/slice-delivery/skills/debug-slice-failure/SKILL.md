---
name: debug-slice-failure
description: Use when a fix on a slice gate did not hold — stop patching and switch to root-cause debugging. The fix sub-agent reaches for this when its previous fix on the gate failed again.
---

# Debug Slice Failure

A fix that did not hold means the previous attempt was a guess, or fixed the wrong thing. Stop patching. A third speculative patch will not land the slice — it adds mess. Switch to root-cause debugging.

A fix sub-agent reaches for this skill when `run-slices` tells it an earlier fix attempt on the same gate did not hold.

## Trigger

An earlier fix attempt on this gate did not hold — the gate failed again after it. Do not write another patch until you have a root cause.

## Process

1. **Reproduce.** Get one deterministic command that fails. Run it; read the *complete* output — exit code, the actual error, the failing assertion. Not a summary.
2. **Find the root cause.** Do not edit code yet. Read the error fully. Trace the bad value backward to where it originates. Check exactly what the previous fix changed — it may have masked or moved the symptom. Name the cause in one sentence.
3. **Hypothesise.** State one falsifiable hypothesis: "the failure is caused by X." Confirm it with a probe, a log, or a targeted test before fixing.
4. **Fix minimally, at the right seam.** Change one thing, where the root cause actually lives. Add a regression test that fails before the fix and passes after.
5. **Verify.** Re-run the gate's command. If green, return to `run-slices` with the root cause stated in the result.

## Escalate

If the root cause is architectural — the bug lives behind a missing seam, there is nowhere correct to put the regression test, or the fix would reach outside the slice — stop. Report `Status: BLOCKED` with the root cause; `run-slices` escalates it to the user. Suggest `/improve-codebase-architecture` for the seam, or `/diagnose` for a harder standalone investigation.

## Red flags — never

- Write another speculative patch "to see if it works".
- Widen the fix to cover symptoms you have not traced to the cause.
- Suppress the symptom — catch-and-ignore, a loosened assertion — instead of fixing the cause.
- Skip the regression test — an untested fix can silently regress in the next slice.
- Burn fix attempts guessing. `run-slices` stops the slice when a gate stops making progress; a real root cause is worth more than another guess.

## Notes

- This is the escalation tier above `handle-review-feedback`: the first fix attempt applies feedback with rigour; once a fix has not held, debug the cause.
- Scoped cousin of `pocock-skills:diagnose`. For a hard bug that outgrows the slice, hand off to `/diagnose` and its full reproduce → minimise → hypothesise loop.
