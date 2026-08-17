"""Assert player-card numeric surfaces are internally consistent.

Works for every skater card kind that uses ``pbp`` + ``html_renderer``
(NHL, PWHL, prospect, junior). Goalie/team cards use separate renderers.

Run: python3 -m player_cards.validate_card path/to/card.json [...]
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any


def _issues_for_profile(profile: dict[str, Any], *, name: str = "card") -> list[str]:
    from .html_renderer import write_player_card_html
    from .shot_map import _split_shots

    issues: list[str] = []
    pbp = profile.get("pbp") or {}
    bio = profile.get("bio") or {}
    src = profile.get("sources") or {}
    pg = pbp.get("per_game") or {}
    shots = pbp.get("shots") or []
    gp = int(pbp.get("games_played") or 0)
    games = int(pbp.get("games") or gp or 0) or 1
    league = str(profile.get("league") or "").lower()
    pbp_only = league in {"pwhl", "prospect"} or src.get("card_kind") in {
        "junior_player",
        "nhl_prospect",
        "pwhl_player",
    } or bool(bio.get("undrafted"))

    if not pbp:
        return [f"{name}: no pbp block (skip skater checks)"]

    ng, gl = _split_shots(shots)
    sc = int(pbp.get("shot_count") or -1)
    goals = int(pbp.get("goals") or -1)
    if sc != len(shots):
        issues.append(f"shot_count {sc} != len(shots) {len(shots)}")
    if len(shots) != len(ng) + len(gl):
        issues.append(f"shots {len(shots)} != plotted {len(ng)+len(gl)}")
    if goals != len(gl):
        issues.append(f"goals {goals} != plotted goals {len(gl)}")

    if games and sc >= 0 and pg.get("Shots") is not None:
        if abs(float(pg["Shots"]) * games - sc) > 1.05:
            issues.append(
                f"Shots/gp {pg['Shots']}*{games}={float(pg['Shots'])*games:.1f} != shot_count {sc}"
            )
    if games and goals >= 0 and pg.get("Goals") is not None:
        if abs(float(pg["Goals"]) * games - goals) > 1.05:
            issues.append(
                f"Goals/gp {pg['Goals']}*{games}={float(pg['Goals'])*games:.1f} != goals {goals}"
            )
    xg = float(pbp.get("xg_total") or 0)
    xg_sum = round(sum(float(s.get("xg") or 0) for s in shots), 2)
    if abs(xg - xg_sum) > 0.15:
        issues.append(f"xg_total {xg} != sum markers {xg_sum}")
    if games and pg.get("xG") is not None and abs(float(pg["xG"]) * games - xg) > 0.55:
        issues.append(f"xG/gp {pg['xG']}*{games} != xg_total {xg}")

    if int(pbp.get("points") or 0) != int(pbp.get("goals") or 0) + int(pbp.get("assists") or 0):
        issues.append("points != goals+assists")

    ct = pbp.get("count_totals") or {}
    if ct.get("Shots") is not None and sc >= 0 and int(ct["Shots"]) != sc:
        issues.append(f"count_totals.Shots {ct['Shots']} != shot_count {sc}")
    if ct.get("Goals") is not None and goals >= 0 and int(ct["Goals"]) != goals:
        issues.append(f"count_totals.Goals {ct['Goals']} != goals {goals}")
    if ct.get("SOG") is not None and sc >= 0 and int(ct["SOG"]) > sc:
        issues.append(f"SOG {ct['SOG']} > shot_count {sc}")
    if games and ct.get("SOG") is not None and pg.get("SOG") is not None:
        if abs(float(pg["SOG"]) * games - float(ct["SOG"])) > 0.51:
            issues.append(f"SOG/gp {pg['SOG']}*{games} != count SOG {ct['SOG']}")
    if games and pbp.get("assists") is not None and pg.get("Assists") is not None:
        if abs(float(pg["Assists"]) * games - float(pbp["assists"])) > 1.05:
            issues.append(
                f"Assists/gp {pg['Assists']}*{games} != assists {pbp['assists']}"
            )

    ep = bio.get("ep_season_totals") or {}
    clubs = bio.get("season_clubs") or []
    if clubs and ep:
        if int(ep.get("goals") or 0) != sum(int(c.get("g") or 0) for c in clubs):
            issues.append("ep.goals != sum season_clubs.g")
        if int(ep.get("assists") or 0) != sum(int(c.get("a") or 0) for c in clubs):
            issues.append("ep.assists != sum season_clubs.a")
        if int(ep.get("games_played") or 0) != sum(int(c.get("gp") or 0) for c in clubs):
            issues.append("ep.gp != sum season_clubs.gp")

    pbp_by = src.get("pbp_by_club") or {}
    if pbp_by:
        if sum(int(v.get("gp") or 0) for v in pbp_by.values()) != gp:
            issues.append("sum pbp_by_club.gp != games_played")
        if sum(int(v.get("g") or 0) for v in pbp_by.values()) != goals:
            issues.append("sum pbp_by_club.g != goals")

    with tempfile.TemporaryDirectory() as td:
        hp = Path(td) / "c.html"
        write_player_card_html(profile, hp)
        text = hp.read_text(encoding="utf-8")

    if ep.get("games_played") and gp and abs(int(ep["games_played"]) - gp) > 1:
        vit = re.search(r'class="vitals"[^>]*>(.*?)</div>', text, re.S)
        vtxt = re.sub(r"<[^>]+>", " ", vit.group(1) if vit else "")
        if str(int(ep["games_played"])) not in vtxt:
            issues.append(
                f"vitals missing season GP {ep['games_played']} (PBP {gp})"
            )
        if "PBP" not in vtxt:
            issues.append("vitals missing PBP sample tag when season≠PBP")
        map_sub = re.search(r"Card generated from (\d+) games of PBP", text)
        if not map_sub or int(map_sub.group(1)) != gp:
            issues.append(f"map subtitle GP != pbp games_played {gp}")
        if f"season {int(ep['games_played'])} GP" not in text:
            issues.append(
                f"map subtitle missing season {ep['games_played']} GP note"
            )

    sm = re.search(r'class="shot-map-stats">(.*?)</div>\s*</div>', text, re.S)
    hdr = {
        b: a
        for a, b in re.findall(r"<b>([^<]+)</b><span>([^<]+)</span>", sm.group(1) if sm else "")
    }
    if sc >= 0 and int(float(hdr.get("shots", -1))) != sc:
        issues.append(f"HTML shots {hdr.get('shots')} != {sc}")
    if goals >= 0 and int(float(hdr.get("goals", -1))) != goals:
        issues.append(f"HTML goals {hdr.get('goals')} != {goals}")

    foot = re.search(
        r"No goal \((\d+)\).*Goal \((\d+)\).*?(\d+)\+(\d+)=(\d+)", text, re.S
    )
    if not foot:
        issues.append("missing shot-map footer equation")
    else:
        a, b, c, d, e = map(int, foot.groups())
        if a != len(ng) or b != goals or a + b != e or c + d != e or e != sc:
            issues.append(f"footer {foot.groups()} vs ng={len(ng)} goals={goals} sc={sc}")

    sd = re.search(r'class="shot-dots">(.*?)</g>', text, re.S)
    sg = re.search(r'class="shot-goals">(.*?)</g>', text, re.S)
    n_shot = len(re.findall(r"<circle ", sd.group(1))) if sd else -1
    n_goal_c = len(re.findall(r"<circle ", sg.group(1))) if sg else -1
    if n_shot != len(ng):
        issues.append(f"SVG shot circles {n_shot} != {len(ng)}")
    if n_goal_c != len(gl) * 2:
        issues.append(f"SVG goal circles {n_goal_c} != {len(gl)*2}")

    m = re.search(
        r'bar-row__lbl">Shots</span>.*?bar-row__pct">([^<]+)</span>', text, re.S
    )
    if m:
        raw = m.group(1).strip()
        if pbp_only:
            try:
                v = float(raw.rstrip("%"))
                # PBP-only cards must show the rate, not a bare percentile.
                if raw.endswith("%") and pg.get("Shots") is not None:
                    # Allow % only when prefer_value fell back; still flag if far from rate.
                    if abs(v - float(pg["Shots"])) > 0.05 and abs(v - float(pg["Shots"]) * 100) > 1:
                        issues.append(f"Shots pillar {raw} != per_game {pg.get('Shots')}")
                elif pg.get("Shots") is not None and abs(v - float(pg["Shots"])) > 0.05:
                    issues.append(f"Shots pillar {v} != per_game {pg.get('Shots')}")
            except ValueError:
                issues.append(f"Shots pillar unparsable {raw}")
        elif raw not in {"—", "-"} and not raw.endswith("%"):
            # NHL/A3Z percentile bars must carry a trailing % so they aren't
            # read as shot counts next to the map.
            try:
                float(raw)
                issues.append(f"Shots pillar percentile missing % suffix: {raw}")
            except ValueError:
                pass

    rows = dict(
        re.findall(
            r'rate-row__lbl">([^<]+)</span>\s*<span class="rate-row__val">([^<]+)</span>',
            text,
        )
    )
    for label, key in (
        ("Shots per Game", "Shots"),
        ("Goals per Game", "Goals"),
        ("Expected Goals per Game", "xG"),
        ("Shots on Goal per Game", "SOG"),
        ("Assists per Game", "Assists"),
    ):
        if label in rows and pg.get(key) is not None:
            try:
                if abs(float(rows[label]) - float(pg[key])) > 0.02:
                    issues.append(f"{label} HTML {rows[label]} != pg {pg.get(key)}")
            except ValueError:
                issues.append(f"{label} HTML unparsable {rows[label]}")

    return [f"{name}: {msg}" for msg in issues]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("paths", nargs="+", type=Path)
    args = p.parse_args(argv)
    all_issues: list[str] = []
    for path in args.paths:
        profile = json.loads(path.read_text(encoding="utf-8"))
        all_issues.extend(_issues_for_profile(profile, name=path.name))
    for msg in all_issues:
        print(msg)
    if all_issues:
        print(f"FAIL: {len(all_issues)} issue(s)")
        return 1
    print("OK: no mismatches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
