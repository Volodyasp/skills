---
name: to-slices
description: Break a PRD or plan into independently-grabbable vertical-slice tickets as local markdown files under `docs/specs/<slug>/slices/`. Use when user wants to decompose a PRD into vertical slices, tracer-bullet tickets, or implementation work units for local spec-driven workflow.
---

# To Slices

Break a plan into independently-grabbable tickets using **vertical slices** (tracer bullets). Each slice becomes a numbered markdown file under `docs/specs/<slug>/slices/`.

This is the second step of the local spec pipeline: `/to-prd → /to-slices → /run-slices → /finish-slices`.

A slice file is a **contract**, not a sketch. `/run-slices` hands it to a fresh implementer sub-agent that never reads the PRD or any other slice file — the agent gets only what the slice itself carries. Write each slice so that agent has everything it needs and nothing it must guess.

## Process

### 1. Locate the PRD

Determine the story slug:

- If the user passes a slug as an argument, use it.
- Otherwise, list directories under `docs/specs/` and ask the user which one to decompose.
- The PRD must be at `docs/specs/<slug>/PRD.md`. If it is missing, stop and tell the user to run `/to-prd` first.

Read the PRD fully. If the PRD references prior context not in your conversation (other ADRs, related specs), read those too.

### 2. Explore the codebase

If you have not already explored the codebase, do so. Slice titles and descriptions should use the project's domain glossary, and respect ADRs in the area being touched.

### 3. Map the module and file structure

Before drafting slices, map out the modules and files the work will create or modify, and what each one is responsible for. This is where decomposition decisions get locked in.

- Design units with clear boundaries and well-defined interfaces — one clear responsibility each.
- Files that change together live together. Split by responsibility, not by technical layer.
- In an existing codebase, follow established patterns — do not unilaterally restructure.

Hold the PRD's `Implementation Decisions` and `Testing Decisions` next to this map — interfaces, contracts, schema, architectural and testing choices. They do not travel on their own: each slice that depends on a decision must carry it (step 7, `## Context & decisions`).

### 4. Draft vertical slices

Break the plan into **tracer bullet** slices. Each slice is a thin vertical cut through every layer the change actually touches end-to-end, NOT a horizontal slice of one layer.

Slices may be **HITL** (Human-In-The-Loop) or **AFK** (Away-From-Keyboard). HITL slices require human interaction such as an architectural decision or design review. AFK slices can be implemented and merged without human interaction. Prefer AFK over HITL where possible.

<vertical-slice-rules>
- Each slice delivers a narrow but COMPLETE path through every layer it touches — data, API, UI, CLI, tests, whichever apply. Never a horizontal slice of one layer.
- A completed slice is demoable or verifiable on its own.
- Each slice is independently valuable — small, but never so small it ships nothing a person would care about.
- Prefer many thin slices over few thick ones, down to that "independently valuable" floor and no further.
</vertical-slice-rules>

### 5. Self-review the breakdown

Before presenting anything, review the draft breakdown with fresh eyes. This is a checklist you run yourself — not a sub-agent dispatch.

1. **Story coverage** — can every user story in the PRD be traced to a slice? List gaps; add slices to close them.
2. **Dependency order** — does each `Blocked by` point only at lower-numbered slices? No cycles? Do the numbers reflect dependency order?
3. **Concrete criteria** — is every acceptance criterion checkable? No "works nicely", no "handles edge cases". Rewrite vague ones (see step 7).
4. **Real layers only** — does each slice cut through layers the change genuinely touches, not invented ones?
5. **Independently valuable** — is each slice small yet still worth delivering on its own?

Fix issues inline, then proceed.

### 6. Quiz the user

Present the proposed breakdown as a numbered list. For each slice, show:

- **Title**: short descriptive name (will become the filename slug)
- **Type**: HITL / AFK
- **Blocked by**: which other slices (if any) must complete first
- **User stories covered**: which user stories from the PRD this addresses

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the dependency relationships correct?
- Should any slices be merged or split further?
- Are HITL/AFK markings correct?

Iterate until the user approves the breakdown.

### 7. Write the slice files

For each approved slice, create one markdown file at:

```
docs/specs/<slug>/slices/NNN-<slice-slug>.md
```

Where:

- `NNN` is a zero-padded 3-digit number, starting from `001` if the directory is empty, otherwise `max(existing) + 1`. Scan `docs/specs/<slug>/slices/` for existing numbered files before assigning.
- `<slice-slug>` is a short kebab-case slug derived from the title (e.g. `add-jwt-validation`, `handle-expired-tokens`).
- Numbers reflect dependency order: blockers first, so `Blocked by` references can point to earlier numbers.

Acceptance criteria are the contract `check-before-done` verifies against — each must be provable with fresh evidence. Write them concrete:

<no-placeholders>
- Each criterion is a concrete, checkable statement — a command that passes, a status code, an observable output, a file that exists.
- Banned: "works nicely", "handles edge cases", "robust", "appropriate error handling" — none of these can be verified.
- Banned: criteria that reference a type, endpoint, or behavior not described in `What to build` or `Context & decisions`.
- A criterion a reviewer could not turn into a test is a slice failure — rewrite it.
</no-placeholders>

Use the slice body template below. Create `docs/specs/<slug>/slices/` if it doesn't exist.

<slice-template>

# <NNN> — <Title>

**Type:** HITL | AFK
**Blocked by:** None | #001, #002

## What to build

A concise description of this vertical slice. Describe end-to-end behavior, not layer-by-layer implementation.

## Context & decisions

The implementation and testing decisions this slice depends on — interfaces, API contracts, schema, conventions, architectural choices — copied from the PRD, plus any interface established by an earlier slice this one builds on. Copy them in full. The implementer never reads the PRD or other slice files; a decision that is not in this section does not reach it. Omit the section only if the slice genuinely depends on nothing beyond `What to build`.

## Files

The files this slice creates, modifies, or tests — exact paths where known; for a not-yet-existing module, the path you intend. Mark each `Create` / `Modify` / `Test`.

## User stories covered

- US-<n>: <short reference to the user story from PRD>

## Acceptance criteria

- [ ] <concrete, checkable criterion>
- [ ] <concrete, checkable criterion>

## Notes

Anything else relevant — prior art, related ADRs, gotchas. Omit if empty.

</slice-template>

### 8. Report

After writing all files, report to the user:

```
Wrote N slices to docs/specs/<slug>/slices/:
  001-<slug>.md  (AFK, blockers: none)
  002-<slug>.md  (AFK, blockers: #001)
  003-<slug>.md  (HITL, blockers: #001)
  ...

Next: /run-slices to implement the slices on a story branch.
```

Do NOT modify the PRD file. Do NOT re-number existing slice files.
