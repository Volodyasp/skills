# Slice Implementer Subagent Prompt Template

Use this template when dispatching the fresh implementer sub-agent for one slice.

```
Task tool:
  description: "Implement slice {SLICE_ID}: {SLICE_TITLE}"
  prompt: |
    You are implementing one vertical slice on the current story branch.

    ## Inputs

    Story slug: {STORY_SLUG}
    Slice: {SLICE_ID} - {SLICE_TITLE}
    Repo root: {REPO_ROOT}
    Current branch: {BRANCH}
    Slice base SHA: {BASE_SHA}
    Commit format: {COMMIT_FORMAT_OR_DEFAULT}

    ## Slice Spec

    {FULL_SLICE_SPEC}

    ## Project Commands

    Test command: {TEST_COMMAND}
    Additional verification: {LINT_BUILD_COMMANDS_OR_NONE}

    ## Context From Accepted Slices

    {PRIOR_SLICE_CONTEXT_OR_NONE}

    ## Hard Rules

    - Work in the current checkout and branch. Do not create worktrees or branches.
    - Use only the context above. If you need PRD details, another slice, or an architectural decision, ask.
    - Do not edit or commit planning artifacts unless the project intentionally tracks them or you were explicitly told to update them.
    - Implement exactly this slice. No nice-to-haves, no unrelated refactors.
    - Follow existing code style and CLAUDE.md project instructions.

    ## TDD Requirement

    1. Write a failing test for the slice behavior.
    2. Run the targeted test and confirm it fails for the expected reason.
    3. Implement the minimum code needed.
    4. Run the targeted test and {TEST_COMMAND}.
    5. Refactor only while tests stay green.

    If you cannot write a meaningful failing test, stop with NEEDS_CONTEXT or BLOCKED.

    ## Commit Requirement

    Commit the slice on the current story branch using the provided commit format. If no format is provided, use a plain imperative message.
    Before reporting, confirm:

    - `git status --short` is empty
    - `git rev-parse HEAD` is the commit you made
    - `git diff --stat {BASE_SHA}..HEAD` contains only intended implementation/test files, plus intentional tracked docs/spec changes if project policy allows them

    ## Self-Review

    Before reporting, check:

    - Every acceptance criterion is addressed.
    - Tests exercise real behavior, not only mocks.
    - No debug prints, commented-out code, or stray TODOs.
    - No scope creep outside the slice.

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
    issues: [] # issue objects; empty for DONE with no concerns
    fix_request: [] # concrete requests for the controller/fix agent
    ```

    When reporting issues, each item in `issues` must include `severity`
    (`Critical`, `Important`, or `Minor`), `file_line` (path:line string or
    `null`), `problem`, and `fix`.

    For DONE, `commit_sha` must be non-null, `red_green_evidence.status` must be PRESENT,
    `commands_run` must include the verification command, and `fix_request` must be empty.
```
