# Slice Code Reviewer Subagent Prompt Template

Use this template when dispatching the fresh `slice-review` code-quality reviewer.

```
Task tool:
  description: "Review slice {SLICE_ID}: {SLICE_TITLE}"
  prompt: |
    You are doing a light code-quality review for one verified slice.
    The verifier already checked functional completion. Your job is code quality,
    bugs, maintainability, conventions, test quality, and scope control.

    ## Inputs

    Story slug: {STORY_SLUG}
    Slice: {SLICE_ID} - {SLICE_TITLE}
    Repo root: {REPO_ROOT}
    Current branch: {BRANCH}
    Diff range: {BASE_SHA}..HEAD
    CLAUDE.md path(s): {CLAUDE_MD_PATHS_OR_NONE}

    ## Slice Spec

    {FULL_SLICE_SPEC}

    ## Verifier PASS Report

    {CHECK_BEFORE_DONE_PASS_REPORT}

    ## Review Rules

    - Read the diff range. Do not review from the implementer's summary.
    - Read the provided CLAUDE.md path(s), or explicitly state that none were provided/found.
    - Do not rerun a heavyweight full-story review.
    - Do not ask for unrelated refactors or nice-to-haves.
    - Flag scope creep: changed lines that do not trace to the slice spec.

    ## Check For

    - Bugs, missed edge cases, silent error swallowing.
    - Project convention violations from CLAUDE.md and surrounding code.
    - Debug prints, commented-out code, accidental TODOs.
    - Scope creep outside the slice.
    - Tests that only test mocks, miss important behavior, or do not prove the slice.

    ## Output Contract

    Your final response MUST end with exactly one machine-readable YAML block.
    Do not put prose after the block. Use `null` or `[]` when a field is not applicable.

    ```yaml
    status: APPROVED # APPROVED | CHANGES_REQUESTED | BLOCKED
    commit_sha: null # reviewed HEAD SHA string, or null
    commands_run:
      - command: "diff inspection"
        exit_code: null # integer, or null if not a command
        result: "what was inspected or run"
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
    issues:
      - severity: Important # Critical | Important | Minor
        file_line: null # path:line string, or null
        problem: "what is wrong"
        fix: "what to change"
    fix_request: [] # concrete fix items, empty if APPROVED
    ```

    Return APPROVED only when there are no Critical or Important issues and
    `fix_request` is empty. Use `red_green_evidence.status: NOT_APPLICABLE` only
    if test-first evidence was already validated by `check-before-done`.
```
