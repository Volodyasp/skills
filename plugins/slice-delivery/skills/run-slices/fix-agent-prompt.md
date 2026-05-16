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

    ## Verification

    Run the narrow tests for your fix and the project verification command:

    - {TEST_COMMAND}
    - {LINT_BUILD_COMMANDS_OR_NONE}

    Commit your fix on the current story branch using the provided commit format. If no format is provided, use a plain imperative message.
    Before reporting, `git status --short` must be empty.

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
    `null`), `problem`, and `fix`.

    For DONE, `commit_sha` must be non-null, `commands_run` must include the
    verification command, and `fix_request` must be empty. Use
    `red_green_evidence.status: NOT_APPLICABLE` only when the fix did not need a new
    failing test; otherwise include RED/GREEN evidence for changed behavior.
```
