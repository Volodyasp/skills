# skills

Curated Claude Code skills for Python/FastAPI/RAG/agent development.

A personal selection from [mattpocock/skills](https://github.com/mattpocock/skills) with my own adaptations. Designed around the spec-driven AFK workflow: brainstorm → plan → vertical-slice → implement.

## Pipeline

```
/grill-me      → stress-test the plan with interview-style questions
/to-prd        → write PRD to docs/specs/<slug>/PRD.md
/to-issues     → break PRD into vertical-slice issues
                 under docs/specs/<slug>/issues/NNN-<slug>.md
                  ↓
                /to-ralph (separate skill) → Ralph loop artifacts
                  ↓
                ralph (frankbria/ralph-claude-code) implements
                  ↓
/diagnose      → debug if something breaks
```

All artifacts are local markdown — no GitHub Issues / Azure DevOps coupling.

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
| `to-prd` | Convert conversation context into a PRD document |
| `to-issues` | Decompose PRD into vertical-slice issues |
| `tdd` | Test-driven development discipline |
| `diagnose` | Disciplined debug loop for hard bugs and performance regressions |
| `zoom-out` | Map an unfamiliar codebase area to higher-level abstractions |
| `improve-codebase-architecture` | Find deepening opportunities, informed by CONTEXT.md and ADRs |

## Attribution

Original skills authored by [Matt Pocock](https://github.com/mattpocock). Distributed under MIT — see [LICENSE](LICENSE).

This repo represents a curated subset with selection choices appropriate for solo Python/RAG development. For the full collection (including skills not included here), see the upstream.

## Conventions

`to-prd` and `to-issues` write everything to local markdown under `docs/specs/<slug>/`. They do not call `gh issue create` or any other tracker. This makes the pipeline portable across GitHub / Azure DevOps / Linear / no tracker at all — issues are just files in your repo.

Layout:

```
docs/specs/<story-slug>/
  PRD.md                       # from /to-prd
  issues/
    001-<slice-slug>.md        # from /to-issues
    002-<slice-slug>.md
    ...
```
