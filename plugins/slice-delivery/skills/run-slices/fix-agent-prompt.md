# Slice Fix Subagent Prompt Template

Use this template when a verification or review gate fails and a fresh fix sub-agent must repair the current slice.

```
Task tool:
  description: "Fix slice {SLICE_ID}: {GATE_NAME} feedback"
  prompt: |
    You are fixing one failed gate for an already-implemented slice on the current story branch.

    ## Inputs

    Story slug: {STORY_SLUG}
    Slice: {SLICE_ID} - {SLICE_TITLE}
    Repo root: {REPO_ROOT}
    Current branch: {BRANCH}
    Original slice base SHA: {BASE_SHA}
    Current HEAD: {HEAD_SHA}
    Gate that failed: {GATE_NAME}
    Fix round: {FIX_ROUND}
    Commit format: {COMMIT_FORMAT_OR_DEFAULT}

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
    - Do not edit or commit planning artifacts unless the project intentionally tracks them or you were explicitly told.
    - If the feedback is wrong, explain why with code/test evidence instead of blindly changing code.
    - If every remaining item is pushback-only and no code changes are needed, do not create an empty commit.

    ## Fix Discipline

    Follow the `handle-review-feedback` skill. Each feedback item is a hypothesis:
    restate it, verify it against the code, then fix it or push back with
    `file:line` evidence if it is wrong or outside the slice spec. Fix one item at
    a time and run its targeted test before the next. Set
    `status: DONE_WITH_CONCERNS` if you push back on any item. Pushback fits
    judgement calls only — a red test or a failing command is fixed with a code
    or test change, never with an argument.

    If `Fix round` is 2 or higher, the previous fix did not hold — switch to the
    `debug-slice-failure` skill. Stop patching: reproduce the failure, find the
    root cause, confirm one hypothesis, then make a single minimal fix at the
    right seam with a regression test. If the root cause is architectural, return
    `status: BLOCKED` with the root cause instead of guessing again.

    ## Verification

    If you changed code, run the narrow tests for your fix and the project
    verification command:

    - {TEST_COMMAND}
    - {LINT_BUILD_COMMANDS_OR_NONE}

    Commit the fix on the current story branch using the provided commit format,
    or a plain imperative message if none is given.

    If this is a pushback-only result — you changed no code — make no commit and
    run no fix verification; instead capture, for each pushed-back item, the
    code / test / slice-spec evidence that proves your case.

    Before reporting: `git status --short` must be empty, and for a pushback-only
    result `git rev-parse HEAD` must still equal the input `Current HEAD`.

    ## Output Contract

    Your final response MUST end with exactly one machine-readable YAML block.
    Do not put prose after the block. Use `null` or `[]` when a field is not applicable.

    ```yaml
    status: DONE # DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
    commit_sha: null # string SHA when committed, otherwise null
    commands_run:
      - command: "exact command"
        exit_code: 0 # integer, or null if not run
        result: "pass/fail/blocked summary"
    red_green_evidence:
      status: NOT_APPLICABLE # PRESENT | MISSING | NOT_APPLICABLE
      test_file: null # path string, or null
      test_name: null # test name string, or null
      red:
        command: null # exact command string, or null
        exit_code: null # integer, or null
        failure_summary: null # expected failure summary string, or null
      green:
        command: null # exact command string, or null
        exit_code: null # integer, or null
        pass_summary: null # pass summary string, or null
    issues: [] # issue objects; empty for DONE with no concerns
    fix_request: [] # concrete requests for the controller/fix agent
    ```

    When reporting issues, each item in `issues` must include `severity`
    (`Critical`, `Important`, or `Minor`), `file_line` (path:line string or
    `null`), `problem`, `fix`, and `evidence`. For a pushed-back item, `fix` is
    `null` — you are disputing it, not fixing it — and `evidence` is the proof:
    the code, test, or slice-spec references that show the item is wrong or out
    of scope. For a normal fix or concern, `evidence` may be `null`.

    For DONE, `commit_sha` must be non-null, `commands_run` must include the
    verification command, and `fix_request` must be empty. For
    `DONE_WITH_CONCERNS`, `commit_sha` is non-null when you committed a fix, or
    null for a pushback-only result — and when it is null, `commands_run` must
    show `git rev-parse HEAD` still equal to the input `Current HEAD` and
    `git status --short` empty, proving no code changed. The pushed-back items
    and their evidence always go under `issues`. Use
    `red_green_evidence.status: NOT_APPLICABLE` only when the fix did not need a
    new failing test; otherwise include RED/GREEN evidence for changed behavior.
```
