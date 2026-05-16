# Slice Verifier Subagent Prompt Template

Use this template when dispatching the fresh `check-before-done` verification
sub-agent.

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
    2. Run every verification command freshly — never report from memory or a
       prior run.
    3. Read the complete output: exit codes, pass/fail counts, the actual failures.
    4. Inspect the diff range when a requirement cannot be proven by command
       output alone.
    5. Map every definition-of-done item to its evidence or its failure reason.

    ## How To Report

    Report in prose, then end with one status line. In the prose include:

    - Each verification command, its exit code, and its pass/fail count.
    - Each definition-of-done item: satisfied (with the evidence) or failed. Write
      each failure on its own line as `Severity file:line — what is wrong`,
      severity being Critical, Important, or Minor.
    - Whether the implementer's RED/GREEN evidence holds up.

    End with exactly this line and nothing after it:

        Status: <STATUS> · Commit: <verified HEAD sha>

    STATUS is one of: PASS, FAIL, BLOCKED.

    - PASS — every definition-of-done item has fresh evidence.
    - FAIL — at least one item fails or has no evidence behind it.
    - BLOCKED — verification cannot run: missing context, commands, dependencies,
      or environment. State what is missing.
```
