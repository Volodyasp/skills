# Document review: lenses and verifier

Finders: `## Finder rules`, then only your `## Lens: <id>`. Verifiers: `## Verifier` and `### Do not report` only.

## Finder rules

### Inputs (from the plan file)
- Document: `target`. Review the sections listed in `scope.sections`.
- Goal: what the document says it is for (title, intro, goal or scope section), plus `intent.file` when `intent.none` is false.
- Project rules: every path in `rules_files`, and the REVIEW.md copy at `review_md.path`. Follow what it says to report or skip.
- No-repeat list: `known[]`. The same problem at the same place is known even when worded differently.
- Run git as `git -C <repository root> …`.

### Evidence
- Report only what you can show from the text, and for code claims from code you read in this run. Not sure → do not report.
- Few strong items beat many weak ones.
- Every item names its class: write `class` so that "every instance of <class>" tells an editor what else to search for (`limit stated with two different values`).

### Fields (all required; not applicable → `""` or `0`)
- `category`: one of `ambiguity|contradiction|gap|code-claim|unneeded|inconsistency`; your lens names which.
- `class`: reusable defect class, ≤ 80 chars.
- `path`: the document's path (`target`). `line`: 1-based line of the snippet in the document.
- `symbol`: the key of the section that holds the snippet, copied character for character from `scope.sections`. Keys are the heading texts (without `#` marks) from outer to inner, joined by ` > `, e.g. `Design > Storage`; text before the first heading is `(preamble)`; a repeated key ends in ` #2`, ` #3`. Never retype or shorten a key.
- `snippet`: 1–3 consecutive lines copied exactly from the document. Never paraphrase.
- `claim`: one sentence: what is wrong and what it causes for a reader or implementer.
- `trigger`: the reading or case that goes wrong (`implementer reads §3 and §5 → two different timeouts`); `""` if none.
- `evidence`: `path:line` references with short quotes: both sides for a contradiction, the code for a code claim.
- `expected`: what the document should state, in one sentence. Never rewrite the section.
- `broken_by`: always `{"path": "", "line": 0}`.
- `scope_note`: `outside-goal` when the defect sits in text the document's goal does not cover (background, quoted context, "not in scope" or future-work sections); else `""`. Never `outside-goal` on an `unneeded` item.

### Do not report
- Wording, style, grammar, typos that do not change meaning, Markdown formatting, heading levels.
- Paths or kinds of issue REVIEW.md says to skip.
- Generated sections (tables of contents, tool-written changelogs).

## Lens: contradictions-gaps
- Contradiction: two statements that cannot both hold (values, rules, order of steps, ownership). Anchor one, quote both in `evidence` → `contradiction`.
- Gap: a case, error path, decision or input an implementer needs that the document does not settle. Name the missing case in `claim` → `gap`.
- A gap the goal does not need → not a finding.

## Lens: code-claims
- Every statement about existing code: files, functions, fields, commands, config keys, behaviour, numbers. Check each against the repository with Grep, Read and read-only git.
- Report claims that are false or out of date; `evidence` quotes the code that refutes them → `code-claim`.
- Statements about code the document proposes to write are not code claims.

## Lens: ambiguity
- A requirement with two or more reasonable readings that lead to different implementations: give the readings in `evidence` → `ambiguity`.
- A requirement nobody can check ("fast", "robust", "as needed") where a check matters → `ambiguity`.

## Lens: unneeded
- Content the document's goal does not need: speculative features, options nobody asked for, repeated rationale, duplicated sections, detail that belongs in another document → `unneeded`.
- `claim` names the goal it does not serve.

## Lens: consistency-links
- Links and references: target file or heading missing, wrong path, an id that does not exist → `inconsistency`.
- Terms, ids, numbers and names that differ between this document and the documents it links, or between its own sections → `inconsistency`.
- Read every linked document in the repository; skip external URLs.

## Verifier
You see only a claim and its location. Judge from the text and the code, not from how the claim is worded.

- Depth (each level includes the ones before): `anchor and its file` = the anchored section and the whole document; deeper levels add the documents and code it links or describes. `name a concrete trigger or the line that prevents it`: `holds: true` needs `trigger`; `holds: false` needs `prevented_by`.
- New items (`N…`, `S…` ids): does the defect exist in the current document? For a claim about code, check the code.
- Re-check items (`F…` ids): read the entry with the same `id` in the re-check file. Still present → `holds: true`. Gone → `holds: false`, `prevented_by` = the text that now settles it.
- The item is on the list in `### Do not report` above → `holds: false`; `reason` names the list entry.

Fields (all required; not applicable → `""`, `0` or `[]`):
- `item_id`: copied from the item. `holds`: `true` only when you confirmed the defect yourself.
- `severity`: when holding, `important` (an implementer would build the wrong thing or get stuck: contradiction, missing required case, false code claim) or `nit` (real but minor). REVIEW.md severity rules override these. Not holding → `""`.
- `reason`: one or two sentences for your verdict.
- `evidence`: `path:line` with short quotes you read.
- `trigger`: the reading that goes wrong when holding. `prevented_by`: `path:line` of the text that settles it when refuting.
- `needs_decision`: flag only when the right fix is the owner's choice, with evidence; no evidence, no flag. Pick one criterion and fill only its fields:
  - `1`: the fix changes a business rule, visible behaviour or a public contract: `before` and `after` (non-empty, different) describe it.
  - `2`: the item contradicts the stated intent: `intent_quote` copied character for character from the intent file.
  - `3`: fix options differ in observable behaviour: `options` = at least two `{label, observable}`.
  - None of these → `{"criterion": 0, "before": "", "after": "", "intent_quote": "", "options": []}`.
