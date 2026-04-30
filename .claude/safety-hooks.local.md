---
allow:
  - "git push"
---

# Safety hooks whitelist for Volodyasp/skills

This repo gets pushed multiple times per session during normal development of the
plugins inside it. The default safety-hooks block on `git push` adds friction
without protecting anything (the repo has no production deploys gated on push).

`push --force` and other dangerous patterns remain blocked.
