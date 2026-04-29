# skills

A curated subset of [mattpocock/skills](https://github.com/mattpocock/skills) plus my own adaptations. Designed for spec-driven engineering with AI agents — brainstorm, plan, slice, implement.

## Pipeline

The main flow: spec it, slice it, hand it off to a runner.

```
/grill-me      → stress-test the plan with interview-style questions
/to-prd        → write PRD to docs/specs/<slug>/PRD.md
/to-issues     → break PRD into vertical-slice issues
                 under docs/specs/<slug>/issues/NNN-<slug>.md
                  ↓
                <your runner of choice — Ralph loop, worktree, manual, etc.>
                  ↓
/diagnose      → debug if something breaks
```

All artifacts are local markdown — no coupling to GitHub Issues, Azure DevOps, Linear, or any tracker. Issues are just files in your repo.

Plus utility skills:

- `/zoom-out` — get a higher-level map of an unfamiliar area
- `/improve-codebase-architecture` — find deepening opportunities
- `/tdd` — discipline for red-green-refactor

## Installation

As a Claude Code plugin:

```bash
claude plugin marketplace add Volodyasp/skills
claude plugin install skills@skills
```

After install, restart Claude Code. The skills become available as `/grill-me`, `/to-prd`, etc.

## Skills included

| Skill | Purpose |
|---|---|
| `grill-me` | Interview-style stress-test of a plan or design |
| `to-prd` | Convert conversation context into a PRD (local markdown) |
| `to-issues` | Decompose PRD into vertical-slice issues (local markdown) |
| `tdd` | Test-driven development discipline |
| `diagnose` | Disciplined debug loop for hard bugs and performance regressions |
| `zoom-out` | Map an unfamiliar codebase area to higher-level abstractions |
| `improve-codebase-architecture` | Find deepening opportunities, informed by CONTEXT.md and ADRs |

## Layout convention

```
docs/specs/<story-slug>/
  PRD.md                       # from /to-prd
  issues/
    001-<slice-slug>.md        # from /to-issues
    002-<slice-slug>.md
    ...
```

Portable across any tracker (or no tracker at all).

## Differences from upstream

- **Curated**: 7 skills selected from the larger upstream set.
- **`to-prd` and `to-issues` write to local markdown** instead of `gh issue create`. Outputs land in `docs/specs/<slug>/`.
- **Plugin packaging**: distributable via `claude plugin marketplace add`.

## Attribution

Original skills authored by [Matt Pocock](https://github.com/mattpocock). Distributed under MIT — see [LICENSE](LICENSE).

For the full collection (including skills not selected here), see the upstream.
