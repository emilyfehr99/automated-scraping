"""Guards: every card kind has its own generator and output tree."""

from __future__ import annotations

from player_cards.card_kinds import (
    CARD_KINDS,
    SPECS,
    default_output_path,
    detect_card_kind,
    normalize_kind,
)
from player_cards.generators import GENERATORS, assert_generators_complete
from player_cards.pbp_metrics import SHOT_MAP_ACTIONS, _is_assist_shot, _is_shot


def test_every_kind_has_a_generator() -> None:
    assert_generators_complete()
    assert set(GENERATORS) == set(CARD_KINDS)
    for kind, mod in GENERATORS.items():
        assert getattr(mod, "KIND") == kind
        assert callable(mod.generate)


def test_output_trees_never_overlap() -> None:
    dirs = [SPECS[k].output_subdir for k in CARD_KINDS]
    assert len(dirs) == len(set(dirs)), dirs
    name = "Test Player"
    paths = [
        default_output_path("nhl_player", name, team="PIT"),
        default_output_path("nhl_goalie", name, team="PIT"),
        default_output_path("nhl_prospect", name, team="PIT"),
        default_output_path("nhl_team", "PIT", team="PIT"),
        default_output_path("pwhl_player", name, team="NY"),
        default_output_path("junior_player", name, amateur_club="Everett Silvertips"),
    ]
    resolved = [str(p) for p in paths]
    assert len(resolved) == len(set(resolved))
    assert "/nhl/players/" in resolved[0]
    assert "/nhl/goalies/" in resolved[1]
    assert "/nhl/prospects/" in resolved[2]
    assert "/nhl/teams/" in resolved[3]
    assert "/pwhl/players/" in resolved[4]
    assert "/junior/players/" in resolved[5]


def test_detect_card_kind_keeps_pipelines_separate() -> None:
    assert detect_card_kind("Sidney Crosby", team="PIT") == "nhl_player"
    assert detect_card_kind("Igor Shesterkin", team="NYR", position="G") == "nhl_goalie"
    assert detect_card_kind("Gavin McKenna", team="TOR", league="prospect") == "nhl_prospect"
    assert detect_card_kind("PIT", team_card=True) == "nhl_team"
    assert detect_card_kind("Sarah Fillier", team="NY", league="pwhl") == "pwhl_player"
    assert (
        detect_card_kind("Landon Dupont", amateur_club="Everett Silvertips", undrafted=True)
        == "junior_player"
    )
    assert normalize_kind("pwhl") == "pwhl_player"
    assert normalize_kind("undrafted") == "junior_player"
    assert normalize_kind("goalie") == "nhl_goalie"


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
    assert "Blocked shots" not in SHOT_MAP_ACTIONS


if __name__ == "__main__":
    test_every_kind_has_a_generator()
    test_output_trees_never_overlap()
    test_detect_card_kind_keeps_pipelines_separate()
    test_shots_blocking_never_offensive_shot()
    test_shot_map_actions_cover_instat_variants()
    print("OK: generator + kind + pbp invariant tests")
