# skills

Vladimir Suponin's Claude Code skills marketplace. Home for curated forks and personal authored skills.

## Plugins

| Plugin | Description |
|---|---|
| [`pocock-skills`](./plugins/pocock-skills/) | Curated subset of [mattpocock/skills](https://github.com/mattpocock/skills) with local-markdown adaptations. Spec-driven engineering pipeline: `grill-me → to-prd → to-issues`, plus `tdd`, `diagnose`, `zoom-out`, `improve-codebase-architecture`. |

More plugins to come (personal authored skills, additional curated forks).

## Installation

Add the marketplace once:

```bash
claude plugin marketplace add Volodyasp/skills
```

Then install the plugins you want:

```bash
claude plugin install pocock-skills@skills
```

Restart Claude Code after install.

## pocock-skills pipeline

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

### Layout convention

```
docs/specs/<story-slug>/
  PRD.md                       # from /to-prd
  issues/
    001-<slice-slug>.md        # from /to-issues
    002-<slice-slug>.md
    ...
```

Portable across any tracker (or no tracker at all).

## Attribution

`pocock-skills` derives from [mattpocock/skills](https://github.com/mattpocock/skills) by Matt Pocock, distributed under MIT — see [LICENSE](LICENSE).

For the full upstream collection (including skills not selected here), see the source.
