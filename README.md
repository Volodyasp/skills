# skills

My personal Claude Code skills marketplace — curated forks and authored skills that I use for AI-assisted development.

## About

A working repo, not a polished public product. I keep it on GitHub so I can install on any machine (`claude plugin marketplace add Volodyasp/skills`) and track adaptations as I tweak things over time.

The skills here support a **spec-driven workflow**:

1. Plan a feature with `/grill-me` — interview-style stress test of the idea
2. Write a spec via `/to-prd` — synthesises conversation context into a PRD
3. Decompose into vertical slices via `/to-slices` — tracer-bullet tickets
4. Hand off to a runner — Ralph loop, manual, worktree-parallelism, whatever fits

Everything lands as plain markdown under `docs/specs/<slug>/` — no coupling to GitHub Issues, Azure DevOps, Linear, or any tracker. That makes the pipeline portable across projects (I work across multiple trackers) and leaves me with artifacts I can read, edit, and review by hand.

Most skills here are forks from [mattpocock/skills](https://github.com/mattpocock/skills) — Matt's foundational engineering skills, adapted to drop the GitHub-Issues-coupling and write to local markdown instead. Future plugins in this marketplace will hold my own authored skills (e.g. `/to-ralph` for handing slices to [Ralph loop](https://github.com/frankbria/ralph-claude-code)).

## Plugins

| Plugin | Description |
|---|---|
| [`pocock-skills`](./plugins/pocock-skills/) | Curated subset of [mattpocock/skills](https://github.com/mattpocock/skills) with local-markdown adaptations. Spec-driven engineering pipeline: `grill-me → to-prd → to-slices`, plus `tdd`, `diagnose`, `zoom-out`, `improve-codebase-architecture`. |
| [`safety-hooks`](./plugins/safety-hooks/) | `PreToolUse` hooks that block destructive git commands (`push`, `--force`, `reset --hard`, `--no-verify`, etc.) and access to secret files. Per-project whitelist via `.claude/safety-hooks.local.md`. |

More plugins to come (personal authored skills, additional curated forks).

## Installation

Add the marketplace once:

```bash
claude plugin marketplace add Volodyasp/skills
```

Then install the plugins you want:

```bash
claude plugin install pocock-skills@skills
claude plugin install safety-hooks@skills
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
                <your runner of choice — Ralph loop, worktree, manual, etc.>
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

## Attribution

`pocock-skills` derives from [mattpocock/skills](https://github.com/mattpocock/skills) by Matt Pocock, distributed under MIT — see [LICENSE](LICENSE).

For the full upstream collection (including skills not selected here), see the source.
