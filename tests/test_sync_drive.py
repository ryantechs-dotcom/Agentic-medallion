"""Drive sync filters: each problem sends only its own eval and results folders."""

import pytest

import sync_drive


def test_p1_eval_skips_other_problems():
    source, rules = sync_drive.source_and_filters("eval", "p1")
    assert source == "eval"
    assert "- /p2/**" in rules and "- /p3/**" in rules
    assert "- CLAUDE.md" in rules


@pytest.mark.parametrize("problem", ["p2", "p3"])
def test_other_problems_send_their_subfolder(problem):
    source, rules = sync_drive.source_and_filters("eval", problem)
    assert source == f"eval/{problem}"
    assert not any(rule.startswith("+") for rule in rules)


def test_results_only_own_run_folders():
    source, rules = sync_drive.source_and_filters("results", "p2")
    assert source == "results"
    assert rules[-2:] == ["+ /*_p2_*/**", "- **"]


def test_unknown_problem_rejected():
    with pytest.raises(ValueError, match="MEDRAG_PROBLEM"):
        sync_drive.source_and_filters("eval", "P2")
