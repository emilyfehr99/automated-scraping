# 🏒 Player Cards Analytics & Generation Engine

A unified, production-grade analytics and visualization engine that generates high-fidelity player cards across all hockey domains: active NHL skaters, NHL goaltenders, PWHL stars, drafted prospects, draft-eligible junior talent, prospect goaltenders, and complete NHL franchise team cards.

---

## 📑 Table of Contents
1. [System Architecture](#-system-architecture)
2. [The 7 Card Archetypes & Scripts Involved](#-the-7-card-archetypes--scripts-involved)
3. [Deep Dive Per Card Archetype](#-deep-dive-per-card-archetype)
   - [1. Active NHL Skater (`nhl_player`)](#1-active-nhl-skater-nhl_player)
   - [2. Active NHL Goaltender (`nhl_goalie`)](#2-active-nhl-goaltender-nhl_goalie)
   - [3. Drafted NHL Prospect (`nhl_prospect`)](#3-drafted-nhl-prospect-nhl_prospect)
   - [4. Junior / Undrafted Skater (`junior_player`)](#4-junior--undrafted-skater-junior_player)
   - [5. Goalie Prospect — Drafted & Undrafted (`junior_goalie`)](#5-goalie-prospect--drafted--undrafted-junior_goalie)
   - [6. PWHL Player (`pwhl_player`)](#6-pwhl-player-pwhl_player)
   - [7. NHL Team Card (`nhl_team`)](#7-nhl-team-card-nhl_team)
4. [Master Inventory of All Scripts & Modules](#-master-inventory-of-all-scripts--modules)
5. [Smart Auto-Detection & Routing Engine](#-smart-auto-detection--routing-engine)
6. [Data Integrity & Zero-Failure Fallback System](#-data-integrity--zero-failure-fallback-system)
7. [CLI & Programmatic API Usage](#-cli--programmatic-api-usage)

---

## 🏛 System Architecture

The player card engine operates on a layered, pipeline architecture:

```mermaid
flowchart TD
    A[Input: Player Name / Club / Tri] --> B[Smart Card Classifier: card_kinds.py]
    B --> C{Dispatch Generator: generators/}
    
    subgraph Data Layer
        D1[NHL Official API: nhl_bio.py, nhl_instat.py]
        D2[InStat Play-by-Play & Microstats: instat_source.py, pbp_metrics.py]
        D3[EliteProspects API & Scraper: ep_api.py, ep_profile.py]
        D4[Salary Cap Engine: cap_source.py]
        D5[NHLe Translation Model: prospect_nhle.py, prospect_source.py]
        D6[PWHL Stats & Media: pwhl_bio.py, pwhl_photos.py]
    end

    subgraph Profile Builders
        P1[profile.py - Skaters]
        P2[goalie_profile.py - NHL Goalies]
        P3[prospect_goalie_profile.py - Junior Goalies]
        P4[team_profile.py - NHL Teams]
    end

    subgraph Rendering & Export Layer
        R1[html_renderer.py - Skater HTML]
        R2[goalie_renderer.py - Goalie HTML]
        R3[team_renderer.py - Team HTML]
        R4[shot_map.py - Rink Coordinates]
        E1[png_export.py - Headless Chrome PNG Render]
    end

    C --> Data Layer
    Data Layer --> Profile Builders
    Profile Builders --> Rendering & Export Layer
    Rendering & Export Layer --> Out[High-Res 1200x675 PNG & HTML]
```

---

## 🎴 The 7 Card Archetypes & Scripts Involved

Every card archetype is governed by its dedicated generator in `player_cards/generators/` and backed by specific data pipelines and renderers:

| Card Archetype | Kind Key | Entry Generator Script | Profile & Data Engine Scripts | Rendering Scripts | Output Directory |
|---|---|---|---|---|---|
| **Active NHL Skater** | `nhl_player` | [`generators/nhl_player.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/generators/nhl_player.py) | [`profile.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/profile.py), [`pbp_metrics.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/pbp_metrics.py), [`nhl_bio.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/nhl_bio.py), [`cap_source.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/cap_source.py), [`instat_source.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/instat_source.py) | [`html_renderer.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/html_renderer.py), [`shot_map.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/shot_map.py), [`png_export.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/png_export.py) | `player_cards/output/nhl/players/` |
| **Active NHL Goaltender** | `nhl_goalie` | [`generators/nhl_goalie.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/generators/nhl_goalie.py) | [`goalie_profile.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/goalie_profile.py), [`goalie_source.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/goalie_source.py), [`goalie_pbp_metrics.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/goalie_pbp_metrics.py), [`nhl_bio.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/nhl_bio.py), [`cap_source.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/cap_source.py) | [`goalie_renderer.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/goalie_renderer.py), [`shot_map.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/shot_map.py), [`png_export.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/png_export.py) | `player_cards/output/nhl/goalies/` |
| **Drafted NHL Prospect** | `nhl_prospect` | [`generators/nhl_prospect.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/generators/nhl_prospect.py) | [`profile.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/profile.py), [`prospect_source.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/prospect_source.py), [`prospect_nhle.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/prospect_nhle.py), [`ep_profile.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/ep_profile.py), [`nhl_bio.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/nhl_bio.py), [`draft_source.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/draft_source.py) | [`html_renderer.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/html_renderer.py), [`shot_map.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/shot_map.py), [`png_export.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/png_export.py) | `player_cards/output/nhl/prospects/` |
| **Junior / Undrafted Skater** | `junior_player` | [`generators/junior_player.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/generators/junior_player.py) | [`profile.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/profile.py), [`prospect_source.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/prospect_source.py), [`prospect_nhle.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/prospect_nhle.py), [`ep_profile.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/ep_profile.py), [`amateur_brands.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/amateur_brands.py) | [`html_renderer.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/html_renderer.py), [`shot_map.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/shot_map.py), [`png_export.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/png_export.py) | `player_cards/output/junior/players/` |
| **Goalie Prospect (Drafted & Undrafted)** | `junior_goalie` | [`generators/junior_goalie.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/generators/junior_goalie.py) | [`prospect_goalie_profile.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/prospect_goalie_profile.py), [`goalie_pbp_metrics.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/goalie_pbp_metrics.py), [`nhl_bio.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/nhl_bio.py), [`amateur_brands.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/amateur_brands.py), [`draft_source.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/draft_source.py) | [`goalie_renderer.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/goalie_renderer.py), [`shot_map.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/shot_map.py), [`png_export.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/png_export.py) | `player_cards/output/junior/goalies/` |
| **PWHL Skater** | `pwhl_player` | [`generators/pwhl_player.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/generators/pwhl_player.py) | [`profile.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/profile.py), [`pwhl_bio.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/pwhl_bio.py), [`pwhl_photos.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/pwhl_photos.py), [`pwhl_vitals.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/pwhl_vitals.py), [`pbp_metrics.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/pbp_metrics.py) | [`html_renderer.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/html_renderer.py), [`shot_map.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/shot_map.py), [`png_export.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/png_export.py) | `player_cards/output/pwhl/players/` |
| **NHL Team Card** | `nhl_team` | [`generators/nhl_team.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/generators/nhl_team.py) | [`team_profile.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/team_profile.py), [`team_source.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/team_source.py), [`nhl_bio.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/nhl_bio.py), [`cap_source.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/cap_source.py), [`team_colors.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/team_colors.py) | [`team_renderer.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/team_renderer.py), [`team_charts.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/team_charts.py), [`shot_map.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/shot_map.py), [`png_export.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/png_export.py) | `player_cards/output/nhl/teams/` |

---

## 🔍 Deep Dive Per Card Archetype

---

### 1. Active NHL Skater (`nhl_player`)
* **Intended Subject**: Full-time active NHL forwards and defensemen.
* **Involved Scripts**:
  - `generators/nhl_player.py`: Generator dispatcher & filename routing.
  - `profile.py`: Primary skater profile engine (calculates 5v5 Game Score, league percentiles, microstat averages).
  - `nhl_bio.py`: Official NHL API client (roster status, sweater number, vitals, flag, headshot).
  - `cap_source.py`: Real-time contract cap hit, AAV %, expiry year, and contract status scraper.
  - `pbp_metrics.py`: 5v5 microstat calculations (zone entries, exits, scoring chances, rush offense).
  - `instat_source.py` & `pbp_harvest.py`: Local InStat CSV discovery and event parsing.
  - `html_renderer.py`: Skater HTML layout compiler.
  - `shot_map.py`: Half-rink coordinate shot scatter plotter.
  - `png_export.py`: Playwright headless Chrome 1200x675 PNG rasterizer.
* **Every Visual & Data Component Included**:
  1. **Header & Vitals**: Full Name + Country Flag emoji, Headshot Cutout with object-positioning, Official NHL Team Logo, Sweater Number badge, Position (`C`/`LW`/`RW`/`LD`/`RD`), Team Name, Season (`2025-26`), Height (ft/in), Weight (lbs), Shoots (`L`/`R`), Team Colors.
  2. **Salary Cap & Contract Box**: Cap Hit ($M/yr), Cap Hit % of upper limit, Term / Expiry Year, Status (`ELC`, `RFA`, `UFA`, `NTC`, `NMC`, `35+`).
  3. **5v5 Game Score Headline**: 5v5 Game Score per 60, League Percentile Rank (`0-100th %ile`) vs qualified NHL forwards or defensemen, tier classification color badge.
  4. **The 3 Core Metric Pillars (12 Micro-Stats)**:
     - *Offense Pillar*: 5v5 Primary Points/60, Individual Expected Goals (`ixG/60`), Scoring Chances Created/60, Rush Offense Shots/60.
     - *Defense Pillar*: 5v5 Defensive Impact / Goals Against Suppression/60, Defensive Zone Puck Recoveries/60, DZ Exits with Possession/60, Quality of Competition (QoC).
     - *Transition Pillar*: Controlled Zone Entries/60, Zone Entry Success %, Controlled Zone Exits/60, Controlled Exit Success %.
  5. **Season Summary (6 Stat Tiles)**: Games Played (GP), Goals (G), Assists (A), Points (PTS), Plus/Minus (+/-), Time On Ice per Game (TOI/GP).
  6. **Rink Shot Map Scatter Plot**: Half-rink SVG plotting all 5v5 shots `(pos_x, pos_y)` with xG-weighted dot sizing, goal indicators, net target area, and summary tally (Total Shots, Total xG Sum, Total Goals).
  7. **Context Footer**: Minimum GP threshold, percentile pool size definition, tracking data attribution.

---

### 2. Active NHL Goaltender (`nhl_goalie`)
* **Intended Subject**: Active NHL starting and backup goaltenders.
* **Involved Scripts**:
  - `generators/nhl_goalie.py`: Generator dispatcher.
  - `goalie_profile.py`: NHL goalie profile builder (matches NHL API game logs with InStat per-shot tracking).
  - `goalie_source.py`: InStat aggregate goalie statistics.
  - `goalie_pbp_metrics.py`: 12-way situational splits, rebound metrics, posture tracking.
  - `nhl_bio.py`: Official NHL API bio, sweater number, team, headshot.
  - `cap_source.py`: Goalie contract cap hit, AAV %, expiry year.
  - `goalie_renderer.py`: Goalie HTML template engine (9-zone net grid, posture splits).
  - `shot_map.py`: Defensive half-rink shot scatter plotter.
  - `png_export.py`: Playwright headless Chrome PNG rasterizer.
* **Every Visual & Data Component Included**:
  1. **Header & Vitals**: Full Name + Country Flag, Goalie Headshot Cutout, Official Team Logo, Sweater Number, Position (`G`), Team Name, Height, Weight, Catches Hand (`L`/`R`), Team Colors.
  2. **Salary Cap & Contract Box**: Cap Hit ($M), Cap Hit %, Expiry Year, Contract Status.
  3. **Headline Hero Block**: Save % (SV%) headline badge, GAA, Shots Faced, League Percentile Rank vs qualified NHL goalies (min 10 GP), quick situation tags (5v5 EV SV%, Rush SV%, Rebound Control Rate %).
  4. **12 Situational SV% Splits**:
     - *Strength Splits*: Overall SV%, 5v5 Even Strength SV%, Penalty Kill (SH) SV%, Power Play SV%.
     - *Shot Danger Splits*: High Danger (<15m) SV%, Medium Range (15-25m) SV%, Long Range (>25m) SV%, Inner Slot Area SV%.
     - *Tactical Sequences*: Rush Chances SV%, Royal Road Cross-Slot Passes SV%, Forecheck / Cycle SV%, Perimeter / Flanks SV%.
     - *Sample Flags*: `(small n)` indicator for low-sample buckets (<50 shots).
  5. **Season Summary (6 Stat Tiles)**: Games Played (GP), Record (`W-L-OTL`), Goals Against Average (GAA), Shutouts (SO), Quality Starts (`QS (QS%)`), Shots Faced (SA).
  6. **Lateral & Angle Splits**: Shots from Left (n, SV%), Shots from Right (n, SV%), Left Flank Outside (n, SV%), Right Flank Outside (n, SV%), Inner Slot (n, SV%).
  7. **Save Posture & Technique Tracking**: Butterfly Posture (n, SV%), In Motion / Recovery (n, SV%), Scramble / Beaten (n, SV%).
  8. **Rebound & Workload Analytics**: Rebound Control Rate (%), High-Danger Workload (%), Rebounds Allowed (%), Workload (Shots/GP), Saves/GP.
  9. **9-Zone Net Ice Grid Heatmap**: 3x3 Quadrant breakdown (Top Left/Center/Right, Mid Left/Center/Right, Low Left/Center/Right) with shot counts, goals against, and SV% colored by performance.
  10. **Defensive Shot Map**: Scatter plot of all shots faced in defensive zone with xG bubble sizes, goal markers, and shot/goal/xG tallies.

---

### 3. Drafted NHL Prospect (`nhl_prospect`)
* **Intended Subject**: Skaters drafted by an NHL franchise playing in Junior (OHL/WHL/QMJHL), NCAA, USHL, or European pro leagues.
* **Involved Scripts**:
  - `generators/nhl_prospect.py`: Prospect skater generator.
  - `profile.py`: Profile orchestrator with `league="prospect"` setting.
  - `draft_source.py` & `nhl_bio.py`: Draft database & NHL API draft details resolver.
  - `prospect_nhle.py`: League translation model projecting points per 82 NHL games.
  - `prospect_source.py`: Prospect upside tier probabilities and historical comparable players.
  - `ep_profile.py` & `ep_api.py`: EliteProspects vitals, rankings, and stats integration.
  - `html_renderer.py`: Prospect skater HTML layout compiler.
  - `shot_map.py`: Amateur shot scatter chart.
  - `png_export.py`: Playwright headless Chrome PNG rasterizer.
* **Every Visual & Data Component Included**:
  1. **Header & Vitals**: Full Name + Flag, Amateur Club, League tag (e.g. WHL, NCAA), Height, Weight, Draft Line, Shoots, Drafting NHL Club Logo / Colors.
  2. **Draft Info Box**: Drafting NHL Club, Round, Pick in Round, Overall Pick Number (`#Z Overall (NHL Team)`).
  3. **NHLe Point Projection & Upside Model**: Projected NHL Points / 82 Games, Tier Probability Breakdown (Star Upside %, Top 6 / Top 4 D %, Bottom 6 / Bottom Pair D %, Non-NHL %).
  4. **Top 5 Historical Comparable Players**: Matched by age, league, height/weight, scoring pace, and draft pedigree.
  5. **Microstat Tracking**: 5v5 primary production, rush offense, controlled zone entries/exits.
  6. **Season Summary (6 Stat Tiles)**: Games Played (GP), Goals (G), Assists (A), Points (PTS), Points Per Game (P/GP), Shots On Goal (SOG).
  7. **Amateur Shot Map**: Complete charted amateur shot coordinates with xG sizing and goal indicators.

---

### 4. Junior / Undrafted Skater (`junior_player`)
* **Intended Subject**: Draft-eligible or undrafted skaters playing in junior/college hockey.
* **Involved Scripts**:
  - `generators/junior_player.py`: Junior skater generator.
  - `profile.py`: Populates amateur club statistics, multi-club splits, and per-game tracking rates.
  - `ep_profile.py` & `ep_api.py`: EliteProspects vitals, league rankings, and draft eligibility year.
  - `amateur_brands.py`: Resolves colors, SVG logos, and official branding for CHL, USHL, and NCAA teams.
  - `prospect_nhle.py` & `prospect_source.py`: Age-weighted NHLe projection and draft-year comps.
  - `html_renderer.py`: Junior skater HTML layout compiler.
  - `shot_map.py`: Junior shot scatter chart.
  - `png_export.py`: Playwright headless Chrome PNG rasterizer.
* **Every Visual & Data Component Included**:
  1. **Header & Vitals**: Full Name + Flag, Amateur Club, Junior League, Height, Weight, Shoots, Official Junior Club Logo, Team Colors.
  2. **Draft Status Box**: NHL Draft Eligibility Year (`Undrafted · 2026` / `2027`), Current Amateur Club, Junior League (OHL, WHL, QMJHL, USHL, NCAA).
  3. **NHLe Translation & Comps**: Translated NHL scoring pace, upside probability distribution, draft-year historical comps.
  4. **Tracking Microstats**: Per-game entries, exits, scoring chances created.
  5. **Season Summary (6 Stat Tiles)**: GP, Goals, Assists, Points, Points Per Game (P/GP), Shots On Goal (SOG).
  6. **Amateur Shot Map**: Complete charted junior game shot map.

---

### 5. Goalie Prospect — Drafted & Undrafted (`junior_goalie`)
* **Intended Subject**: Goalie prospects across junior, college, and international leagues (e.g. Carter George, Ilya Nabokov, Mikhail Yegorov).
* **Involved Scripts**:
  - `generators/junior_goalie.py`: Goalie prospect generator.
  - `prospect_goalie_profile.py`: Profile engine equipped with `_extract_best_season_total` and `_synthesize_goalie_profile_from_totals` ensuring 100% data completeness with automatic fallbacks.
  - `goalie_pbp_metrics.py`: 12 situational cuts and rebound metrics.
  - `nhl_bio.py`: Official NHL API bio, draft details, and season totals.
  - `draft_source.py`: NHL draft pick matching.
  - `amateur_brands.py`: Junior club colors and SVG logos.
  - `goalie_renderer.py`: Full goalie layout with context-aware `Draft Info` or `Draft Status` boxes.
  - `shot_map.py`: Defensive shot scatter chart.
  - `png_export.py`: Playwright headless Chrome PNG rasterizer.
* **Every Visual & Data Component Included**:
  1. **Header & Vitals**: Full Name + Flag, Amateur Club, Height, Weight, Draft Line, Catches Hand, Junior Club Logo, Team Colors.
  2. **Draft Status / Draft Info Box**:
     - *Drafted Goalie*: Displays `Draft Info` with Amateur Club, Selection (`Rd X, Pick Y`), and `#Z Overall (NHL Team)`.
     - *Undrafted Goalie*: Displays `Draft Status` with Eligibility Year (`Undrafted · 2026`), Amateur Club, and League.
  3. **Headline Hero Block**: Save % (SV%), GAA, Shots Faced, 5v5 EV SV%, Rush SV%, Rebound Control Rate %, GAA, Shutouts, Quality Start %.
  4. **12 Situational SV% Splits**: Full parity with NHL goalies (Strength, Danger, Tactical Sequences).
  5. **Season Summary (6 Stat Tiles)**: Games Played (GP), Saves, Goals Against Average (GAA), Shutouts (SO), Quality Starts (`QS (QS%)`), Shots Faced (SA).
  6. **Lateral, Technique & Rebound Analytics**: Lateral angles (Left/Right/Flank/Slot), Save Posture (Butterfly, In Motion, Scramble), Rebound Control Rate %, High-Danger Workload %, Shots/GP, Saves/GP.
  7. **9-Zone Net Ice Grid Heatmap**: 3x3 quadrant breakdown with shots faced, goals allowed, and save percentages.
  8. **Charted Shot Map**: Scatter plot of shots faced with xG danger bubble sizes and goal markers.
  9. **Zero-PBP Fallback Engine**: Fully synthesized profiles from verified official season totals when local PBP CSVs are absent.

---

### 6. PWHL Player (`pwhl_player`)
* **Intended Subject**: Professional Women's Hockey League skaters.
* **Involved Scripts**:
  - `generators/pwhl_player.py`: PWHL skater generator.
  - `pwhl_bio.py`: Official PWHL HockeyTech API client (rosters, stats, standings).
  - `pwhl_photos.py` & `pwhl_cutout.py`: High-resolution PWHL headshots and action cutouts.
  - `pwhl_vitals.py`: PWHL team names, sweater numbers, and positions.
  - `pbp_metrics.py`: PWHL microstat rate calculations.
  - `html_renderer.py`: PWHL team color-themed HTML layout.
  - `shot_map.py`: PWHL shot scatter chart.
  - `png_export.py`: Playwright headless Chrome PNG rasterizer.
* **Every Visual & Data Component Included**:
  1. **Header & Vitals**: Full Name + Flag, PWHL Franchise Name (Montreal, Toronto, Boston, Minnesota, New York, Ottawa), Official PWHL Team Logo, Primary Colors, Height, Weight, Shoots.
  2. **PWHL Microstat Tracking**: 5v5 scoring chances, rush entries, controlled exits, puck recoveries.
  3. **Season Summary (6 Stat Tiles)**: Games Played (GP), Goals (G), Assists (A), Points (PTS), Plus/Minus (+/-), Time On Ice per Game (TOI/GP).
  4. **PWHL Shot Map**: Coordinate shot chart with xG sizing and goal markers.

---

### 7. NHL Team Card (`nhl_team`)
* **Intended Subject**: Complete franchise analytic overview for all 32 NHL teams.
* **Involved Scripts**:
  - `generators/nhl_team.py`: Team card generator.
  - `team_profile.py`: Integrates standings, records, goal differential, special teams, and cap commitments.
  - `team_source.py`: Aggregates 5v5 microstat rates across all rostered skaters with in-memory cached PBP files.
  - `team_colors.py`: Official NHL team primary/secondary hex color palettes.
  - `team_renderer.py` & `team_charts.py`: Team HTML template and SVG chart generators.
  - `shot_map.py`: Dual-rink shot plotter.
  - `png_export.py`: Playwright headless Chrome PNG rasterizer.
* **Every Visual & Data Component Included**:
  1. **Header & Team Vitals**: Franchise Name, Official Logo, Primary & Secondary Colors, Division, Conference.
  2. **Team Summary & Cap Commitments**: Record (`W-L-OTL`), Points (PTS), Points % (P%), Goal Differential (+/-), Power Play % (PP%), Penalty Kill % (PK%), Cap Space / Total Cap Committed.
  3. **5v5 Team Efficiency Matrix**: Offensive Generation vs Defensive Suppression relative to league average.
  4. **Team Microstat Profile**: Controlled entry rate, exit success %, scoring chances for/against.
  5. **Goaltending Tandem Summary**: Combined Starter/Backup tandem SV%, GAA, GSAx, Quality Start %.
  6. **Dual-Rink Shot Maps**: Offensive Shots-For Map + Defensive Shots-Against Map.

---

## 🗂 Master Inventory of All Scripts & Modules

Below is the complete file inventory of `player_cards/` grouped by system layer:

```
player_cards/
├── generators/                   # Individual Card Kind Dispatchers
│   ├── __init__.py               # Unified dispatch: generate_card()
│   ├── nhl_player.py             # Active NHL Skater generator
│   ├── nhl_goalie.py             # Active NHL Goalie generator
│   ├── nhl_prospect.py           # Drafted Prospect Skater generator
│   ├── junior_player.py          # Junior/Undrafted Skater generator
│   ├── junior_goalie.py          # Goalie Prospect generator
│   ├── pwhl_player.py            # PWHL Skater generator
│   └── nhl_team.py               # NHL Team Card generator
│
├── Core Profile Engines/         # Assembles Card Data Payloads
│   ├── profile.py                # Primary profile engine for all skaters (NHL/Junior/Prospect/PWHL)
│   ├── goalie_profile.py         # Profile engine for active NHL goalies
│   ├── prospect_goalie_profile.py# Profile engine for junior/drafted goalie prospects with fallbacks
│   └── team_profile.py           # Profile engine for NHL team cards
│
├── Data Sources & Harvest/       # Live APIs, Scrapers & Microstats
│   ├── nhl_bio.py                # Official NHL API (rosters, landing, bio, draft picks, game logs)
│   ├── nhl_instat.py             # NHL InStat API data bridging
│   ├── ep_api.py                 # EliteProspects API client
│   ├── ep_profile.py             # EliteProspects scraper & profile builder
│   ├── instat_source.py          # InStat local CSV reader and player matching
│   ├── instat_pbp_fetch.py       # Playwright/InStat PBP downloader with fallback handling
│   ├── pbp_metrics.py            # 5v5 skater microstat calculations (entries, exits, chances)
│   ├── pbp_harvest.py            # Fast ripgrep/directory harvest of local PBP CSVs
│   ├── pbp_team_cache.py         # In-memory DataFrame caching & frame warming for PBP games
│   ├── goalie_source.py          # InStat aggregate goalie statistics
│   ├── goalie_pbp_metrics.py     # 12-way situational goalie splits & rebound metrics
│   ├── cap_source.py             # CapWages / PuckPedia live salary cap scraping
│   ├── draft_source.py           # Historical and current NHL Draft picks database
│   ├── prospect_source.py        # Prospect tier outcome probabilities & historical comps
│   ├── prospect_nhle.py          # NHLe translation coefficients & projections
│   ├── pwhl_bio.py               # PWHL HockeyTech API client
│   └── team_source.py            # Team-wide roster microstat rate aggregation
│
├── Visual & HTML Renderers/      # Layout, Heatmaps, SVG & Shot Charts
│   ├── html_renderer.py          # Master HTML template engine for skater cards
│   ├── goalie_renderer.py        # Master HTML template engine for goalie cards
│   ├── team_renderer.py          # Master HTML template engine for team cards
│   ├── team_charts.py            # SVG chart and bar generators for team cards
│   ├── shot_map.py               # Half-rink coordinate shot plotter with xG sizing
│   └── pbp_display.py            # Metric labels, groupings, and percentile bar formatters
│
├── Assets, Colors & Layout/      # Media & Design Resolvers
│   ├── headshots.py              # Photo caching, local photo embedding, and headshot fallbacks
│   ├── photo_layout.py           # Aspect ratio and object-position framing
│   ├── amateur_brands.py         # Junior, USHL, and NCAA club colors and logos
│   ├── team_colors.py            # NHL team primary/secondary hex colors
│   ├── color_utils.py            # Hex brightness, contrast, and gradient helpers
│   ├── pwhl_photos.py            # PWHL headshot downloader & local cacher
│   ├── pwhl_cutout.py            # Action photo cutout & silhouette pipeline
│   └── pwhl_vitals.py            # PWHL roster matching & formatting
│
├── Infrastructure & Export/      # System Utilities & CLI
│   ├── card_kinds.py             # Smart automatic card kind classifier
│   ├── png_export.py             # Playwright headless Chrome 1200x675 PNG rasterizer
│   ├── card_store.py             # File-based caching and disk storage
│   ├── disk_cache.py             # HTTP request caching layer
│   ├── validate_card.py          # Data integrity and layout verification assertions
│   └── __main__.py               # player_cards package execution entry point
```

---

## 🧠 Smart Auto-Detection & Routing Engine

When generating a card using `generate_card(player_name)`, the system runs [`card_kinds.py`](file:///Users/emilyfehr8/CascadeProjects/automated-scraping/player_cards/card_kinds.py) to resolve the exact card kind:

```mermaid
flowchart TD
    A["Query: Player Name / Club"] --> B{Team Card Requested?}
    B -->|Yes| K7["nhl_team"]
    B -->|No| C{PWHL League?}
    C -->|Yes| K6["pwhl_player"]
    C -->|No| D{Position: Goalie?}
    
    D -->|Yes| E{Active NHL GP >= 5 or Career >= 10?}
    E -->|Yes| K2["nhl_goalie"]
    E -->|No| K5["junior_goalie"]
    
    D -->|No (Skater)| F{Active NHL GP >= 15 or Career >= 40?}
    F -->|Yes| K1["nhl_player"]
    F -->|No| G{Drafted by NHL Club?}
    G -->|Yes| K3["nhl_prospect"]
    G -->|No| K4["junior_player"]
```

### Dynamic Team & Trade Resolution
- If a player was recently traded or signed (e.g. **Tristan Jarry** to `EDM`), the engine queries the live NHL API landing endpoint (`https://api-web.nhle.com/v1/player/{id}/landing`) to dynamically adopt the player's active team, sweater number, and primary colors.

---

## 🛡 Data Integrity & Zero-Failure Fallback System

1. **No-CSV Prospect Goalie Fallback**:
   - When a goalie plays in a league without local PBP files (e.g. KHL, Europe, or newly drafted junior goalies), `prospect_goalie_profile.py` automatically extracts verified statistics from `bio["season_totals"]` and models complete situational splits, 9-zone net grid heatmaps, and shot maps so **zero cards render with blank dashes or 0 GP**.

2. **InStat Session Resilience**:
   - `instat_pbp_fetch.py` and `team_source.py` cleanly trap remote InStat token expiration and seamlessly fall back to local disk-cached play-by-play files and official NHL stats without crashing.

3. **High-Resolution Headless Chrome PNG Rendering**:
   - `png_export.py` renders pixel-perfect 1200x675 images with embedded base64 assets and webfonts at 2x device scale factor for crisp typography.

---

## ⚡ CLI & Programmatic API Usage

### Live CapWages Contract API

The Player Cards FastAPI server exposes live CapWages lookups (skips the 24h disk cache; 60s in-process throttle). **Team wage pages are preferred** — CapWages usually posts new signings/extensions there before the signings feed or a fully confirmed player page.

```bash
# Prefer CapWages gateway when you have a key (player path); team pages always use HTML
export CAPWAGES_API_KEY=...   # optional

uvicorn player_cards.server:app --host 0.0.0.0 --port 8080

curl "http://127.0.0.1:8080/cap/player?name=Sam%20Steel&player_id=8479351&team=DAL"
curl "http://127.0.0.1:8080/cap/player/8479351?team=DAL"
```

Returns the newest deal as `aav` / `expiry_season` (including CapWages **unconfirmed** extensions on team pages). Prior remaining years may appear as `prior_aav` / `prior_expiry`.

### 1. Interactive CLI Menu
Run without arguments to launch the guided interactive prompt:
```bash
python3 generate_cards.py
```

### 2. Single Card Auto-Detection
Pass any player name; the system automatically resolves position, league, and team:
```bash
# NHL Skater
python3 generate_cards.py "Beckett Sennecke"

# NHL Goaltender
python3 generate_cards.py "Tristan Jarry"

# Drafted NHL Skater Prospect
python3 generate_cards.py "Cayden Lindstrom" --team CBJ

# Junior / Undrafted Skater
python3 generate_cards.py "Landon Dupont" --amateur-club "Everett Silvertips"

# Goalie Prospect (Drafted or Undrafted)
python3 generate_cards.py "Carter George" --amateur-club "Owen Sound"
python3 generate_cards.py "Ilya Nabokov" --amateur-club "Metallurg Magnitogorsk"

# PWHL Skater
python3 generate_cards.py "Marie-Philip Poulin" --team MTL --league pwhl

# NHL Team Card
python3 generate_cards.py "Edmonton Oilers" --kind nhl_team --team EDM
```

### 3. Programmatic Python API
```python
from player_cards.generators import generate_card

# Auto-detect kind
result = generate_card("Carter George", amateur_club="Owen Sound")
print("Card generated at:", result["png"])

# Explicit kind override
team_result = generate_card("Edmonton Oilers", kind="nhl_team", team="EDM")
print("Team card generated at:", team_result["png"])
```

---

## 📂 Output Folder Structure

All generated assets are organized by category under `player_cards/output/`:

```
player_cards/output/
├── nhl/
│   ├── players/    # e.g. beckett-sennecke-ana.png
│   ├── goalies/    # e.g. tristan-jarry-edm-goalie.png
│   ├── prospects/  # e.g. cayden-lindstrom-cbj-prospect.png
│   └── teams/      # e.g. edm-team.png
├── junior/
│   ├── players/    # e.g. landon-dupont-everett-junior.png
│   └── goalies/    # e.g. carter-george-owen-goalie.png, ilya-nabokov-metallurg-goalie.png
└── pwhl/
    └── players/    # e.g. marie-philip-poulin-mtl-pwhl.png
```

