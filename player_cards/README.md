# player_cards — how these visuals are built

This package generates hockey stat cards (skater, goalie, team, prospect) as
PNG images. Everything runs through one CLI:

```
python3 -m player_cards "<player name or team abbrev>" [flags]
```

This doc exists so a future you (or anyone else) can add a new card type, a
new metric, or a new chart without re-deriving the pipeline from scratch.

## 1. The pipeline, end to end

Every card follows the same three-stage shape:

```
resolve + fetch data  →  build a "profile" dict  →  render HTML  →  screenshot to PNG
   (source.py)            (profile.py)              (renderer.py)    (png_export.py)
```

**Generators** (`player_cards/generators/`) — one module per kind, one output tree:

| Kind | Module | Output |
|---|---|---|
| `nhl_player` | `generators/nhl_player.py` | `output/nhl/players/` |
| `nhl_goalie` | `generators/nhl_goalie.py` | `output/nhl/goalies/` |
| `nhl_prospect` | `generators/nhl_prospect.py` | `output/nhl/prospects/` |
| `nhl_team` | `generators/nhl_team.py` | `output/nhl/teams/` |
| `pwhl_player` | `generators/pwhl_player.py` | `output/pwhl/players/` |
| `junior_player` | `generators/junior_player.py` | `output/junior/players/` |

```
python3 -m player_cards "Sidney Crosby" --kind nhl_player
python3 -m player_cards "Igor Shesterkin" --kind nhl_goalie
python3 -m player_cards --kind junior_player --batch
```

1. **Source layer** (`nhl_bio.py`, `instat_source.py`, `team_source.py`,
   `goalie_source.py`, `cap_source.py`, ...): talks to an external API or reads
   cached local CSVs, and returns plain dicts/lists. No HTML, no rendering
   logic — just "go get the numbers."
2. **Profile layer** (`profile.py`, `goalie_profile.py`, `team_profile.py`):
   orchestrates the source-layer calls for one player/team, computes derived
   metrics (percentiles, averages, projections), and assembles one big dict —
   the "profile" — that has everything the renderer needs. This is the layer
   to extend when you want a **new metric**.
3. **Renderer layer** (`html_renderer.py`, `goalie_renderer.py`,
   `team_renderer.py`): takes a profile dict and returns a big HTML string
   (self-contained, inline `<style>`, no external JS). This is the layer to
   extend when you want a **new visual**.
4. **Export** (`png_export.py`): writes the HTML to a temp file, opens it in
   headless Chromium via Playwright, screenshots it, done. You never touch
   this layer — it's generic across all card types.

Entry point: `python3 -m player_cards` dispatches through
`player_cards/generators/` (one module per card kind). Goalies and team
cards never go through the skater renderer.
**Every card type goes through this one CLI** — there should never be a
one-off throwaway script per card; if you're tempted to write one, add it
as a generator module instead.

## 2. Every external endpoint used

### NHL's public API (`api-web.nhle.com/v1`) — bio, rosters, official stats
| Endpoint | Used for | File |
|---|---|---|
| `/roster/{team}/{season}` | Current roster (by position group) | `build_store.py`, `shooter_hands.py`, `team_source.py` |
| `/player/{id}/landing` | Full bio, season-by-season totals, draft info, headshot | `nhl_bio.py`, `goalie_profile.py` |
| `/player/{id}/game-log/{season}/2` | Per-game log (used to attribute PBP games to a specific goalie) | `goalie_pbp_metrics.py` |
| `/draft/picks/{year}/all` | Draft-day team/round/pick/amateur club | `draft_source.py` |
| `/standings/now` (307-redirects to `/standings/{date}`) | Record, points, division/conf rank, streak, L10, goal diff | `team_source.py` |

Always send `headers={"User-Agent": "PlayerCards/1.0"}` — some of these 404 or
behave oddly without one. `/standings/now` **redirects**; pass
`follow_redirects=True` or you'll get an empty 307 body.

### NHL's stats API (`api.nhle.com/stats/rest/en`) — official team/skater stats
| Endpoint | Used for | File |
|---|---|---|
| `/team/summary?cayenneExp=seasonId=X and gameTypeId=2` | **All 32 teams in one call**: PP%/PK%/faceoff%/points%/GF-GA per game/shots per game | `team_source.py` |
| `/skater/summary?cayenneExp=...teamId=N&sort=[...]` | Full-team scoring leaders (G/A/P/GP), sorted | `team_source.py` |
| `/team` | `{id, triCode}` map for every franchise (needed to join `/team/summary`'s numeric `teamId` back to an abbrev) | `team_source.py` |

This is the API that made real 32-team percentile ranking possible on the
team card **without** an expensive InStat download — one cheap call gets
every team's official stats at once. Reach for this before reaching for a
big InStat harvest whenever the stat you want is something the NHL itself
publishes (goals, shots, PP/PK, faceoffs, standings).

### NHL name search (`search.d3.nhle.com/api/v1/search/player`)
Player name → playerId/teamAbbrev lookup. Takes `active=true|false` — **prospects
and recently-graduated players often only show up with `active=false`** (the
"active" flag means "on an NHL roster recently," not "exists"). `nhl_bio.py`'s
`fetch_nhl_bio` tries `active=true` first, then falls back. `search_player()`
scores candidates and requires a minimum confidence (≥40) before returning a
match — never returns "the first result" blindly.

### NHL image CDN (`assets.nhle.com`)
Headshots (`/mugs/nhl/{season}/{team}/{id}.png`), team logos
(`/logos/nhl/svg/{tri}_{light|dark}.svg`), action shots. Also a generic
placeholder for players with no photo (`/mgl/nhl/images/headshots/current/168x168/skater.jpg`).

### CapWages (`capwages.com/api/gateway/v1/players/{slug}`)
Contract/cap-hit info shown in the "CONTRACT" box on NHL skater/goalie cards.
`cap_source.py`.

### InStat (via `hudl-scraping/instat_api.py`) — microstats, play-by-play, shot charting
This is a Playwright-driven session against InStat's internal API (not a
public REST API — it's the same one the scouting-hub product uses). All calls
go through `InStatAPI.api_call(method_name, params)`. Methods actually used:

| Method | Used for |
|---|---|
| `scout_uni_search` | Resolve a team name → InStat numeric team_id |
| `scout_uni_gear` | Param/metric dictionary for a stat category (feeds `_build_col_map`) |
| `scout_param_lexical` (via `get_labels`) | Decode a lexicon code → human-readable label. **Never guess a label — always decode it live.** |
| `scout_uni_advanced_matches_list` / `get_matches_list` | A team's season match ID list |
| `scout_uni_team_players_stat` / `get_team_skaters` | Season-aggregate per-player stat rows for a team |
| `scout_uni_match_players_stat` | Per-match player stat rows |
| `scout_uni_match_inf`, `scout_uni_overview_match_stat` | Match metadata |
| `scout_uni_team_matches_stat`, `scout_uni_team_units_stat` | Team-level match/unit rollups |
| `scout_export_params` | Raw PBP action export → the `game_*_pbp.csv` files everything else reads |
| `scout_match_map_shoot_goalie_new_scout` | Real per-shot goalie shot-charting (location, attack type, rebound detail — NOT a proxy) |

**Rate limiting is deliberate, not accidental** — `instat_api.py` sleeps
~0.75-1s + jitter between calls specifically to avoid pattern-detection
firewalls. Don't reduce it. If something needs to go faster, parallelize
across independent Playwright sessions instead (see `chl_style_scrape_parallel.py`-style
scripts for the pattern), never by cutting the per-request sleep.

**Two ways to read a field back out of an InStat response, and they are NOT
interchangeable:**
- `_build_col_map()` + `_parse_player_rows()` (`instat_api.py`) resolves each
  `(param_id, option_id)` to a **readable short-code name** (e.g. `"SC"`,
  `"P"`) via live label lookup. This is convenient but **the same short code
  can mean different things depending on which gear block it came from** —
  e.g. `"P"` resolved to both "Passes" and "Hits" in different blocks this
  season. If you see a metric that looks implausible (a "passes" number in
  the 0.01-0.76/game range), suspect a param collision before trusting it.
- The raw `p{param_id}_o{option_id}` key format bypasses that name resolution
  entirely and is unambiguous. `instat_source.py`'s `INSTAT_CARD_PARAMS` dict
  maps specific, hand-verified param IDs this way. **When in doubt, verify a
  param's real meaning by decoding its live label** (see `/tmp/debug_all_params.py`-style
  probes in this project's history) rather than trusting a hardcoded name.

### Local PBP CSVs (`~/Desktop/.../Instat_API_Downloads/game_*_pbp.csv`, or wherever `team_pbp_dir()` points)
Once exported via `scout_export_params`, everything downstream
(`pbp_metrics.py`, `goalie_pbp_metrics.py`, `team_source.py`) reads these CSVs
directly with pandas — no more InStat calls needed for stats already
downloaded. Columns: `ID, start, end, duration, pos_x, pos_y, player, team,
action, half`. Coordinates are in metres, **attack-normalized per row** (the
team taking the action always has `pos_x` increasing toward the net it's
attacking — verified empirically: both sides' shot rows cluster near the same
high `pos_x`, so shots-for and shots-against need no mirroring before you
plot them on the same rink template).

**InStat logs one physical shot as multiple rows** — a generic `"Shots"` row
plus its specific outcome (`"Shots on goal"` / `"Missed shots"` / `"Goals"`),
and a goal *also* duplicates as `"Shots on goal"` at the same
`(start, player)`. Any code that counts shots by filtering on `_is_shot()`
without deduping will double- or triple-count. Dedupe by grouping on
`(start, player, team)` and keeping one row, preferring `Goals` >
`Shots on goal` > `Missed shots`. This bug was found and fixed twice this
session in two different places (`goalie_pbp_metrics.py`, `team_source.py`) —
check for it a third time before trusting any new shot-counting code.

## 3. How to add a new visual

Worked example: the team card's shot-location heatmap.

1. **Get the raw data into the source layer.** `team_source.py`'s
   `aggregate_team_zone_events()` scans the already-downloaded PBP CSVs once
   and returns plain `{"x": .., "y": .., "xg": .., "goal": bool}` dicts.
   No rendering concerns here — just correct, deduplicated data.
2. **Wire it into the profile.** `team_profile.py` calls the source function
   and adds the result under a new key (`zone_events`) in the profile dict.
3. **Render it.** `shot_map.py`'s `render_team_shot_heatmap_html()` takes that
   list, bins it into a grid, and returns an HTML/SVG string. It reuses the
   existing rink background image and coordinate transform
   (`instat_to_svg()`) — don't reinvent rink calibration, it's already
   calibrated against `assets/half_rink.png`.
4. **Drop it into the page template.** `team_renderer.py`'s
   `render_team_card_html()` just interpolates the returned HTML string into
   the page f-string, inside a `<div class="shot-maps-row">`.

The same shape applies to any new metric: **compute it once in a `*_source.py`
function using real data (no placeholders), thread it through the profile
dict, write a small render function that returns an HTML fragment, and drop
that fragment into the page template.** Never compute a metric inline inside
a renderer function — renderers should only format numbers that are already
correct by the time they arrive.

## 4. Design system / visual language

- `html_renderer.py`'s `shared_card_css()` is the **one shared stylesheet**
  for every card type (colors, `.pillar`/`.bar-row` percentile bars, stat
  tiles, fonts). Always extend this instead of writing a parallel CSS file —
  goalie and team cards both `from .html_renderer import shared_card_css` and
  only add a small `<style>` block on top for their own layout needs.
- Team colors: `team_colors.py` (`get_team_colors(team, league=...)` →
  `{primary, accent, light}`). Every card derives its whole palette from
  these three values plus `color_utils.theme_text_vars()` (handles light/dark
  text contrast automatically).
- Percentile bars (`_bar_row`, `_pillar_col` in `html_renderer.py`) expect a
  `{"percentile": 0.0-1.0 | None}` dict. `None` renders as "—", never a fake
  0 or 50.
- This project follows the general **dataviz skill** conventions (see the
  `dataviz` skill if it's available in your session): sequential single-hue
  ramps for magnitude, a real diverging pair only when there's a genuine
  "above/below baseline" story, status colors (green/red) reserved for
  actual state (streak, goal differential) and never reused as a categorical
  series color, and — the one we broke and then fixed on the team card —
  **a binned heatmap instead of a raw scatterplot once you have more than a
  few hundred points to plot.** A few dozen shots as individual dots is
  readable; a full team-season (thousands) is not, and needs binning.

## 5. Known gotchas (read before you debug the same thing twice)

- **Diacritics break substring team-name matching.** `_is_team_match()`
  (canonical copy: `pwhl_bio.py`) must ASCII-fold both sides
  (`"Brynäs IF"` vs `"Brynas IF"` in a raw CSV) or the roster/percentile
  population silently comes back empty. This function got duplicated once
  (a second unfoldsed copy sat in `pbp_metrics.py`) — if you see it needing a
  fix again, grep for a duplicate before patching just one copy.
- **Hardcoded InStat team IDs can just be wrong.** `PROSPECT_INSTAT_TEAM_IDS`
  in `leagues.py` had two off-by-two errors (Medicine Hat, Oshawa) that
  silently downloaded a *different team's* games into that team's folder.
  If a team's per-game numbers look implausible (13 GP for a full-season
  player, or PBP files where neither team name matches what you expect),
  verify the hardcoded ID against a live `scout_uni_search` call before
  assuming the aggregation logic is at fault.
- **Two different caches can both look "successful" while one is stale.**
  The SQLite card store (`card_store.py`) and the disk-based per-team
  percentile cache (`~/.cache/player-cards/team_pct/`) invalidate
  independently. If a fix doesn't seem to take effect, check both — clearing
  one and not the other reproduces the exact same bug.
- **A card's saved PNG file and its database record can disagree.** Rerunning
  the CLI updates the SQLite profile row immediately but the on-disk PNG only
  gets rewritten if the render step actually executes end to end. Always
  re-open the actual PNG (not just the JSON `sources` output) after a fix to
  confirm it visually changed.
