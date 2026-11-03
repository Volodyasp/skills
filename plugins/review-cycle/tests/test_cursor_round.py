"""Cursor wave driver stays byte-compatible with workflows/review.js."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import HARNESS, PLUGIN_DIR, REVIEW_JS
from review_cycle.checksum import result_checksum

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

ROUND = PLUGIN_DIR / "workflows" / "cursor-round.mjs"


def make_args(**over: Any) -> dict[str, Any]:
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
        "tiebreak": None,
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


def item() -> dict[str, Any]:
    return {
        "category": "logic",
        "class": "class-a.py-f-1",
        "path": "a.py",
        "line": 11,
        "symbol": "f",
        "snippet": "snippet a.py-f-1",
        "claim": "claim a.py-f-1",
        "trigger": "trigger a.py-f-1",
        "evidence": "evidence a.py-f-1",
        "expected": "expected a.py-f-1",
        "broken_by": {"path": "", "line": 0},
        "scope_note": "",
    }


def verdict(item_id: str, *, holds: bool) -> dict[str, Any]:
    return {
        "verdicts": [
            {
                "item_id": item_id,
                "holds": holds,
                "severity": "important" if holds else "",
                "reason": "r",
                "evidence": "e",
                "trigger": "t",
                "prevented_by": "",
                "needs_decision": {
                    "criterion": 0,
                    "before": "",
                    "after": "",
                    "intent_quote": "",
                    "options": [],
                },
            }
        ]
    }


def run_round(tmp: Path, *args: str) -> dict[str, str]:
    proc = subprocess.run(
        ["node", str(ROUND), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    out: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        key, _, value = line.partition(": ")
        out[key] = value
    assert out.get("next"), proc.stdout
    return out


def write_json(path: str, payload: object) -> None:
    Path(path).write_text(json.dumps(payload), encoding="utf-8")


def tasks(out: dict[str, str]) -> list[dict[str, Any]]:
    return json.loads(Path(out["tasks-file"]).read_text(encoding="utf-8"))


def test_cursor_round_matches_review_js(tmp_path: Path) -> None:
    args = make_args()
    args_file = tmp_path / "args.json"
    args_file.write_text(json.dumps(args), encoding="utf-8")
    work = tmp_path / "round"
    opened = run_round(tmp_path, "open", "--dir", str(work), "--args-file", str(args_file))
    assert opened["wave"] == "find"
    found = tasks(opened)
    assert [t["model"] for t in found] == ["fm-test", "fm-test"]
    write_json(found[0]["reply"], {"findings": [item()]})
    write_json(found[1]["reply"], {"findings": []})
    verified = run_round(tmp_path, "fold", "--dir", str(work))
    assert verified["wave"] == "verify"
    for task in tasks(verified):
        write_json(task["reply"], verdict("N1.1", holds=True))
    done = run_round(tmp_path, "fold", "--dir", str(work))
    assert done["next"] == "done"
    result = json.loads(Path(done["result"]).read_text(encoding="utf-8"))

    proc = subprocess.run(
        ["node", str(HARNESS), str(REVIEW_JS)],
        input=json.dumps(
            {
                "args": args,
                "find": {"find:bugs": {"findings": [item()]}, "find:intent": {"findings": []}},
                "default_spec": {
                    "holds": True,
                    "severity": "important",
                    "reason": "r",
                    "evidence": "e",
                    "trigger": "t",
                },
            }
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    expected = json.loads(proc.stdout)["result"]
    assert result["checksum"] == expected["checksum"]
    assert result["checksum"] == result_checksum(result)
    assert result["stats"] == expected["stats"]
    assert result["candidates"] == expected["candidates"]
    assert result["verdicts"] == expected["verdicts"]


def test_cursor_round_tiebreak_wave(tmp_path: Path) -> None:
    args = make_args(tiebreak="opus")
    args_file = tmp_path / "args.json"
    args_file.write_text(json.dumps(args), encoding="utf-8")
    work = tmp_path / "round"
    opened = run_round(tmp_path, "open", "--dir", str(work), "--args-file", str(args_file))
    found = tasks(opened)
    write_json(found[0]["reply"], {"findings": [item()]})
    write_json(found[1]["reply"], {"findings": []})
    verified = run_round(tmp_path, "fold", "--dir", str(work))
    votes = tasks(verified)
    write_json(votes[0]["reply"], verdict("N1.1", holds=True))
    write_json(votes[1]["reply"], verdict("N1.1", holds=False))
    tied = run_round(tmp_path, "fold", "--dir", str(work))
    assert tied["wave"] == "tiebreak"
    assert tasks(tied)[0]["model"] == "opus"
    write_json(tasks(tied)[0]["reply"], verdict("N1.1", holds=True))
    done = run_round(tmp_path, "fold", "--dir", str(work))
    result = json.loads(Path(done["result"]).read_text(encoding="utf-8"))
    assert result["checksum"] == result_checksum(result)
    assert any(v["role"] == "tiebreak" and v["holds"] for v in result["verdicts"])


def test_cursor_round_refuses_haiku_without_override(tmp_path: Path) -> None:
    args = make_args(votes=["sonnet", "haiku"])
    args_file = tmp_path / "args.json"
    args_file.write_text(json.dumps(args), encoding="utf-8")
    out = run_round(
        tmp_path, "open", "--dir", str(tmp_path / "round"), "--args-file", str(args_file)
    )
    assert out["next"] == "stop"
    assert out["reason"] == "haiku-verifier"
