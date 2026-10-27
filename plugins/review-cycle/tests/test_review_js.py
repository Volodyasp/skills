"""Behavioural tests for workflows/review.js (SPECS WF-1..13) through tests/js/harness.mjs.

The harness replaces the Workflow runtime with fakes; scenario keys are documented there.
Item ids: `N<f>.<k>` for finder items (f, k 1-based), `S<k>` for sweep items.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

import pytest
from conftest import HARNESS, REVIEW_JS

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

NEXT_TEXT = "Run /review-cycle; this workflow needs arguments from review-cycle-state."
PROVENANCE = "review-cycle/workflows/review.js"
RESULT_KEYS = {
    "provenance", "v", "started", "plan_id", "echo", "candidates", "dropped", "verdicts",
    "missing", "stats", "log", "checksum",
}  # fmt: skip
HOLDS = {"holds": True}
REFUTES = {"holds": False}


def make_args(**over: Any) -> dict[str, Any]:
    """Valid ST-3 workflow args (absolute paths); `over` replaces top-level fields."""
    base: dict[str, Any] = {
        "v": 1,
        "plan_id": "plan-1",
        "plan": "/state/plan.json",
        "repo_root": "/repo",
        "mode": "code",
        "level": "high",
        "finders": [{"lens": "bugs", "order": "forward"}, {"lens": "intent", "order": "forward"}],
        "finder_model": "fm-test",
        "votes": ["sonnet", "opus"],
        "tiebreak": "opus",
        "sweep": None,
        "model_override": False,
        "depth": "DEPTH-TEXT anchor and its file",
        "lens_file": "/refs/code.md",
        "verifier_section": "## Verifier",
        "verify_dir": "/state/verify",
        "state_dir": "/state",
        "intent_file": "/state/verify/intent.md",
        "review_md": "/state/verify/review-md-base.md",
        "rules_files": ["/repo/CLAUDE.md"],
        "recheck_file": "/state/verify/recheck.json",
        "recheck": [],
    }
    return {**base, **over}


def item(path: str = "a.py", symbol: str = "f", n: int = 1, **over: Any) -> dict[str, Any]:
    """A finder item (ST-9) whose text fields are unique per (path, symbol, n)."""
    tag = f"{path}-{symbol}-{n}"
    base: dict[str, Any] = {
        "category": "logic",
        "class": f"class-{tag}",
        "path": path,
        "line": 10 + n,
        "symbol": symbol,
        "snippet": f"snippet {tag}",
        "claim": f"claim {tag}",
        "trigger": f"trigger {tag}",
        "evidence": f"evidence {tag}",
        "expected": f"expected {tag}",
        "broken_by": {"path": "", "line": 0},
        "scope_note": "",
    }
    return {**base, **over}


def run_js(**scenario: Any) -> dict[str, Any]:
    proc = subprocess.run(
        ["node", str(HARNESS), str(REVIEW_JS)],
        input=json.dumps(scenario),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, f"harness failed: {proc.stderr}"
    out: dict[str, Any] = json.loads(proc.stdout)
    assert out.get("unclassified", []) == [], "agent labels not recognised by the harness"
    return out


def run_round(args: dict[str, Any], **scenario: Any) -> dict[str, Any]:
    return run_js(args=args, **scenario)


def kinds(out: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [c for c in out["calls"] if c["kind"] == kind]


def blind_calls(out: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in out["calls"] if c["kind"] in ("verify", "tiebreak")]


def split_batches(out: dict[str, Any], slot: int = 0) -> list[list[str]]:
    return [c["ids"] for c in kinds(out, "verify") if c["slot"] == slot]


SCENARIO_KEYS = ("verdicts", "null_calls", "extra_rows", "throw_calls")


def one_finder(items: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
    """Run a round with a single forward finder returning `items`.

    Keys in SCENARIO_KEYS drive the fake agents; every other key overrides a workflow arg.
    """
    scenario = {k: over.pop(k) for k in SCENARIO_KEYS if k in over}
    args = make_args(finders=[{"lens": "bugs", "order": "forward"}], **over)
    return run_round(args, find={"find:bugs": {"findings": items}}, **scenario)


def assert_not_started(out: dict[str, Any], reasons: set[str]) -> None:
    result = out["result"]
    assert result["provenance"] == PROVENANCE
    assert result["v"] == 1
    assert result["started"] is False
    assert result["reason"] in reasons
    if result["reason"] in ("no-args", "bad-args"):
        assert result["next"] == NEXT_TEXT
    else:
        assert isinstance(result["next"], str)
        assert result["next"]
    assert out["calls"] == []


# --- WF-1 static ---------------------------------------------------------------------------

FORBIDDEN = [
    r"Date\.now", r"Math\.random", r"new Date\(\)", r"import\(", r"require\(", r"process\.",
    r"\bBuffer\b", r"\bTextEncoder\b", r"\bcrypto\b", r"\bsetTimeout\b", r"\bfetch\b",
    r"\bglobalThis\b", r"agentType", r"\beffort\b",
]  # fmt: skip


def _scan(src: str, i: int, in_template_expr: bool, keep_strings: bool) -> tuple[str, int]:
    """Copy code from `src[i:]` without comments; string bodies are blanked unless kept.

    Template-literal `${...}` expressions are scanned as code. With `in_template_expr` the scan
    stops after the `}` closing the expression. Regex literals are not understood.
    """
    out: list[str] = []
    depth = 0
    n = len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            i = src.find("\n", i) if "\n" in src[i:] else n
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c in "\"'":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            out.append(src[i : j + 1] if keep_strings else c + c)
            i = j + 1
        elif c == "`":
            out.append("`" if keep_strings else "``")
            i += 1
            while i < n and src[i] != "`":
                if src.startswith("${", i):
                    code, i = _scan(src, i + 2, True, keep_strings)
                    out.append(f" {code} ")
                else:
                    if keep_strings:
                        out.append(src[i])
                    i += 2 if src[i] == "\\" else 1
            i += 1
        else:
            if in_template_expr and c == "}" and depth == 0:
                return "".join(out), i + 1
            depth += (c == "{") - (c == "}")
            out.append(c)
            i += 1
    return "".join(out), n


def strip_js(src: str, *, keep_strings: bool = False) -> str:
    """Return `src` without comments and (unless `keep_strings`) without string bodies."""
    return _scan(src, 0, False, keep_strings)[0]


def test_wf1_strip_js_self_test() -> None:
    assert re.search(FORBIDDEN[0], strip_js("const t = Date.now();"))
    assert not re.search(FORBIDDEN[0], strip_js('const t = "Date.now()";'))
    assert not re.search(FORBIDDEN[0], strip_js("const t = `see Date.now()`;"))
    assert not re.search(FORBIDDEN[0], strip_js("// Date.now()\n/* Date.now() */ x = 1"))
    assert re.search(FORBIDDEN[0], strip_js("const t = `a ${Date.now()} b`;"))
    assert re.search(FORBIDDEN[0], strip_js("const t = `a ${ {k: 1}.k } ${Date.now()}`;"))
    assert "Date" not in strip_js("x = 'a\\' Date.now()'; y = 2")


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_wf1_script_has_no_forbidden_api(pattern: str) -> None:
    code = strip_js(REVIEW_JS.read_text(encoding="utf-8"))
    assert re.search(pattern, code) is None


def test_wf1_meta_is_pure_literal_named_round() -> None:
    text = strip_js(REVIEW_JS.read_text(encoding="utf-8"), keep_strings=True)
    match = re.search(r"^\s*export const meta\s*=\s*(\{.*?^\s*\})\s*;", text, re.S | re.M)
    assert match, "export const meta literal not found"
    literal = re.sub(r"'([^'\\\n]*)'", r'"\1"', match.group(1))
    skeleton = re.sub(r'"(?:[^"\\]|\\.)*"', '""', literal)
    assert not re.search(r"[(`+]|=>|\.\.\.", skeleton), "meta is not a pure literal"
    words = re.findall(r"[A-Za-z_]\w*(?!\s*:)\b", re.sub(r"\b[A-Za-z_]\w*(?=\s*:)", "", skeleton))
    assert set(words) <= {"true", "false", "null"}
    assert re.search(r'\bname\s*:\s*"round"', literal)
    for phase_name in ("Find", "Verify", "Tie-break", "Sweep"):
        assert f'"{phase_name}"' in literal


def test_wf1_no_agent_option_beyond_label_phase_schema_model() -> None:
    out = one_finder([item()])
    for call in out["calls"]:
        assert set(call["opts"]) <= {"label", "phase", "schema", "model"}


# --- WF-2 guards ---------------------------------------------------------------------------


def test_wf2_undefined_args() -> None:
    assert_not_started(run_js(), {"no-args"})


@pytest.mark.parametrize("raw", ["{not json", "[1, 2"])
def test_wf2_bad_json_string(raw: str) -> None:
    assert_not_started(run_js(args=raw), {"bad-args"})


@pytest.mark.parametrize(
    ("value", "reason"),
    [("", "no-args"), ({}, "no-args"), (None, "no-args"), (42, "bad-args"), ([], "bad-args"),
     ("text", "bad-args")],
)  # fmt: skip
def test_wf2_empty_or_non_object(value: Any, reason: str) -> None:
    assert_not_started(run_js(args=value), {reason})


@pytest.mark.parametrize(
    "field", ["plan_id", "plan", "level", "mode", "finders", "votes", "repo_root"]
)
def test_wf2_missing_required_field(field: str) -> None:
    args = make_args()
    del args[field]
    assert_not_started(run_round(args), {"bad-args"})


@pytest.mark.parametrize(
    "over",
    [{field: "relative/path"} for field in
     ("plan", "repo_root", "lens_file", "verify_dir", "state_dir", "intent_file", "recheck_file")]
    + [{"rules_files": ["/abs/CLAUDE.md", "AGENTS.md"]}],
)  # fmt: skip
def test_wf2_relative_path(over: dict[str, Any]) -> None:
    assert_not_started(run_round(make_args(**over)), {"bad-args"})


def test_wf2_null_review_md_is_valid() -> None:
    out = one_finder([item()], review_md=None, votes=["sonnet"], tiebreak=None)
    assert out["result"]["started"] is True
    prompts = [c["prompt"] for c in kinds(out, "verify")]
    assert prompts
    assert not any("review-md-base" in p for p in prompts)


@pytest.mark.parametrize("focus", [None, "look at the refund path"])
def test_rpt19_focus_absent_or_string_is_valid(focus: str | None) -> None:
    out = one_finder([item()], focus=focus, votes=["sonnet"], tiebreak=None)
    assert out["result"]["started"] is True


def test_rpt19_focus_missing_key_is_valid() -> None:
    args = make_args()
    assert "focus" not in args
    out = run_round(args, find={"find:bugs": {"findings": [item()]}})
    assert out["result"]["started"] is True


@pytest.mark.parametrize("bad", [42, True, [], {}])
def test_rpt19_focus_non_string_is_bad_args(bad: Any) -> None:
    assert_not_started(run_round(make_args(focus=bad)), {"bad-args"})


@pytest.mark.parametrize("paths", [None, [], ["src/a.py"], ["src/a.py", "lib/b.py"]])
def test_rpt20c_paths_absent_null_or_string_array_is_valid(paths: list[str] | None) -> None:
    out = one_finder([item()], paths=paths, votes=["sonnet"], tiebreak=None)
    assert out["result"]["started"] is True


def test_rpt20c_paths_missing_key_is_valid() -> None:
    args = make_args()
    assert "paths" not in args
    out = run_round(args, find={"find:bugs": {"findings": [item()]}})
    assert out["result"]["started"] is True


@pytest.mark.parametrize("bad", [42, "src/a.py", True, {}, [1, 2], [None]])
def test_rpt20c_paths_non_array_or_non_string_items_is_bad_args(bad: Any) -> None:
    assert_not_started(run_round(make_args(paths=bad)), {"bad-args"})


def test_wf2_string_json_args_run_normally() -> None:
    out = run_js(args=json.dumps(make_args()))
    assert out["result"]["started"] is True
    assert len(kinds(out, "find")) == 2


# --- WF-3 haiku ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "over",
    [{"votes": ["sonnet", "claude-haiku-4"]}, {"votes": ["sonnet", "sonnet"], "tiebreak": "Haiku"}],
)
def test_wf3_haiku_verifier_refused(over: dict[str, Any]) -> None:
    result = run_round(make_args(**over))
    assert_not_started(result, {"haiku-verifier"})


def test_wf3_haiku_allowed_with_override() -> None:
    args = make_args(votes=["haiku", "haiku"], tiebreak="haiku", model_override=True)
    out = run_round(args, find={"find:bugs": {"findings": [item()]}})
    assert out["result"]["started"] is True
    assert {c["opts"]["model"] for c in blind_calls(out)} == {"haiku"}


# --- WF-4 find agents ----------------------------------------------------------------------


def test_wf4_find_calls_labels_models_order() -> None:
    finders = [
        {"lens": "bugs", "order": "forward"},
        {"lens": "bugs", "order": "reverse"},
        {"lens": "history", "order": "forward"},
    ]
    out = run_round(make_args(finders=finders))
    calls = kinds(out, "find")
    assert sorted(c["label"] for c in calls) == ["find:bugs", "find:bugs:rev", "find:history"]
    for call in calls:
        assert call["opts"]["phase"] == "Find"
        assert call["opts"]["model"] == "fm-test"
        prompt = call["prompt"]
        assert "/state/plan.json" in prompt
        assert f"## Lens: {call['label'].split(':')[1]}" in prompt
        assert "/refs/code.md" in prompt
        assert re.search(r"read-only", prompt, re.I)
        assert re.search(r"no-repeat", prompt, re.I)
        assert bool(re.search(r"reverse", prompt, re.I)) == call["label"].endswith(":rev")


FOCUS_LINE = (
    "Owner's focus (look harder here; still report every other real problem): "
    '"refunds in checkout.py"'
)


def test_rpt19_focus_line_in_finder_prompt_only_when_set() -> None:
    out = one_finder([item()], focus="refunds in checkout.py", votes=["sonnet"], tiebreak=None)
    finds = kinds(out, "find")
    assert finds and all(FOCUS_LINE in c["prompt"] for c in finds)
    assert not any(FOCUS_LINE in c["prompt"] for c in blind_calls(out))


def test_rpt19_no_focus_line_when_focus_is_absent() -> None:
    out = one_finder([item()], votes=["sonnet"], tiebreak=None)
    for call in kinds(out, "find"):
        assert "Owner's focus" not in call["prompt"]


@pytest.mark.parametrize(
    ("mode", "categories"),
    [
        ("code", {"intent", "logic", "edge-case", "concurrency", "error-handling", "rule",
                  "stale", "regression", "contract"}),
        ("document", {"ambiguity", "contradiction", "gap", "code-claim", "unneeded",
                      "inconsistency"}),
    ],
)  # fmt: skip
def test_wf4_finder_schema_per_mode(mode: str, categories: set[str]) -> None:
    out = run_round(make_args(mode=mode, finders=[{"lens": "bugs", "order": "forward"}]))
    schema = kinds(out, "find")[0]["opts"]["schema"]
    entry = schema["properties"]["findings"]["items"]
    fields = {"category", "class", "path", "line", "symbol", "snippet", "claim", "trigger",
              "evidence", "expected", "broken_by", "scope_note"}  # fmt: skip
    assert schema["type"] == "object"
    assert set(entry["required"]) == fields
    assert set(entry["properties"]["category"]["enum"]) == categories


# --- WF-5 dedup and ids --------------------------------------------------------------------


def test_wf5_ids_and_dedup_code_mode() -> None:
    long_a = "y" * 120 + "A"
    long_b = "y" * 120 + "B"
    first = [
        item("a.py", "f", 1, snippet="  x  =  1\n\n   y = 2"),
        item("b.py", "g", 1, snippet=long_a),
    ]
    second = [
        item("a.py", "f", 2, snippet="x = 1\ny = 2", category="rule"),
        item("b.py", "g", 2, snippet=long_b),
        item("b.py", "other", 3, snippet=long_b),
    ]
    out = run_round(
        make_args(),
        find={"find:bugs": {"findings": first}, "find:intent": {"findings": second}},
    )
    result = out["result"]
    assert [c["id"] for c in result["candidates"]] == ["N1.1", "N1.2", "N2.3"]
    assert result["dropped"] == [
        {"id": "N2.1", "dup_of": "N1.1"},
        {"id": "N2.2", "dup_of": "N1.2"},
    ]
    assert any("N2.1" in line for line in result["log"])
    assert [c["finder"] for c in result["candidates"]] == [1, 1, 2]
    assert all(c["of_class"] == "" for c in result["candidates"])
    assert result["candidates"][0]["lens"] == "bugs"
    assert result["candidates"][2]["lens"] == "intent"


def test_wf5_no_dedup_in_document_mode() -> None:
    dup = item("doc.md", "Intro", 1, category="gap")
    out = run_round(
        make_args(mode="document"),
        find={"find:bugs": {"findings": [dup]}, "find:intent": {"findings": [dup]}},
    )
    assert [c["id"] for c in out["result"]["candidates"]] == ["N1.1", "N2.1"]
    assert out["result"]["dropped"] == []


# --- WF-6 flow in both modes ---------------------------------------------------------------


@pytest.mark.parametrize("mode", ["code", "document"])
def test_wf6_flow_barrier_rechecks_once_and_sorted_output(mode: str) -> None:
    args = make_args(
        mode=mode,
        votes=["sonnet", "sonnet"],
        tiebreak=None,
        recheck=[{"id": "F1", "path": "a.py"}],
    )
    cat = {"category": "gap" if mode == "document" else "logic"}
    out = run_round(
        args,
        find={
            "find:bugs": {"findings": [item("b.py", "g", 1, **cat), item("a.py", "f", 2, **cat)]},
            "find:intent": {"findings": [item("c.py", "h", 1, **cat)]},
        },
    )
    calls = out["calls"]
    last_find = max(i for i, c in enumerate(calls) if c["kind"] == "find")
    first_verify = min(i for i, c in enumerate(calls) if c["kind"] == "verify")
    assert last_find < first_verify

    result = out["result"]
    assert [c["id"] for c in result["candidates"]] == ["N1.1", "N1.2", "N2.1"]
    rows = [v for v in result["verdicts"] if v["item_id"] == "F1"]
    assert sorted((v["kind"], v["role"], v["slot"]) for v in rows) == [
        ("recheck", "vote", 0),
        ("recheck", "vote", 1),
    ]
    assert result["echo"]["recheck_ids"] == ["F1"]
    new_rows = [v for v in result["verdicts"] if v["kind"] == "new"]
    assert len(new_rows) == 3 * 2
    for role in ("vote", "tiebreak"):
        keys = [
            (v["batch"], v["slot"], v["item_id"]) for v in result["verdicts"] if v["role"] == role
        ]
        assert keys == sorted(keys)
    assert {v["model"] for v in result["verdicts"]} == {"sonnet"}
    assert all(c["opts"]["phase"] == "Verify" for c in kinds(out, "verify"))


# --- WF-7 batching -------------------------------------------------------------------------


def test_wf7_nine_in_one_file_split_eight_plus_one() -> None:
    items = [item("a.py", f"f{n}", n) for n in range(1, 10)]
    out = one_finder(items, votes=["sonnet"], tiebreak=None)
    sizes = sorted(len(ids) for ids in split_batches(out))
    assert sizes == [1, 8]
    verdict_batches = {v["batch"] for v in out["result"]["verdicts"]}
    assert len(verdict_batches) == 2


def test_wf7_mixed_files_first_fit_by_sorted_path() -> None:
    items = (
        [item("a.py", f"f{n}", n) for n in range(1, 6)]
        + [item("b.py", f"g{n}", n) for n in range(1, 6)]
        + [item("c.py", f"h{n}", n) for n in range(1, 4)]
    )
    out = one_finder(items, votes=["sonnet"], tiebreak=None)
    by_id = {c["id"]: c["path"] for c in out["result"]["candidates"]}
    batches = sorted(sorted({by_id[i] for i in ids}) for ids in split_batches(out))
    assert batches == [["a.py", "c.py"], ["b.py"]]
    assert sorted(len(ids) for ids in split_batches(out)) == [5, 8]


def test_wf7_one_verifier_per_vote_slot_per_batch() -> None:
    out = one_finder([item()], votes=["sonnet", "opus"], tiebreak=None)
    calls = kinds(out, "verify")
    assert sorted((c["slot"], c["opts"]["model"]) for c in calls) == [(0, "sonnet"), (1, "opus")]
    assert sorted(c["label"] for c in calls) == ["verify:b1:0:sonnet", "verify:b1:1:opus"]
    assert {v["batch"] for v in out["result"]["verdicts"]} == {1}
    schema = calls[0]["opts"]["schema"]
    entry = schema["properties"]["verdicts"]["items"]
    assert {"item_id", "holds", "severity", "reason", "evidence", "trigger", "prevented_by",
            "needs_decision"} <= set(entry["required"])  # fmt: skip


# --- WF-8 blindness ------------------------------------------------------------------------


def test_wf8_verifier_prompts_blind_and_complete() -> None:
    sentinels = {
        "evidence": "SENT_EVIDENCE_91",
        "trigger": "SENT_TRIGGER_91",
        "expected": "SENT_EXPECTED_91",
        "class": "SENT_CLASS_91",
        "category": "stale",
        "scope_note": "SENT_SCOPE_NOTE_91",
        "broken_by": {"path": "SENT_BROKEN_BY_91.py", "line": 7},
        "lens": "SENT_ITEM_LENS_91",
    }
    finders = [{"lens": "sentinel-lens-91", "order": "forward"}]
    args = make_args(finders=finders)
    found = item(
        "src/mod.py", "SYMBOL_91", 1, line=4217, claim="CLAIM_91", snippet="SNIPPET_91", **sentinels
    )
    out = run_round(
        args,
        find={"find:sentinel-lens-91": {"findings": [found]}},
        verdicts={
            "N1.1": {
                "vote:0": {"holds": True, "reason": "SENT_REASON_V0"},
                "vote:1": {"holds": False, "reason": "SENT_REASON_V1"},
            }
        },
        default_spec={"holds": True},
    )
    verifiers = blind_calls(out)
    assert {c["kind"] for c in verifiers} == {"verify", "tiebreak"}
    banned = ["SENT_EVIDENCE_91", "SENT_TRIGGER_91", "SENT_EXPECTED_91", "SENT_CLASS_91",
              "stale", "SENT_SCOPE_NOTE_91", "SENT_BROKEN_BY_91", "SENT_ITEM_LENS_91", "sentinel-lens-91"]  # fmt: skip
    verify_line = (
        "Read only the repository files, the lens file named above, and the files in "
        "/state/verify; do not open anything else under /state."
    )
    for call in verifiers:
        prompt = call["prompt"]
        for word in banned:
            assert word not in prompt
        for word in ("CLAIM_91", "SNIPPET_91", "src/mod.py", "4217", "SYMBOL_91", "N1.1",
                     "/repo/CLAUDE.md", "/state/verify/review-md-base.md",
                     "/state/verify/intent.md", "/refs/code.md", "## Verifier",
                     "DEPTH-TEXT", verify_line):  # fmt: skip
            assert word in prompt
    for call in kinds(out, "tiebreak"):
        assert "SENT_REASON_V0" not in call["prompt"]
        assert "SENT_REASON_V1" not in call["prompt"]


def test_wf8_sweep_items_blind_in_verifier_prompts() -> None:
    sentinels = {
        "evidence": "SW_EVIDENCE_77",
        "trigger": "SW_TRIGGER_77",
        "expected": "SW_EXPECTED_77",
        "category": "stale",
        "scope_note": "SW_SCOPE_77",
        "broken_by": {"path": "SW_BROKEN_77.py", "line": 3},
        "of_class": "SW_OF_CLASS_77",
        "class": "SW_CLASS_77",
    }
    swept = item(
        "z.py", "SW_SYMBOL_77", 1, claim="SW_CLAIM_77", snippet="SW_SNIPPET_77", **sentinels
    )
    out = run_round(
        sweep_args(finders=[{"lens": "bugs", "order": "forward"}]),
        find={"find:bugs": {"findings": [item("a.py", "f", 1)]}},
        verdicts={"N1.1": {"vote:0": HOLDS, "vote:1": HOLDS, "vote:2": HOLDS}},
        sweep={"findings": [swept]},
    )
    s_calls = [c for c in blind_calls(out) if "S1" in c["ids"]]
    assert len(s_calls) == 3
    for call in s_calls:
        for word in ("SW_EVIDENCE_77", "SW_TRIGGER_77", "SW_EXPECTED_77", "stale",
                     "SW_SCOPE_77", "SW_BROKEN_77", "SW_OF_CLASS_77", "SW_CLASS_77"):  # fmt: skip
            assert word not in call["prompt"]
        for word in ("SW_CLAIM_77", "SW_SNIPPET_77", "SW_SYMBOL_77", "z.py"):
            assert word in call["prompt"]


def test_wf8_recheck_prompt_points_to_recheck_file() -> None:
    args = make_args(votes=["sonnet"], tiebreak=None, recheck=[{"id": "F3", "path": "a.py"}])
    out = run_round(args)
    prompts = [c["prompt"] for c in kinds(out, "verify")]
    assert len(prompts) == 1
    assert "F3" in prompts[0]
    assert "/state/verify/recheck.json" in prompts[0]


# --- WF-9 tie-break ------------------------------------------------------------------------


def split_scenario() -> dict[str, dict[str, Any]]:
    return {
        "N1.1": {"vote:0": HOLDS, "vote:1": HOLDS},
        "N1.2": {"vote:0": HOLDS, "vote:1": REFUTES},
        "N1.3": {"vote:0": REFUTES, "vote:1": REFUTES},
        "N1.4": {"vote:0": HOLDS, "vote:1": "omit"},
        "N1.5": {"vote:0": REFUTES, "vote:1": HOLDS},
    }


def test_wf9_tiebreak_only_on_split_and_missing() -> None:
    items = [item("a.py", f"f{n}", n) for n in range(1, 6)]
    out = one_finder(
        items,
        verdicts={**split_scenario(), "N1.2": {**split_scenario()["N1.2"], "tiebreak:0": REFUTES}},
    )
    tie = kinds(out, "tiebreak")
    assert len(tie) == 1
    assert sorted(tie[0]["ids"]) == ["N1.2", "N1.4", "N1.5"]
    assert tie[0]["opts"]["model"] == "opus"
    assert tie[0]["opts"]["phase"] == "Tie-break"
    assert re.fullmatch(r"tiebreak:b\d+:opus", tie[0]["label"])
    assert tie[0]["opts"]["schema"] == kinds(out, "verify")[0]["opts"]["schema"]
    rows = [v for v in out["result"]["verdicts"] if v["role"] == "tiebreak"]
    assert sorted((v["item_id"], v["slot"], v["model"]) for v in rows) == [
        ("N1.2", 0, "opus"),
        ("N1.4", 0, "opus"),
        ("N1.5", 0, "opus"),
    ]


def test_wf9_no_tiebreak_at_maj3() -> None:
    items = [item("a.py", f"f{n}", n) for n in range(1, 3)]
    verdicts = {
        "N1.1": {"vote:0": HOLDS, "vote:1": REFUTES, "vote:2": HOLDS},
        "N1.2": {"vote:0": REFUTES, "vote:1": REFUTES, "vote:2": HOLDS},
    }
    out = one_finder(items, votes=["sonnet", "sonnet", "opus"], tiebreak=None, verdicts=verdicts)
    assert kinds(out, "tiebreak") == []
    assert len(kinds(out, "verify")) == 3


def test_wf9_missing_tiebreak_row_recorded() -> None:
    out = one_finder(
        [item()],
        verdicts={"N1.1": {"vote:0": HOLDS, "vote:1": REFUTES}},
        null_calls=[{"kind": "tiebreak"}],
    )
    assert out["result"]["missing"] == [{"item_id": "N1.1", "role": "tiebreak", "slot": 0}]


# --- WF-10 sweep ---------------------------------------------------------------------------


def sweep_args(**over: Any) -> dict[str, Any]:
    base = {
        "votes": ["opus", "opus", "opus"],
        "tiebreak": None,
        "sweep": "sweep-model",
        "finders": [{"lens": "bugs", "order": "forward"}],
    }
    return make_args(**{**base, **over})


def sweep_items() -> list[dict[str, Any]]:
    return [
        item("a.py", "f", 1, **{"class": "cls-A"}),
        item("b.py", "g", 1, **{"class": "cls-B"}),
        item("c.py", "h", 1, **{"class": "cls-C"}),
    ]


SWEEP_VERDICTS = {
    "N1.1": {"vote:0": HOLDS, "vote:1": HOLDS, "vote:2": HOLDS},
    "N1.2": {"vote:0": HOLDS, "vote:1": REFUTES, "vote:2": REFUTES},
    "N1.3": {"vote:0": REFUTES, "vote:1": REFUTES, "vote:2": REFUTES},
}


def test_rpt19_focus_line_in_sweep_prompt_only_when_set() -> None:
    out = run_round(
        sweep_args(focus="refunds in checkout.py"),
        find={"find:bugs": {"findings": sweep_items()}},
        verdicts=SWEEP_VERDICTS,
        sweep={"findings": []},
    )
    sweeps = kinds(out, "sweep")
    assert sweeps and all(FOCUS_LINE in c["prompt"] for c in sweeps)
    assert not any(FOCUS_LINE in c["prompt"] for c in blind_calls(out))


def test_rpt20c_sweep_prompt_limits_search_to_paths_when_set() -> None:
    out = run_round(
        sweep_args(paths=["src/a.py", "lib/b.py"]),
        find={"find:bugs": {"findings": sweep_items()}},
        verdicts=SWEEP_VERDICTS,
        sweep={"findings": []},
    )
    sweeps = kinds(out, "sweep")
    assert sweeps
    for call in sweeps:
        assert "WHOLE repository" not in call["prompt"]
        assert json.dumps(["src/a.py", "lib/b.py"], separators=(",", ":")) in call["prompt"]


def test_rpt20c_sweep_prompt_searches_whole_repository_without_paths() -> None:
    out = run_round(
        sweep_args(),
        find={"find:bugs": {"findings": sweep_items()}},
        verdicts=SWEEP_VERDICTS,
        sweep={"findings": []},
    )
    for call in kinds(out, "sweep"):
        assert "WHOLE repository" in call["prompt"]


def test_rpt20c_finder_and_verifier_prompts_do_not_mention_paths() -> None:
    out = run_round(
        sweep_args(paths=["src/a.py"]),
        find={"find:bugs": {"findings": sweep_items()}},
        verdicts=SWEEP_VERDICTS,
        sweep={"findings": []},
    )
    for call in kinds(out, "find") + blind_calls(out):
        assert "src/a.py" not in call["prompt"]


def test_wf10_sweep_runs_for_confirmed_classes_only() -> None:
    hit = item("z.py", "zz", 1, of_class="cls-A")
    out = run_round(
        sweep_args(),
        find={"find:bugs": {"findings": sweep_items()}},
        verdicts=SWEEP_VERDICTS,
        sweep={"findings": [hit]},
    )
    sweeps = kinds(out, "sweep")
    assert len(sweeps) == 1
    assert sweeps[0]["opts"]["model"] == "sweep-model"
    assert sweeps[0]["opts"]["phase"] == "Sweep"
    assert "cls-A" in sweeps[0]["prompt"]
    assert "cls-B" not in sweeps[0]["prompt"]
    assert "cls-C" not in sweeps[0]["prompt"]
    assert "of_class" in json.dumps(sweeps[0]["opts"]["schema"])
    swept = [c for c in out["result"]["candidates"] if c["id"].startswith("S")]
    assert [(c["id"], c["of_class"]) for c in swept] == [("S1", "cls-A")]
    s_rows = [v for v in out["result"]["verdicts"] if v["item_id"] == "S1"]
    assert sorted(v["slot"] for v in s_rows) == [0, 1, 2]
    n_batches = {v["batch"] for v in out["result"]["verdicts"] if v["item_id"].startswith("N")}
    assert n_batches == {1}
    assert {v["batch"] for v in s_rows} == {2}


def test_wf10_no_sweep_without_sweep_model() -> None:
    out = run_round(
        sweep_args(sweep=None),
        find={"find:bugs": {"findings": sweep_items()}},
        verdicts=SWEEP_VERDICTS,
    )
    assert kinds(out, "sweep") == []


def test_wf10_sweep_hits_deduped_and_not_tiebroken() -> None:
    items = [item("a.py", "f", 1, **{"class": "cls-A"})]
    fresh = item("z.py", "zz", 1, of_class="cls-A")
    dup = {**items[0], "of_class": "cls-A"}
    out = run_round(
        sweep_args(votes=["sonnet", "sonnet"], tiebreak="opus"),
        find={"find:bugs": {"findings": items}},
        verdicts={
            "N1.1": {"vote:0": HOLDS, "vote:1": HOLDS},
            "S1": {"vote:0": HOLDS, "vote:1": REFUTES},
        },
        sweep={"findings": [dup, fresh]},
    )
    result = out["result"]
    assert [c["id"] for c in result["candidates"]] == ["N1.1", "S1"]
    assert [d["dup_of"] for d in result["dropped"]] == ["N1.1"]
    assert result["candidates"][1]["path"] == "z.py"
    assert kinds(out, "tiebreak") == []


def test_wf10_no_qualifying_class_means_no_sweep_agent() -> None:
    verdicts = {
        f"N1.{n}": {"vote:0": HOLDS, "vote:1": REFUTES, "vote:2": REFUTES} for n in (1, 2, 3)
    }
    out = run_round(
        sweep_args(),
        find={"find:bugs": {"findings": sweep_items()}},
        verdicts=verdicts,
    )
    assert kinds(out, "sweep") == []
    assert any("sweep" in line.lower() for line in out["result"]["log"])


def test_wf10_null_sweep_agent_logged_without_crash() -> None:
    out = run_round(
        sweep_args(),
        find={"find:bugs": {"findings": sweep_items()}},
        verdicts=SWEEP_VERDICTS,
        sweep=None,
    )
    result = out["result"]
    assert result["started"] is True
    assert len(kinds(out, "sweep")) == 1
    assert any("sweep" in line.lower() for line in result["log"])
    assert all(not c["id"].startswith("S") for c in result["candidates"])


# --- WF-11 verdict collection --------------------------------------------------------------


def test_wf11_null_finder_counted_and_logged() -> None:
    out = run_round(
        make_args(votes=["sonnet"], tiebreak=None),
        find={"find:bugs": None, "find:intent": {"findings": [item()]}},
    )
    result = out["result"]
    assert result["stats"]["finders_null"] == 1
    assert result["log"]
    assert [c["id"] for c in result["candidates"]] == ["N2.1"]


def test_wf11_throwing_finder_counts_as_null() -> None:
    out = run_round(
        make_args(votes=["sonnet"], tiebreak=None),
        find={"find:intent": {"findings": [item()]}},
        throw_calls=[{"kind": "find", "label": "find:bugs"}],
    )
    assert out["result"]["stats"]["finders_null"] == 1
    assert [c["id"] for c in out["result"]["candidates"]] == ["N2.1"]


def test_wf11_finder_reply_failing_schema_counts_as_null() -> None:
    out = run_round(
        make_args(votes=["sonnet"], tiebreak=None),
        find={"find:bugs": {"unexpected": []}, "find:intent": {"findings": [item()]}},
    )
    assert out["result"]["stats"]["finders_null"] == 1


def test_wf11_null_verifier_marks_all_its_rows_missing() -> None:
    items = [item("a.py", f"f{n}", n) for n in (1, 2)]
    out = one_finder(
        items, votes=["sonnet", "sonnet"], tiebreak=None, null_calls=[{"kind": "verify", "slot": 1}]
    )
    result = out["result"]
    assert result["stats"]["verifiers_null"] == 1
    assert sorted((m["item_id"], m["role"], m["slot"]) for m in result["missing"]) == [
        ("N1.1", "vote", 1),
        ("N1.2", "vote", 1),
    ]
    assert {v["slot"] for v in result["verdicts"]} == {0}


def test_wf11_omitted_item_is_missing_only_for_that_item() -> None:
    items = [item("a.py", f"f{n}", n) for n in (1, 2)]
    out = one_finder(items, votes=["sonnet"], tiebreak=None, verdicts={"N1.2": {"vote:0": "omit"}})
    result = out["result"]
    assert result["missing"] == [{"item_id": "N1.2", "role": "vote", "slot": 0}]
    assert [v["item_id"] for v in result["verdicts"]] == ["N1.1"]


def test_wf11_duplicate_row_keeps_first_and_logs() -> None:
    out = one_finder(
        [item()],
        votes=["sonnet"],
        tiebreak=None,
        verdicts={"N1.1": {"vote:0": {"holds": True, "reason": "first", "_dup": True}}},
    )
    result = out["result"]
    assert [(v["holds"], v["reason"]) for v in result["verdicts"]] == [(True, "first")]
    assert result["missing"] == []
    assert result["log"]


def test_wf11_unknown_and_foreign_rows_dropped_and_logged() -> None:
    items = [item("a.py", f"f{n}", n) for n in range(1, 9)] + [item("b.py", "g", 9)]
    extra = [
        {"for_id": "N1.1", "kind": "verify", "slot": 0, "row": {"item_id": "N9.9"}},
        {"for_id": "N1.1", "kind": "verify", "slot": 0, "row": {"item_id": "N1.9"}},
    ]
    out = one_finder(items, votes=["sonnet"], tiebreak=None, extra_rows=extra)
    result = out["result"]
    ids = [v["item_id"] for v in result["verdicts"]]
    assert sorted(ids) == sorted(f"N1.{n}" for n in range(1, 10))
    assert result["missing"] == []
    foreign_batch = next(v["batch"] for v in result["verdicts"] if v["item_id"] == "N1.1")
    assert next(v["batch"] for v in result["verdicts"] if v["item_id"] == "N1.9") != foreign_batch
    assert len(result["log"]) >= 2


# --- WF-12 result shape --------------------------------------------------------------------


def test_wf12_result_shape_stats_and_echo() -> None:
    args = make_args(recheck=[{"id": "F2", "path": "a.py"}])
    out = run_round(
        args,
        find={"find:bugs": {"findings": [item()]}, "find:intent": None},
        verdicts={"N1.1": {"vote:0": HOLDS, "vote:1": REFUTES}},
        null_calls=[{"kind": "tiebreak"}],
    )
    result = out["result"]
    assert set(result) == RESULT_KEYS
    assert result["provenance"] == PROVENANCE
    assert (result["v"], result["started"], result["plan_id"]) == (1, True, "plan-1")
    assert result["echo"] == {
        "level": "high",
        "mode": "code",
        "finders": args["finders"],
        "votes": ["sonnet", "opus"],
        "tiebreak": "opus",
        "recheck_ids": ["F2"],
    }
    calls = out["calls"]
    returned = sum(1 for c in calls if not (c["kind"] == "find" and c["label"] == "find:intent"))
    assert result["stats"] == {
        "agents_started": len(calls),
        "agents_returned": returned - len(kinds(out, "tiebreak")),
        "finders_null": 1,
        "verifiers_null": 1,
    }
    assert all(isinstance(line, str) for line in result["log"])
    assert re.fullmatch(r"[0-9a-f]{8}", result["checksum"])
    verdict = result["verdicts"][0]
    assert {"item_id", "kind", "role", "slot", "model", "batch", "holds", "severity", "reason",
            "evidence", "trigger", "prevented_by", "needs_decision"} <= set(verdict)  # fmt: skip


# --- WF-13 checksum parity -----------------------------------------------------------------

VECTORS = ["", "abc", "foobar", "Привет, мир", "emoji \U0001f600 mix", "lone \ud800 surrogate"]
KNOWN_FNV = {"": "811c9dc5", "a": "e40c292c", "foobar": "bf9cf968"}


def test_wf13_js_fnv_matches_published_vectors() -> None:
    out = run_js(probe_fnv=list(KNOWN_FNV))
    assert out["fnv"] == list(KNOWN_FNV.values())


def test_wf13_fnv_parity_with_python() -> None:
    from review_cycle import checksum

    out = run_js(probe_fnv=VECTORS)
    assert out["fnv"] == [checksum.fnv1a32(v) for v in VECTORS]


def rich_result() -> dict[str, Any]:
    """Round whose result has C, V (with options), D and M records and awkward text."""
    tricky = [
        item("a.py", "f", 1, claim="Привет \U0001f600 lone \ud800", snippet="x = 1"),
        item("a.py", "f", 2, claim="dup", snippet="x = 1"),
        item("b.py", "g", 1, claim="tab\there\x1f\x1e"),
    ]
    options = [{"label": "keep", "observable": "same"}, {"label": "drop", "observable": "gone"}]
    nd = {"criterion": 3, "before": "b", "after": "a", "intent_quote": "q", "options": options}
    args = make_args(votes=["sonnet", "sonnet"], tiebreak=None, finders=[
        {"lens": "bugs", "order": "forward"}])  # fmt: skip
    out = run_round(
        args,
        find={"find:bugs": {"findings": tricky}},
        verdicts={
            "N1.1": {"vote:0": {"holds": True, "needs_decision": nd, "reason": "ж"}},
            "N1.3": {"vote:1": "omit"},
        },
    )
    result: dict[str, Any] = out["result"]
    assert result["dropped"] and result["missing"]
    return result


def test_wf13_result_checksum_parity_with_python() -> None:
    from review_cycle import checksum

    result = rich_result()
    assert checksum.result_checksum(result) == result["checksum"]


# --- RPT-15 amendments ---------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["code", "document"])
def test_wf11_unusable_finder_items_dropped_without_consuming_ids(mode: str) -> None:
    good = "logic" if mode == "code" else "gap"
    bad_category = "logic" if mode == "document" else "gap"
    items = [
        item("", "f", 1, category=good),
        item("a.py", "f", 2, claim="", category=good),
        item("a.py", "f", 3, category=bad_category),
        item("a.py", "f", 4, category=good),
    ]
    out = one_finder(items, mode=mode, votes=["sonnet"], tiebreak=None)
    result = out["result"]
    assert [c["id"] for c in result["candidates"]] == ["N1.1"]
    assert result["candidates"][0]["claim"] == "claim a.py-f-4"
    assert sum("dropped" in line for line in result["log"]) == 3


def test_wf10_unusable_sweep_items_dropped_and_logged() -> None:
    bad = item("z.py", "zz", 1, claim="", of_class="cls-A")
    good = item("y.py", "yy", 1, of_class="cls-A")
    out = run_round(
        sweep_args(),
        find={"find:bugs": {"findings": sweep_items()}},
        verdicts=SWEEP_VERDICTS,
        sweep={"findings": [bad, good]},
    )
    result = out["result"]
    assert [c["id"] for c in result["candidates"] if c["id"].startswith("S")] == ["S1"]
    assert any("sweep item 1 dropped" in line for line in result["log"])


def test_wf11_omitted_row_is_logged() -> None:
    out = one_finder(
        [item(), item("a.py", "g", 2)],
        votes=["sonnet"],
        tiebreak=None,
        verdicts={"N1.2": {"vote:0": "omit"}},
    )
    assert any("N1.2" in line for line in out["result"]["log"])


def test_wf4_finder_prompt_tools_and_preexisting_note() -> None:
    prompt = kinds(one_finder([]), "find")[0]["prompt"]
    assert "read-only gh" in prompt
    assert "unchanged code" in prompt
    assert "Pre-existing" in prompt


def test_wf8_recheck_prompt_says_entries_matched_by_id() -> None:
    args = make_args(votes=["sonnet"], tiebreak=None, recheck=[{"id": "F3", "path": "a.py"}])
    prompt = kinds(run_round(args), "verify")[0]["prompt"]
    assert 'matched by their "id" field' in prompt


# --- RPT-16 repository root ----------------------------------------------------------------

ROOT_LINE = "Repository root: /repo. Every path below is relative to it."


def test_wf8_every_agent_prompt_states_repository_root() -> None:
    out = run_round(
        sweep_args(votes=["sonnet", "sonnet"], tiebreak="opus"),
        find={"find:bugs": {"findings": sweep_items()}},
        verdicts={
            "N1.1": {"vote:0": HOLDS, "vote:1": HOLDS},
            "N1.2": {"vote:0": HOLDS, "vote:1": REFUTES},
        },
        sweep={"findings": []},
    )
    assert {c["kind"] for c in out["calls"]} == {"find", "verify", "tiebreak", "sweep"}
    for call in out["calls"]:
        assert ROOT_LINE in call["prompt"], call["label"]
