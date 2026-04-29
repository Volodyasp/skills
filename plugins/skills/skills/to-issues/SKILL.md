---
name: to-issues
description: Break a PRD or plan into independently-grabbable vertical-slice issues as local markdown files under `docs/specs/<slug>/issues/`. Use when user wants to convert a PRD into implementation tickets for local spec-driven workflow.
---

# To Issues

Break a plan into independently-grabbable issues using **vertical slices** (tracer bullets). Each slice becomes a numbered markdown file under `docs/specs/<slug>/issues/`.

This is the second step of the local spec pipeline: `/to-prd → /to-issues → /to-ralph`.

## Process

### 1. Locate the PRD

Determine the story slug:

- If the user passes a slug as an argument, use it.
- Otherwise, list directories under `docs/specs/` and ask the user which one to decompose.
- The PRD must be at `docs/specs/<slug>/PRD.md`. If it is missing, stop and tell the user to run `/to-prd` first.

Read the PRD fully. If the PRD references prior context not in your conversation (other ADRs, related specs), read those too.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so. Issue titles and descriptions should use the project's domain glossary, and respect ADRs in the area being touched.

### 3. Draft vertical slices

Break the plan into **tracer bullet** issues. Each issue is a thin vertical slice that cuts through ALL integration layers end-to-end, NOT a horizontal slice of one layer.

Slices may be **HITL** (Human-In-The-Loop) or **AFK** (Away-From-Keyboard). HITL slices require human interaction such as an architectural decision or design review. AFK slices can be implemented and merged without human interaction. Prefer AFK over HITL where possible.

<vertical-slice-rules>
- Each slice delivers a narrow but COMPLETE path through every layer (schema, API, UI, tests)
- A completed slice is demoable or verifiable on its own
- Prefer many thin slices over few thick ones
</vertical-slice-rules>

### 4. Quiz the user

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

### 5. Write the issue files

For each approved slice, create one markdown file at:

```
docs/specs/<slug>/issues/NNN-<slice-slug>.md
```

Where:

- `NNN` is a zero-padded 3-digit number, starting from `001` if the directory is empty, otherwise `max(existing) + 1`. Scan `docs/specs/<slug>/issues/` for existing numbered files before assigning.
- `<slice-slug>` is a short kebab-case slug derived from the title (e.g. `add-jwt-validation`, `handle-expired-tokens`).
- Numbers reflect dependency order: blockers first, so `Blocked by` references can point to earlier numbers.

Use the issue body template below. Create `docs/specs/<slug>/issues/` if it doesn't exist.

<issue-template>

# <NNN> — <Title>

**Type:** HITL | AFK
**Blocked by:** None | #001, #002

## What to build

A concise description of this vertical slice. Describe end-to-end behavior, not layer-by-layer implementation.

## User stories covered

- US-<n>: <short reference to the user story from PRD>

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## Notes

Anything else relevant — prior art, related ADRs, gotchas. Omit if empty.

</issue-template>

### 6. Report

After writing all files, report to the user:

```
Wrote N issues to docs/specs/<slug>/issues/:
  001-<slug>.md  (AFK, blockers: none)
  002-<slug>.md  (AFK, blockers: #001)
  003-<slug>.md  (HITL, blockers: #001)
  ...

Next: /to-ralph to convert these into Ralph loop artifacts.
```

Do NOT modify the PRD file. Do NOT re-number existing issue files.
