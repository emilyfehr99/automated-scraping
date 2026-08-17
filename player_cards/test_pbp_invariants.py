"""Regression guards for shared PBP shot-counting invariants (all card kinds)."""

from __future__ import annotations

from player_cards.pbp_metrics import (
    SHOT_MAP_ACTIONS,
    _is_assist_shot,
    _is_shot,
)


def test_shots_blocking_never_offensive_shot() -> None:
    assert _is_shot("Shots blocking") is False
    assert _is_shot("Blocked shots") is False
    assert _is_assist_shot("Shots blocking") is False
    assert _is_assist_shot("Blocked shots") is False
    assert _is_shot("Shots") is True
    assert _is_assist_shot("Shots on goal") is True


def test_shot_map_actions_cover_instat_variants() -> None:
    for act in (
        "Shots",
        "Shots on goal",
        "Goals",
        "Missed shots",
        "Power play shots",
        "Short-handed shots",
    ):
        assert act in SHOT_MAP_ACTIONS
    assert "Shots blocking" not in SHOT_MAP_ACTIONS
    assert "Blocked shots" not in SHOT_MAP_ACTIONS  # defensive/blocked attempts stay off OZ map


if __name__ == "__main__":
    test_shots_blocking_never_offensive_shot()
    test_shot_map_actions_cover_instat_variants()
    print("OK: pbp invariant tests")
