---
name: grill-me
description: Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me".
---

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time.

If a question can be answered by exploring the codebase, explore the codebase instead.

## When the interview is complete

STOP. Do **not** automatically generate a PRD, write code, run `/to-prd`, or proceed to any next step.

1. Summarise the agreed decisions briefly (5–10 bullets max).
2. Ask the user explicitly what to do next. Offer concrete options, e.g.:
   - Run `/to-prd` to write the spec to `docs/specs/<slug>/PRD.md`
   - Continue grilling on a sub-area you flagged
   - Pause and save the summary somewhere
   - Something else

Wait for the user's choice before doing anything further. Even if the next step seems obvious, the user wants the explicit handoff.
