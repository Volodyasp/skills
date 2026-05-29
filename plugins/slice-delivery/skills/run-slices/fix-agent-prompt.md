# Slice Fix Subagent Prompt Template

Use this template when a verification or review gate fails and a fresh fix
sub-agent must repair the current slice.

```
Task tool:
  description: "Fix slice {SLICE_ID}: {GATE_NAME} feedback"
  prompt: |
    You are fixing one failed gate for an already-implemented slice on the
    current story branch.

    ## Inputs

    Story slug: {STORY_SLUG}
    Slice: {SLICE_ID} - {SLICE_TITLE}
    Repo root: {REPO_ROOT}
    Current branch: {BRANCH}
    Slice base SHA: {BASE_SHA}
    Current HEAD: {HEAD_SHA}
    Gate that failed: {GATE_NAME}
    Test command: {TEST_COMMAND}
    Additional verification: {LINT_BUILD_COMMANDS_OR_NONE}
    Commit format: {COMMIT_FORMAT_OR_DEFAULT}
    Previous fix attempts on this gate: {PRIOR_FIX_ATTEMPTS_OR_NONE}

    ## Slice Spec

    {FULL_SLICE_SPEC}

    ## Gate Feedback To Fix

    {GATE_REPORT}

    ## Current Slice Diff

    Diff range: {BASE_SHA}..HEAD

    ## Hard Rules

    - Work in the current checkout and branch. Do not create worktrees or branches.
    - Fix only the gate feedback above and any directly required tests.
    - Do not rewrite the slice or add new features.
    - Do not edit or commit planning artifacts unless the project intentionally
      tracks them or you were explicitly told.

    ## Fix Discipline

    Follow the `handle-review-feedback` skill. Each feedback item is a hypothesis:
    restate it, verify it against the code, then either fix it or dispute it.

    - Fix one item at a time and run its targeted test before the next.
    - If an item is wrong or outside the slice spec, do not change code for it.
      Report it as a dispute with `file:line` evidence. The orchestrator escalates
      disputes to the user — you are surfacing it, not adjudicating it.
    - A red test, a non-zero command, or a missing required command is never a
      dispute. It is fixed with a code or test change.

    If `Previous fix attempts on this gate` shows an earlier fix did not hold, you
    are guessing — switch to the `debug-slice-failure` skill. Stop patching:
    reproduce the failure, trace the root cause, confirm one hypothesis, then make
    a single minimal fix at the right seam with a regression test. If the root
    cause is architectural, report BLOCKED with the root cause instead of guessing
    again.

    ## Verification

    If you changed code, run the narrow tests for your fix, then {TEST_COMMAND}
    and {LINT_BUILD_COMMANDS_OR_NONE}. Commit the fix on the current story branch
    using the commit format, or a plain imperative message if none is given. The
    subject must describe the actual code change, not the gate process — avoid
    "fix review feedback", "address verifier", "run-slices changes".

    Before reporting, `git status --short` must be empty. If you changed no code
    (you dispute every item), make no commit and `git rev-parse HEAD` must still
    equal the input `Current HEAD`.

    ## How To Report

    Report in prose, then end with one status line. In the prose include:

    - Each item: fixed (name the commit and the test that now passes) or disputed
      (give the `file:line` code, test, or slice-spec evidence that shows it is
      wrong or out of scope).
    - Each verification command you ran, with its exit code and pass/fail count.

    End with exactly this line and nothing after it:

        Status: <STATUS> · Commit: <sha or none>

    STATUS is one of: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED.

    - DONE — every item fixed, verification green, committed.
    - DONE_WITH_CONCERNS — you disputed at least one item. `Commit` is a sha if you
      also committed fixes, or `none` if you disputed everything.
    - NEEDS_CONTEXT — you need information that was not provided.
    - BLOCKED — the root cause is architectural or otherwise outside this slice;
      state it.
```
