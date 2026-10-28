"""Tests for `cli.parse_tokens` (SPECS CLI-2, CLI-3, CLI-4, CLI-5, CLI-6)."""

from __future__ import annotations

import pytest
from review_cycle.cli import MarkReq, PlanReq, ShowReq, UsageError, parse_tokens


def plan_of(tokens: list[str]) -> PlanReq:
    req = parse_tokens(tokens)
    assert isinstance(req, PlanReq)
    return req


# --- CLI-2 mark ---------------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["intentional", "wontfix", "superseded", "open", "fix"])
def test_cli2_mark_verbs_without_reason(verb: str) -> None:
    assert parse_tokens(["F3", verb]) == MarkReq("F3", verb, None)


@pytest.mark.parametrize("verb", ["intentional", "wontfix", "wrong", "superseded"])
def test_cli2_mark_reason_is_rest_joined_by_one_space(verb: str) -> None:
    req = parse_tokens(["F12", verb, "does", "not", "apply"])
    assert req == MarkReq("F12", verb, "does not apply")


def test_cli2_mark_reason_keeps_quotes_dollar_parens_and_newlines() -> None:
    """CLI-2: tokens are data; `'`, `"`, `$()` and newlines inside a token are kept."""
    reason_tokens = ["it's", 'a "quote"', "$(rm -rf x)", "line1\nline2", "`id`"]
    req = parse_tokens(["F7", "intentional", *reason_tokens])
    assert req == MarkReq("F7", "intentional", " ".join(reason_tokens))


def test_cli2_mark_wrong_with_reason() -> None:
    assert parse_tokens(["F1", "wrong", "false", "positive"]) == MarkReq(
        "F1", "wrong", "false positive"
    )


def test_cli2_mark_wrong_without_reason_is_usage_error() -> None:
    with pytest.raises(UsageError):
        parse_tokens(["F1", "wrong"])


def test_cli2_id_must_be_at_least_one() -> None:
    """CLI-2: n >= 1; `F0 intentional` is neither a mark nor a valid plan (two targets)."""
    with pytest.raises(UsageError):
        parse_tokens(["F0", "intentional"])


def test_cli2_unknown_verb_is_usage_error() -> None:
    with pytest.raises(UsageError):
        parse_tokens(["F3", "bogus"])


# --- RPT-20(d) qualified finding ids -------------------------------------------------------------


def test_rpt20_qualified_mark_id_is_parsed() -> None:
    assert parse_tokens(["code/F3", "wontfix"]) == MarkReq("F3", "wontfix", None, "code")


def test_rpt20_qualified_mark_id_with_a_slug_target() -> None:
    req = parse_tokens(["code-path-src-1a2b3c/F12", "intentional", "because"])
    assert req == MarkReq("F12", "intentional", "because", "code-path-src-1a2b3c")


def test_rpt20_qualified_show_id_is_parsed() -> None:
    assert parse_tokens(["show", "doc-plan-md/F1"]) == ShowReq("F1", "doc-plan-md")


def test_rpt20_bare_id_still_has_no_target() -> None:
    assert parse_tokens(["F3", "wontfix"]) == MarkReq("F3", "wontfix", None, None)
    assert parse_tokens(["show", "F3"]) == ShowReq("F3", None)


@pytest.mark.parametrize(
    "token",
    ["Code/F3", "has..dots/F3", "UPPER/F3", "-leading/F3", "a/b/F3", "/F3", "code/F0"],
)
def test_rpt20_malformed_qualified_id_is_a_usage_error(token: str) -> None:
    with pytest.raises(UsageError):
        parse_tokens([token, "wontfix"])
    with pytest.raises(UsageError):
        parse_tokens(["show", token])


# --- CLI-3 show ---------------------------------------------------------------------------------


def test_cli3_show() -> None:
    assert parse_tokens(["show", "F3"]) == ShowReq("F3")


# --- CLI-4 plan ---------------------------------------------------------------------------------


def test_cli4_empty_tokens_use_defaults() -> None:
    assert plan_of([]) == PlanReq(
        level=None,
        full=False,
        fresh=False,
        model=None,
        intent=None,
        target_kind=None,
        target=None,
        right=None,
        incremental=False,
        focus=None,
        paths=(),
    )


# --- CLI-4+ --incremental (RPT-18) --------------------------------------------------------------


def test_cli4plus_incremental_flag() -> None:
    assert plan_of(["--incremental"]).incremental is True
    assert plan_of(["high", "--incremental"]).incremental is True


@pytest.mark.parametrize("other", ["--full", "--fresh"])
def test_cli4plus_incremental_conflicts_with_full_or_fresh(other: str) -> None:
    with pytest.raises(UsageError, match="--incremental conflicts with --full/--fresh"):
        parse_tokens(["--incremental", other])
    with pytest.raises(UsageError):
        parse_tokens([other, "--incremental"])


@pytest.mark.parametrize("level", ["low", "medium", "high", "xhigh", "max"])
def test_cli4_level_words(level: str) -> None:
    req = plan_of([level])
    assert req.level == level
    assert req.target_kind is None


@pytest.mark.parametrize("word", ["hi", "High", "MAX", "lowest"])
def test_cli4_level_is_exact_lowercase_else_branch_target(word: str) -> None:
    """CLI-4/§14: `hi` is a branch name (the check-out error comes later)."""
    req = plan_of([word])
    assert req.level is None
    assert (req.target_kind, req.target) == ("branch", word)


def test_cli4_flags_in_any_order() -> None:
    a = plan_of(["--full", "high", "--fresh", "feature/a"])
    b = plan_of(["feature/a", "--fresh", "high", "--full"])
    assert a == b
    assert (a.level, a.full, a.fresh) == ("high", True, True)
    assert (a.target_kind, a.target) == ("branch", "feature/a")


def test_cli4_model_alias_valid() -> None:
    assert plan_of(["--model", "claude-opus-4.5[1m]"]).model == "claude-opus-4.5[1m]"
    assert plan_of(["--model", "a" * 64]).model == "a" * 64


@pytest.mark.parametrize("alias", ["bad alias", "x;y", "", "a" * 65, "$(x)", "é"])
def test_cli4_model_alias_invalid(alias: str) -> None:
    with pytest.raises(UsageError):
        parse_tokens(["--model", alias])


@pytest.mark.parametrize("flag", ["--model", "--intent"])
def test_cli4_flag_without_value(flag: str) -> None:
    with pytest.raises(UsageError):
        parse_tokens([flag])


def test_cli6_intent_value_is_kept_verbatim() -> None:
    """CLI-6: parsing keeps the value; file-vs-text resolution happens in the command."""
    assert plan_of(["--intent", "docs/goal.md"]).intent == "docs/goal.md"
    assert plan_of(["--intent", "make it fast\nand safe"]).intent == "make it fast\nand safe"


def test_cli4_unknown_flag() -> None:
    with pytest.raises(UsageError):
        parse_tokens(["--bogus"])


def test_cli4_two_targets() -> None:
    with pytest.raises(UsageError):
        parse_tokens(["feature/a", "feature/b"])
    with pytest.raises(UsageError):
        parse_tokens(["notes.md", "feature/b"])


def test_cli4_target_document() -> None:
    req = plan_of(["docs/spec.md"])
    assert (req.target_kind, req.target) == ("document", "docs/spec.md")


def test_cli4_md_suffix_is_checked_before_other_forms() -> None:
    """CLI-4: ends `.md` wins, even for names that also look like a range."""
    req = plan_of(["a...b.md"])
    assert req.target_kind == "document"


@pytest.mark.parametrize(
    ("token", "ref", "right"),
    [
        ("feature-x...HEAD", "feature-x", "HEAD"),
        ("feature-x...", "feature-x", None),
        ("origin/main...feature/y", "origin/main", "feature/y"),
    ],
)
def test_cli4_range_target(token: str, ref: str, right: str | None) -> None:
    req = plan_of([token])
    assert (req.target_kind, req.target, req.right) == ("range", ref, right)


@pytest.mark.parametrize(("token", "number"), [("#12", "12"), ("12", "12")])
def test_cli4_pr_target(token: str, number: str) -> None:
    req = plan_of([token])
    assert (req.target_kind, req.target) == ("pr", number)


@pytest.mark.parametrize("name", ["feature", "feature/a/b", "release-1.2", "v1.0_rc", "A.b"])
def test_cli4_branch_target(name: str) -> None:
    req = plan_of([name])
    assert (req.target_kind, req.target, req.right) == ("branch", name, None)


@pytest.mark.parametrize(
    "token",
    ["-x", "-", "--", "a..b", "a b", "foo;rm", "a$(x)", "x" * 201, "a\nb", "ü", "a`b`"],
)
def test_cli4_invalid_target_is_usage_error(token: str) -> None:
    """CLI-4/§13: NAME has no leading `-`, no `..`, only [A-Za-z0-9._/-], <= 200 chars."""
    with pytest.raises(UsageError):
        parse_tokens([token])


def test_cli4_name_allows_200_chars() -> None:
    req = plan_of(["x" * 200])
    assert req.target == "x" * 200


@pytest.mark.parametrize("token", ["-x...HEAD", "a..b...HEAD", "feat...-x", "feat...a..b"])
def test_cli4_invalid_range_sides(token: str) -> None:
    with pytest.raises(UsageError):
        parse_tokens([token])


# --- RPT-21 range ref relative suffixes ----------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "ref"),
    [
        ("HEAD~3...HEAD", "HEAD~3"),
        ("HEAD^...HEAD", "HEAD^"),
        ("main~2^2...HEAD", "main~2^2"),
        ("HEAD~1...HEAD", "HEAD~1"),
        ("HEAD...HEAD", "HEAD"),
    ],
)
def test_rpt21_range_ref_accepts_relative_suffixes(token: str, ref: str) -> None:
    req = plan_of([token])
    assert (req.target_kind, req.target) == ("range", ref)


@pytest.mark.parametrize(
    "token",
    ["HEAD@{1}...HEAD", "a:b...HEAD", "-x~1...HEAD", "a..b~1...HEAD", "HEAD{0}...HEAD"],
)
def test_rpt21_range_ref_rejects_at_brace_colon_dash_dotdot(token: str) -> None:
    with pytest.raises(UsageError):
        parse_tokens([token])


def test_rpt21_range_right_side_rule_is_unchanged() -> None:
    """RPT-21: only `ref` grows new syntax; `right` keeps the old NAME rule."""
    with pytest.raises(UsageError):
        parse_tokens(["HEAD~1...-x"])
    with pytest.raises(UsageError):
        parse_tokens(["HEAD~1...a..b"])


# --- CLI-5 level (parse side) -------------------------------------------------------------------


def test_cli5_untyped_level_is_none() -> None:
    """CLI-5: the parser reports only a typed level; remembered/default come from the command."""
    assert plan_of(["feature/a"]).level is None
    assert plan_of(["--full"]).level is None
    assert plan_of(["low", "--fresh"]).level == "low"


@pytest.mark.parametrize("tokens", [["F3"], ["show"]])
def test_cli2_cli3_bare_id_or_show_asks_for_a_verb(tokens: list[str]) -> None:
    with pytest.raises(UsageError, match="add a verb"):
        parse_tokens(tokens)


@pytest.mark.parametrize("tokens", [["show", "F0"], ["show", "F3", "x"], ["show", "f3"]])
def test_cli3_malformed_show_is_usage_error(tokens: list[str]) -> None:
    with pytest.raises(UsageError):
        parse_tokens(tokens)


@pytest.mark.parametrize("verb", ["open", "fix"])
def test_cli2_open_and_fix_accept_and_keep_a_reason(verb: str) -> None:
    assert parse_tokens(["F3", verb, "note"]) == MarkReq("F3", verb, "note")


@pytest.mark.parametrize("token", ["../x.md", "my notes.md"])
def test_cli4_md_target_is_not_name_checked(token: str) -> None:
    """CLI-4: `.md` is checked first, so any path-like name is a document target."""
    req = plan_of([token])
    assert (req.target_kind, req.target) == ("document", token)


@pytest.mark.parametrize("token", ["#", "#abc", "...HEAD"])
def test_cli4_malformed_pr_or_range_is_usage_error(token: str) -> None:
    with pytest.raises(UsageError):
        parse_tokens([token])


def test_cli4_intent_value_that_looks_like_a_level_is_not_a_level() -> None:
    req = plan_of(["--intent", "high"])
    assert req.level is None
    assert req.intent == "high"
    assert req.target_kind is None


def test_cli4_flags_first_then_level() -> None:
    req = plan_of(["--model", "opus", "low"])
    assert (req.model, req.level, req.target_kind) == ("opus", "low", None)


# --- code review R2 -----------------------------------------------------------------------------


@pytest.mark.parametrize("reason", ["", " ", "\n"])
def test_cli2_wrong_with_blank_reason_is_usage_error(reason: str) -> None:
    with pytest.raises(UsageError):
        parse_tokens(["F1", "wrong", reason])


@pytest.mark.parametrize(
    "tokens", [["--model", "a", "--model", "b"], ["--intent", "x", "--intent", "y"]]
)
def test_cli4_repeated_value_flag_is_usage_error(tokens: list[str]) -> None:
    with pytest.raises(UsageError):
        parse_tokens(tokens)


def test_cli13_data_dir_is_checked_first_and_must_be_absolute(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from review_cycle.cli import main

    assert main(["merge", "--data-dir", "", "--state-dir", "s"]) == 3  # --result missing
    assert main(["continue", "--data-dir=${CLAUDE_PLUGIN_DATA}", "--state-dir", "s"]) == 3
    assert main(["cli", "--data-dir", "relative/dir", "high"]) == 3
    assert "--data-dir must be an absolute path" in capsys.readouterr().err


# --- RPT-19 --focus / --path ---------------------------------------------------------------------


def test_rpt19_focus_is_parsed_and_stripped() -> None:
    assert plan_of(["--focus", "  look here  "]).focus == "look here"


def test_rpt19_focus_needs_a_value() -> None:
    with pytest.raises(UsageError):
        parse_tokens(["--focus"])


def test_rpt19_focus_empty_or_whitespace_is_a_usage_error() -> None:
    for value in ("", "   ", "\n"):
        with pytest.raises(UsageError, match="--focus needs text"):
            parse_tokens(["--focus", value])


def test_rpt19_focus_over_500_chars_is_a_usage_error() -> None:
    with pytest.raises(UsageError, match="--focus is longer than 500 characters"):
        parse_tokens(["--focus", "x" * 501])


def test_rpt19_focus_at_the_limit_is_fine() -> None:
    assert plan_of(["--focus", "x" * 500]).focus == "x" * 500


def test_rpt19_focus_given_twice_is_a_usage_error() -> None:
    with pytest.raises(UsageError, match="--focus given more than once"):
        parse_tokens(["--focus", "a", "--focus", "b"])


def test_rpt19_focus_works_on_a_document_target() -> None:
    req = plan_of(["docs/spec.md", "--focus", "wording"])
    assert (req.target_kind, req.focus) == ("document", "wording")


def test_rpt19_path_is_repeatable_and_kept_in_order_given() -> None:
    """Sorting into the state-dir slug happens at resolution time, not here (CLI-4)."""
    req = plan_of(["--path", "src/a", "--path", "src/b"])
    assert req.paths == ("src/a", "src/b")


def test_rpt19_path_needs_a_value() -> None:
    with pytest.raises(UsageError):
        parse_tokens(["--path"])


@pytest.mark.parametrize("value", ["", "-x", "-"])
def test_rpt19_path_empty_or_leading_dash_is_a_usage_error(value: str) -> None:
    with pytest.raises(UsageError):
        parse_tokens(["--path", value])


def test_rpt19_more_than_ten_paths_is_a_usage_error() -> None:
    tokens = [t for i in range(11) for t in ("--path", f"src/p{i}")]
    with pytest.raises(UsageError):
        parse_tokens(tokens)


def test_rpt19_ten_paths_is_fine() -> None:
    tokens = [t for i in range(10) for t in ("--path", f"src/p{i}")]
    assert len(plan_of(tokens).paths) == 10


def test_rpt19_path_on_a_document_target_is_a_usage_error() -> None:
    with pytest.raises(UsageError, match="--path works only in code mode"):
        parse_tokens(["docs/spec.md", "--path", "src/a"])


def test_rpt19_path_before_the_target_also_checks_the_mode() -> None:
    with pytest.raises(UsageError, match="--path works only in code mode"):
        parse_tokens(["--path", "src/a", "docs/spec.md"])


def test_rpt19_focus_and_path_coexist_with_other_flags() -> None:
    req = plan_of(["high", "--full", "--focus", "text", "--path", "src/a"])
    assert (req.level, req.full, req.focus, req.paths) == ("high", True, "text", ("src/a",))
