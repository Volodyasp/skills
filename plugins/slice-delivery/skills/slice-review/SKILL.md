---
name: slice-review
description: Use after a slice or focused change has passed verification and needs a light code-quality review before acceptance.
---

# Slice Review

Review one slice's code for quality. Dispatch a single fresh code-review sub-agent: fresh eyes, separate context, not the agent that wrote the code.

This is a **light** review — one focused reviewer. The heavyweight multi-agent review (`/ultrareview`, `/review`) is for the whole story branch at the end, not per slice.

## Inputs

- The **diff range** for the slice, usually `BASE_SHA..HEAD`.
- The **slice spec** — `## What to build` and `## Acceptance criteria` — so the reviewer can judge scope.
- The **repo root** and relevant CLAUDE.md path(s), so project conventions can be checked.
- The `check-before-done` PASS report.

## Process

Dispatch **one fresh code-review sub-agent**. It must not be the implementer and must not inherit the implementer's context. Give it the diff range, slice spec, repo root, CLAUDE.md path(s), and verifier PASS report. It checks:

Use `reviewer-prompt.md` in this skill directory as the dispatch template.

- **Bugs** — logic errors, missed edge cases, error handling that silently swallows failures.
- **Project conventions** — read the provided CLAUDE.md path(s); match the surrounding code.
- **Leftover cruft** — debug prints, commented-out code, stray TODOs that are not intentional documented seams.
- **Scope creep** — every changed line should trace to the slice's `## What to build`; flag changes that do not.
- **Test quality** — tests should exercise real behavior and include the slice's important edge cases.

It returns one status:

- **APPROVED** — no blocking issues.
- **CHANGES_REQUESTED** — concrete issues must be fixed before accepting the slice.
- **BLOCKED** — review cannot proceed because required context, diff, or files are missing.

## Result

Required report fields:

- `status`: `APPROVED`, `CHANGES_REQUESTED`, or `BLOCKED`
- `commit_sha`: HEAD SHA reviewed, or `null`
- `commands_run`: exact commands/inspections used for review
- `red_green_evidence`: TDD evidence status from verifier PASS report, or marked not applicable
- `issues`: each issue with severity, `file:line`, why it matters, and what to change
- `fix_request`: concise instructions for the fix agent when status is `CHANGES_REQUESTED`

If the reviewer cannot produce this block, the result is BLOCKED.

## Red flags — never

- Review code that has not passed `check-before-done` first.
- Let the implementer review its own slice.
- Spawn a heavyweight multi-agent reviewer per slice — that is the whole-story review.
- Approve without reading the diff range.
- Check project conventions without reading the provided CLAUDE.md path(s).
- Omit any required top-level key from the machine-readable result.

## Notes

Functional correctness — "does it do what the slice asked", tests green — is `check-before-done`'s job; run that first. This skill assumes the work already passes its acceptance criteria and reviews *how* it is written.
