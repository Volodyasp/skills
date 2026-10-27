"""Pure round decisions (RND-5, RND-7, RND-13..RND-15, RPT-18 scope/choose helpers)."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from review_cycle import rounds

IDS = {"src/a.py": "id-a", "src/b.py": "id-b", "docs/ф.md": "id-ф"}


def test_change_id_is_sha256_over_sorted_path_id_lines() -> None:
    """RND-5: sha256("\\n".join(path \\x1f id) over sorted paths)."""
    expected = hashlib.sha256(
        "\n".join(f"{p}\x1f{IDS[p]}" for p in sorted(IDS)).encode("utf-8")
    ).hexdigest()
    assert rounds.change_id(IDS) == expected


def test_change_id_ignores_mapping_order() -> None:
    """RND-5."""
    reversed_ids = dict(reversed(list(IDS.items())))
    assert rounds.change_id(reversed_ids) == rounds.change_id(IDS)


def test_change_id_differs_when_an_id_or_a_path_changes() -> None:
    """RND-5."""
    base = rounds.change_id(IDS)
    assert rounds.change_id({**IDS, "src/a.py": "other"}) != base
    assert rounds.change_id({**IDS, "src/c.py": "id-a"}) != base
    assert rounds.change_id({k: v for k, v in IDS.items() if k != "src/b.py"}) != base


def test_scope_round_one_is_full_whatever_the_flags() -> None:
    """RPT-18: round 1 is always the whole branch, incremental ignored (CLI-4+)."""
    scope = rounds.decide_scope(1, False, True, False, {"src/a.py": "old"}, IDS)
    assert scope["kind"] == "full"
    assert sorted(scope["files"]) == sorted(IDS)


def test_scope_full_flag_forces_full() -> None:
    """RPT-18: `--full` (or a forced rerun) means the whole branch, any round."""
    scope = rounds.decide_scope(3, True, False, False, IDS, IDS)
    assert scope["kind"] == "full"
    assert sorted(scope["files"]) == sorted(IDS)


def test_scope_full_flag_beats_base_changed() -> None:
    """RPT-18: `--full` wins over base change; its kind still reflects the change."""
    assert rounds.decide_scope(3, True, False, True, IDS, IDS)["kind"] == "full_base_changed"


def test_scope_base_changed_under_full_is_full_base_changed() -> None:
    """RPT-18 (replaces RND-20): base change kind applies whenever the scope is `full`."""
    scope = rounds.decide_scope(2, True, False, True, IDS, IDS)
    assert scope["kind"] == "full_base_changed"
    assert sorted(scope["files"]) == sorted(IDS)


def test_scope_incremental_wins_over_base_changed() -> None:
    """RPT-18: `--incremental` stays `since`; the base-changed line is handled separately."""
    scope = rounds.decide_scope(3, False, True, True, IDS, IDS)
    assert scope["kind"] == "since"


def test_scope_incremental_at_round_two_is_since() -> None:
    """RPT-18: the old RND-9 `n <= 2` restriction is gone; round 2 can be incremental."""
    prev = {**IDS, "src/b.py": "old"}
    scope = rounds.decide_scope(2, False, True, False, prev, IDS)
    assert scope["kind"] == "since" and scope["files"] == ["src/b.py"]


def test_scope_since_lists_changed_new_and_deleted_files() -> None:
    """RPT-18: new or changed diff-ids are in scope; ids that vanished are `deleted`."""
    prev = {"a": "1", "b": "2", "c": "3"}
    cur = {"a": "1", "b": "changed", "d": "4"}
    scope = rounds.decide_scope(3, False, True, False, prev, cur)
    assert scope["kind"] == "since"
    assert sorted(scope["files"]) == ["b", "d"]
    assert scope["deleted"] == ["c"]


@pytest.mark.parametrize("round_n", [2, 3, 4, 7])
def test_scope_incremental_applies_from_round_two(round_n: int) -> None:
    """RPT-18."""
    scope = rounds.decide_scope(round_n, False, True, False, {"a": "1"}, {"a": "2"})
    assert scope["kind"] == "since"
    assert scope["files"] == ["a"]


def test_scope_incremental_without_previous_ids_falls_back_to_full() -> None:
    """RPT-18: state.file_ids missing -> full_fallback."""
    scope = rounds.decide_scope(3, False, True, False, None, IDS)
    assert scope["kind"] == "full_fallback"
    assert sorted(scope["files"]) == sorted(IDS)


def test_scope_neither_full_nor_incremental_at_round_two_is_a_programming_error() -> None:
    """RPT-18: the choose step always resolves one of them first; this path is unreachable."""
    with pytest.raises(ValueError, match="full or incremental"):
        rounds.decide_scope(2, False, False, False, IDS, IDS)


@pytest.mark.parametrize(
    ("lines", "files", "small"),
    [(50, 3, True), (0, 0, True), (51, 3, False), (50, 4, False), (500, 40, False)],
)
def test_is_small_boundaries(lines: int, files: int, small: bool) -> None:
    """RND-13: lines <= 50 and files <= 3."""
    assert rounds.is_small(lines, files) is small


def finding(**over: Any) -> dict[str, Any]:
    base = {"status": "open", "severity": "important", "first_round": 1, "origin": "introduced"}
    return {**base, **over}


def test_reconsider_asks_for_a_surviving_important_finding_in_round_four() -> None:
    """RND-14."""
    assert rounds.reconsider_question(4, [finding(first_round=2)]) is True
    assert rounds.reconsider_question(5, [finding(first_round=1)]) is True


def test_reconsider_does_not_ask_before_round_four() -> None:
    """RND-14."""
    assert rounds.reconsider_question(3, [finding()]) is False


@pytest.mark.parametrize(
    "over",
    [
        {"first_round": 3},
        {"severity": "nit"},
        {"status": "fixed"},
        {"status": "intentional"},
        {"origin": "pre_existing"},
        {"origin": "out_of_scope"},
    ],
)
def test_reconsider_ignores_findings_that_do_not_qualify(over: dict[str, Any]) -> None:
    """RND-14: excludes later findings, nits, closed ones, pre-existing and out-of-scope."""
    assert rounds.reconsider_question(4, [finding(**over)]) is False


def test_reconsider_one_qualifying_finding_among_others_is_enough() -> None:
    """RND-14."""
    assert rounds.reconsider_question(4, [finding(severity="nit"), finding(first_round=2)])


@pytest.mark.parametrize(
    ("typed", "last", "full", "expected"),
    [
        (None, "high", False, False),
        ("high", "high", False, False),
        ("low", "high", False, True),
        ("high", "low", False, True),
        (None, "high", True, True),
        ("high", "high", True, True),
    ],
)
def test_rerun_unchanged_table(typed: str | None, last: str, full: bool, expected: bool) -> None:
    """RND-7: another typed level or --full restarts a round on unchanged code."""
    assert rounds.rerun_unchanged(typed, last, full) is expected


def cfg(finders: int, votes: list[str], tiebreak: str | None, sweep: str | None) -> dict[str, Any]:
    return {
        "finders": [{"lens": f"l{i}", "order": "forward"} for i in range(finders)],
        "finder_model": "sonnet",
        "votes": votes,
        "tiebreak": tiebreak,
        "keep_rule": "all2",
        "depth": "x",
        "sweep": sweep,
    }


def test_agent_estimate_without_tiebreak_or_sweep() -> None:
    """RND-15: b = ceil((15 + recheck)/8); verifiers = votes x b."""
    est = rounds.agent_estimate(cfg(2, ["sonnet", "sonnet"], None, None), 0)
    assert (est["finders"], est["verifiers"], est["tiebreak"], est["sweep"]) == (2, 4, 0, 0)
    assert est["total"] == 6


def test_agent_estimate_with_tiebreak() -> None:
    """RND-15: tie-break <= b."""
    est = rounds.agent_estimate(cfg(4, ["sonnet", "opus"], "opus", None), 0)
    assert (est["verifiers"], est["tiebreak"], est["total"]) == (4, 2, 10)


def test_agent_estimate_recheck_raises_batch_count() -> None:
    """RND-15: 15 + 1 = 16 -> 2 batches; 15 + 2 = 17 -> 3 batches."""
    assert rounds.agent_estimate(cfg(1, ["sonnet"], None, None), 1)["verifiers"] == 2
    assert rounds.agent_estimate(cfg(1, ["sonnet"], None, None), 2)["verifiers"] == 3


def test_agent_estimate_sweep_is_one_plus_vote_count() -> None:
    """RND-15: sweep <= 1 + len(votes)."""
    est = rounds.agent_estimate(cfg(6, ["opus", "opus", "opus"], None, "sonnet"), 0)
    assert est["sweep"] == 4
    assert est["total"] == 6 + 3 * 2 + 0 + 4


def test_scope_since_with_only_deleted_files() -> None:
    """RPT-18: nothing changed, one id vanished -> empty files, one deleted."""
    scope = rounds.decide_scope(3, False, True, False, {"a": "1", "b": "2"}, {"a": "1"})
    assert scope["kind"] == "since"
    assert scope["files"] == [] and scope["deleted"] == ["b"]


# ---------------------------------------------------------------- RPT-18 choose-step helpers


def test_level_rank_orders_low_to_max() -> None:
    """RPT-18: low < medium < high < xhigh < max."""
    ranks = [rounds.level_rank(w) for w in ("low", "medium", "high", "xhigh", "max")]
    assert ranks == sorted(ranks)


def test_max_earlier_rank_of_no_rounds_is_minus_one() -> None:
    """RPT-18: an empty history never outranks any typed level."""
    assert rounds.max_earlier_rank([]) == -1
    assert rounds.level_rank("low") > rounds.max_earlier_rank([])


def test_max_earlier_rank_is_the_highest_level_seen() -> None:
    """RPT-18."""
    entries = [{"level": "low"}, {"level": "xhigh"}, {"level": "medium"}]
    assert rounds.max_earlier_rank(entries) == rounds.level_rank("xhigh")


def test_count_noun_pluralises() -> None:
    """RPT-18/RPT-17: `_count`'s pluralisation, shared with the choose step."""
    assert [rounds.count_noun(n, "file") for n in (0, 1, 2)] == ["0 files", "1 file", "2 files"]


def test_estimate_total_matches_agent_estimate_at_the_given_scope() -> None:
    """RPT-18: wraps `level_config` + `agent_estimate`, small-diff rule applied."""
    from review_cycle.levels import level_config

    total = rounds.estimate_total("high", "code", None, lines=3, items=2, recheck_n=0)
    expected_cfg = level_config("high", "code", None, True)  # 3 lines/2 files is small
    expected = rounds.agent_estimate(expected_cfg, 0)["total"]
    assert total == expected


def test_estimate_total_small_diff_rule_is_code_only() -> None:
    """RPT-18: the small-diff cut never applies to document mode."""
    from review_cycle.levels import level_config

    total = rounds.estimate_total("high", "document", None, lines=3, items=2, recheck_n=0)
    expected_cfg = level_config("high", "document", None, False)
    expected = rounds.agent_estimate(expected_cfg, 0)["total"]
    assert total == expected
