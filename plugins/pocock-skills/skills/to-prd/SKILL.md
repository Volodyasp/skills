---
name: to-prd
description: Turn the current conversation context into a PRD and write it to `docs/specs/<slug>/PRD.md`. Use when user wants to create a PRD from the current context for local spec-driven workflow.
---

This skill takes the current conversation context and codebase understanding and produces a PRD as a local markdown file. Do NOT interview the user for the PRD body — synthesize what you already know from the conversation.

The PRD lands in `docs/specs/<slug>/PRD.md`, where `<slug>` is a short story identifier the user provides. This is the input for `/to-slices` (decomposition) and downstream `/to-ralph` (Ralph loop runner).

## Process

### 1. Ask for the story slug

Before writing anything, ask the user for the **story slug**: a short kebab-case identifier for this PRD (e.g. `auth-token-refresh`, `vector-search-batching`, `telegram-onboarding-flow`).

Do not generate the slug from the PRD title yourself — auto-generated slugs tend to be vague ("implement-the-system"). Ask one direct question and accept what the user gives.

If `docs/specs/<slug>/` already exists with a `PRD.md`, stop and ask the user whether to overwrite, pick a different slug, or extend the existing PRD.

### 2. Explore the repo

If you haven't already, explore the codebase to understand current state. Use the project's domain glossary throughout the PRD, and respect any ADRs in the area you're touching.

### 3. Sketch deep modules

Sketch the major modules you will need to build or modify. Actively look for opportunities to extract **deep modules** that can be tested in isolation.

A deep module (as opposed to a shallow module) is one that encapsulates a lot of functionality behind a simple, testable interface that rarely changes.

Check with the user that these modules match their expectations. Ask which modules they want tests written for.

### 4. Write the PRD

Create `docs/specs/<slug>/PRD.md` using the template below. Create the directory if it doesn't exist.

<prd-template>

# PRD: <Title>

## Problem Statement

The problem the user is facing, from the user's perspective.

## Solution

The solution to the problem, from the user's perspective.

## User Stories

A LONG, numbered list of user stories in the format:

1. As an <actor>, I want <feature>, so that <benefit>.

<user-story-example>
1. As a mobile bank customer, I want to see balance on my accounts, so that I can make better informed decisions about my spending.
</user-story-example>

The list should be extensive and cover all aspects of the feature.

## Implementation Decisions

A list of implementation decisions. May include:

- The modules that will be built/modified
- The interfaces of those modules
- Technical clarifications from the developer
- Architectural decisions
- Schema changes
- API contracts
- Specific interactions

Do NOT include specific file paths or code snippets — they go stale fast.

## Testing Decisions

- What makes a good test here (only test external behavior, not implementation details)
- Which modules will be tested
- Prior art for the tests (similar tests in the codebase)

## Out of Scope

What is explicitly out of scope for this PRD.

## Further Notes

Anything else worth recording.

</prd-template>

### 5. Report

After writing the file, report the absolute path to the user and suggest the next step:

```
PRD written to: docs/specs/<slug>/PRD.md
Next: /to-slices to break this into vertical slices.
```
