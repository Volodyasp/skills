---
name: check-before-done
description: Use when a slice, task, or change is claimed done and must be verified against its definition of done before it is accepted, merged, or reported complete.
---

# Check Before Done

Verify a unit of work is genuinely complete against evidence, not claims. Dispatch a fresh verification sub-agent with its own context, so the check is independent of whoever did the work.

**Iron law:** evidence before claims. No "done" without fresh verification output.

## Inputs

- **Definition of done** — a slice's full spec plus `## Acceptance criteria`, or an explicit checklist.
- **Work location** — the branch, repo path, and diff range to verify (for slices, usually `BASE_SHA..HEAD`).
- **Verification commands** — test command, and any lint / build.
- **Implementer/fix-agent report** — the latest sub-agent report, used to cross-check the commit and the RED/GREEN evidence.

## Process

Dispatch a **fresh verification sub-agent**. It must not be the agent that did the work and must not inherit its context — construct exactly what it needs from the inputs above. Use `verifier-prompt.md` in this skill directory as the dispatch template. Instruct it to:

1. **Identify** the command that proves each item of the definition of done.
2. **Run** every verification command freshly — never report from memory or a prior run.
3. **Read** the complete output: exit codes, pass/fail counts, the actual failures.
4. **Inspect** the diff range when a requirement cannot be proven by command output alone.
5. **Confirm** each item is genuinely satisfied — map each to its evidence.
6. **Report** pass/fail per item, with the supporting output quoted or summarized. If anything fails, say exactly what.

## Result

The verifier reports in prose and ends with a status line — `Status: <PASS|FAIL|BLOCKED> · Commit: <sha>`:

- **PASS** — every item is satisfied and fresh evidence is shown.
- **FAIL** — at least one item fails or has no evidence. The prose names each failed item with `file:line` and the reason.
- **BLOCKED** — verification cannot run because context, commands, dependencies, or environment are missing.

The prose must show the exact commands run with their exit codes and pass/fail counts. If the verifier cannot run the commands at all, the result is BLOCKED.

## Red flags — never

- Trust a "done" / "should pass" / "looks good" claim without running the command.
- Report a prior run's output instead of a fresh one.
- Pass an item that has no command output behind it.
- Let the agent that did the work also verify it.
- Return prose like "looks good" instead of the `Status:` line.
