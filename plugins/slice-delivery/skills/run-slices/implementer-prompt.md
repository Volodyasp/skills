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
    - Use only the context above. If you need PRD details, another slice, or an
      architectural decision, stop and ask — do not go reading other files.
    - Do not edit or commit planning artifacts unless the project intentionally
      tracks them or you were explicitly told to update them.
    - Implement exactly this slice. No nice-to-haves, no unrelated refactors.
    - Follow existing code style and CLAUDE.md project instructions.

    ## TDD Requirement

    1. Write a failing test for the slice behavior.
    2. Run the targeted test and confirm it fails for the expected reason.
    3. Implement the minimum code needed.
    4. Run the targeted test and {TEST_COMMAND}.
    5. Refactor only while tests stay green.

    If you cannot write a meaningful failing test, stop and report NEEDS_CONTEXT
    or BLOCKED — do not implement untested.

    ## Commit Requirement

    Commit the slice on the current story branch using the provided commit format,
    or a plain imperative message if none is given. The subject must describe the
    actual code/product change, not the slice machinery — avoid "slice done",
    "run-slices changes", "address verifier".

    Before reporting, confirm:

    - `git status --short` is empty.
    - `git rev-parse HEAD` is the commit you made.
    - `git diff --stat {BASE_SHA}..HEAD` contains only intended implementation and
      test files.

    ## Self-Review

    - Every acceptance criterion is addressed.
    - Tests exercise real behavior, not only mocks.
    - No debug prints, commented-out code, or stray TODOs.
    - No scope creep outside the slice.

    ## How To Report

    Report in prose, then end with one status line. In the prose include:

    - Each verification command you ran, with its exit code and pass/fail count.
    - RED/GREEN evidence: the test file and name, the command that showed it fail
      for the expected reason, then the command that showed it pass.
    - Each acceptance criterion and how the code meets it.
    - Any concern or issue, one per line as `Severity file:line — what is wrong`,
      severity being Critical, Important, or Minor.

    End with exactly this line and nothing after it:

        Status: <STATUS> · Commit: <sha or none>

    STATUS is one of: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED.

    - DONE — committed, RED/GREEN shown, verification command run and green.
    - DONE_WITH_CONCERNS — committed, but you have a correctness or scope doubt;
      state it in the prose.
    - NEEDS_CONTEXT — you need information that was not provided.
    - BLOCKED — you cannot complete the slice; explain why.
```
