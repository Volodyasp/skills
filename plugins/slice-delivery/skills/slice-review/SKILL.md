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
- The **repo root** and the project's convention doc path(s) (`CLAUDE.md`, `AGENTS.md`, or equivalent), so project conventions can be checked.

## Process

Dispatch **one fresh code-review sub-agent**. It must not be the implementer and must not inherit the implementer's context. Use `reviewer-prompt.md` in this skill directory as the dispatch template. Give it the diff range, slice spec, repo root, and convention doc path(s). It checks:

- **Bugs** — logic errors, missed edge cases, error handling that silently swallows failures.
- **Project conventions** — read the provided convention docs; match the surrounding code.
- **Leftover cruft** — debug prints, commented-out code, stray TODOs that are not intentional documented seams.
- **Scope creep** — every changed line should trace to the slice's `## What to build`; flag changes that do not.
- **Test quality** — tests should exercise real behavior and include the slice's important edge cases.

## Result

The reviewer reports in prose and ends with a status line — `Status: <APPROVED|CHANGES_REQUESTED|BLOCKED> · Commit: <sha>`:

- **APPROVED** — no Critical or Important issues. Any Minor remarks are listed in the prose; they do not block the slice.
- **CHANGES_REQUESTED** — at least one Critical or Important issue must be fixed before accepting the slice. The prose names each with `file:line` and what to change.
- **BLOCKED** — review cannot proceed because required context, diff, or files are missing.

## Red flags — never

- Review code that has not passed `check-before-done` first.
- Let the implementer review its own slice.
- Spawn a heavyweight multi-agent reviewer per slice — that is the whole-story review.
- Approve without reading the diff range.
- Check project conventions without reading the provided convention docs.
- Return prose like "looks fine" instead of the `Status:` line.

## Notes

Functional correctness — "does it do what the slice asked", tests green — is `check-before-done`'s job; run that first. This skill assumes the work already passes its acceptance criteria and reviews *how* it is written.
