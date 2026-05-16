# Slice Verifier Subagent Prompt Template

Use this template when dispatching the fresh `check-before-done` verification sub-agent.

```
Task tool:
  description: "Verify slice {SLICE_ID}: {SLICE_TITLE}"
  prompt: |
    You are independently verifying whether a slice is genuinely done.
    Do not trust the implementer's report. Verify from commands and code.

    ## Inputs

    Story slug: {STORY_SLUG}
    Slice: {SLICE_ID} - {SLICE_TITLE}
    Repo root: {REPO_ROOT}
    Current branch: {BRANCH}
    Diff range: {BASE_SHA}..HEAD

    ## Implementer Or Fix-Agent Report

    {IMPLEMENTER_OR_FIX_REPORT}

    ## Definition Of Done

    {FULL_SLICE_SPEC}

    ## Verification Commands

    Test command: {TEST_COMMAND}
    Additional verification: {LINT_BUILD_COMMANDS_OR_NONE}

    ## Your Job

    1. Identify what evidence proves each acceptance criterion.
    2. Run every verification command freshly.
    3. Read complete output: exit codes, pass/fail counts, and failures.
    4. Inspect the diff range when a requirement cannot be proven by command output alone.
    5. Map every definition-of-done item to evidence or a failure reason.

    ## Output Contract

    Your final response MUST end with exactly one machine-readable YAML block.
    Do not put prose after the block. Use `null` or `[]` when a field is not applicable.

    ```yaml
    status: PASS # PASS | FAIL | BLOCKED
    commit_sha: null # verified HEAD SHA string, or null
    commands_run:
      - command: "exact command"
        exit_code: 0 # integer, or null if not run
        result: "pass/fail/blocked summary"
    red_green_evidence:
      status: PRESENT # PRESENT | MISSING | NOT_APPLICABLE
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
    issues: [] # issue objects; empty if PASS
    fix_request: [] # concrete fix items, empty if PASS
    ```

    When reporting issues, each item in `issues` must include `severity`
    (`Critical`, `Important`, or `Minor`), `file_line` (path:line string or
    `null`), `problem`, and `fix`.

    Only return PASS when every definition-of-done item has fresh evidence, `commands_run`
    includes the verification commands, and `fix_request` is empty.
```
