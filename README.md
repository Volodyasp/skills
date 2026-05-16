# skills

My personal Claude Code skills marketplace — curated forks and authored skills that I use for AI-assisted development.

## About

A working repo, not a polished public product. I keep it on GitHub so I can install on any machine (`claude plugin marketplace add Volodyasp/skills`) and track adaptations as I tweak things over time.

The skills here support a **spec-driven workflow**:

1. Plan a feature with `/grill-me` — interview-style stress test of the idea
2. Write a spec via `/to-prd` — synthesises conversation context into a PRD
3. Decompose into vertical slices via `/to-slices` — tracer-bullet tickets
4. Run the slices with `/run-slices` — a fresh implementer sub-agent per slice, TDD, then two quality gates before each is accepted
5. Close out the story with `/finish-slices` — final verification, a PR body, and a delivery decision

Everything lands as plain markdown under `docs/specs/<slug>/` — no coupling to GitHub Issues, Azure DevOps, Linear, or any tracker. That makes the pipeline portable across projects (I work across multiple trackers) and leaves me with artifacts I can read, edit, and review by hand.

Most skills in `pocock-skills` are forks from [mattpocock/skills](https://github.com/mattpocock/skills) — Matt's foundational engineering skills, adapted to drop the GitHub-Issues-coupling and write to local markdown instead. `slice-delivery` is the authored execution half: it runs the slices that `pocock-skills` plans.

## Plugins

| Plugin | Description |
|---|---|
| [`pocock-skills`](./plugins/pocock-skills/) | Curated subset of [mattpocock/skills](https://github.com/mattpocock/skills) with local-markdown adaptations. Spec-driven engineering pipeline: `grill-me → to-prd → to-slices`, plus `tdd`, `diagnose`, `zoom-out`, `improve-codebase-architecture`. |
| [`slice-delivery`](./plugins/slice-delivery/) | Execution half of the pipeline. `run-slices` drives slice-by-slice delivery on one story branch — a fresh implementer sub-agent per slice, TDD, two gates (`check-before-done`, `slice-review`), disciplined fix rounds (`handle-review-feedback`, `debug-slice-failure`), and `finish-slices` to close out the story. |
| [`safety-hooks`](./plugins/safety-hooks/) | `PreToolUse` hooks that block destructive git commands (`push`, `--force`, `reset --hard`, `--no-verify`, etc.) and access to secret files. Per-project whitelist via `.claude/safety-hooks.local.md`. |
| [`python-quality-hooks`](./plugins/python-quality-hooks/) | `PostToolUse` hooks for Python files. On `Edit`: `ruff` bugs-only check + `mypy`. On `Write`: `ruff` isort-fix + format, then the same checks. Non-blocking — feedback only. |

More plugins to come (personal authored skills, additional curated forks).

## Installation

Add the marketplace once:

```bash
claude plugin marketplace add Volodyasp/skills
```

Then install the plugins you want:

```bash
claude plugin install pocock-skills@skills
claude plugin install slice-delivery@skills
claude plugin install safety-hooks@skills
claude plugin install python-quality-hooks@skills
```

Restart Claude Code after install.

## pocock-skills reference

Pipeline overview:

```
/grill-me      → stress-test the plan with interview-style questions
/to-prd        → write PRD to docs/specs/<slug>/PRD.md
/to-slices     → break PRD into vertical-slice tickets
                 under docs/specs/<slug>/slices/NNN-<slug>.md
                  ↓
/run-slices    → execute the slices (slice-delivery plugin)
                  ↓
/diagnose      → debug if something breaks
```

Utility skills (used independently of the pipeline):

- `/zoom-out` — get a higher-level map of an unfamiliar area
- `/improve-codebase-architecture` — find deepening opportunities
- `/tdd` — discipline for red-green-refactor

Layout convention:

```
docs/specs/<story-slug>/
  PRD.md                       # from /to-prd
  slices/
    001-<slice-slug>.md        # from /to-slices
    002-<slice-slug>.md
    ...
```

## slice-delivery reference

`slice-delivery` executes the slices that `pocock-skills` plans. Each slice runs
on one story branch through a fresh sub-agent and two gates:

```
/run-slices            → orchestrate slice-by-slice delivery on the story branch
  per slice:
    implementer        → fresh sub-agent: test-first (red-green-refactor), commit
    /check-before-done → fresh verifier: runs tests/lint freshly, evidence per criterion
    /slice-review      → fresh reviewer: bugs, conventions, leftover cruft, scope creep
    on a failed gate:
      /handle-review-feedback → fix round: verify each item, push back if wrong
      /debug-slice-failure    → second failure: root-cause instead of patching
/finish-slices         → after all slices: final verification, PR body, delivery
```

Run modes: **step-by-step** (pause and report after each slice) or **autonomous**
(run back-to-back, pause only at HITL slices or on a failure that survives the
retry budget). Both gates run for every slice in both modes.

## Attribution

`pocock-skills` derives from [mattpocock/skills](https://github.com/mattpocock/skills) by Matt Pocock, distributed under MIT — see [LICENSE](LICENSE).

For the full upstream collection (including skills not selected here), see the source.
