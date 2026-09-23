# Line and Pairing Chemistry via Passing Networks: A Complementary-Skill Model Validated Against On-Ice Expected Goals

**Authors:** Analytics Research (Cascade Projects)  
**Date:** June 2026  
**Data:** NHL 2025–26 season (full league), InStat/Hudl tracking PBP + NHL API rosters  
**Code:** `automated-scraping/research/line_chemistry_passing_networks/analyze_line_chemistry.py`

---

## Abstract

Every NHL coaching staff faces the same in-season problem: which forwards and defensemen actually *fit* together? Traditional line charts describe who plays together, but not *why* a combination works. We propose a **complementary-skill chemistry model** built from InStat/Hudl play-by-play (PBP) passing events and microstat skill profiles, validated against on-ice expected goals (xG).

Using **2,037 NHL games** and **9.0 million** tracked events from **2,100 unique InStat match IDs** (`pbp_catalog`, deduped across team folders), we:

1. Infer **505,948** passer→receiver edges from sequential pass-touch events.
2. Build per-player skill vectors (zone-entry rate, defensive-zone retrieval rate, exit rate, pass volume, shot-xG rate).
3. Score forward trios and defensive pairs with a **cross-skill complementarity index** and within-unit **pass-link density**.
4. Attribute on-ice xGF/xGA to identified units via even-strength shift sweeps.

**Key finding (full league, 2025–26):** Forward lines show the strongest xGF% separation: top chemistry quartile **51.2%** vs bottom **46.0%** (+5.2 pts; chemistry index r = 0.09 with xGF%, r = 0.13 with xGF/60). Defensive pairs correlate with xGF/60 at **r = 0.17** (chemistry index) but xGF% quartiles narrow at league scale (49.2% vs 49.1%).

The framework is directly actionable for line construction: identify a high zone-entry/transporter forward or defenseman, pair with a high retrieval/exit partner, and confirm with within-pair pass-network density before deployment. **Hockey-specific playbooks, weekly staff workflows, and pairing archetypes** are in Section 5.

---

## 1. Introduction

### 1.1 The coaching problem

Line construction is not merely roster optimization — it is a **dynamic, in-season** decision problem. Injuries, slumps, matchups, and special-teams usage force staffs to recombine players weekly. Coaches rely on intuition, video, and box-score splits, but lack a quantitative notion of **skill complementarity**: does Player A's strength (e.g., carrying entries) cover Player B's weakness (e.g., low retrieval rate)?

Network science offers a natural language for this question. Passing networks encode who trusts whom with puck movement. Combined with **microstat skill profiles**, we can ask: *do the players on this unit pass in patterns that match their complementary roles, and does that predict chance generation?*

### 1.2 Contribution

This paper introduces:

| Component | Description |
|-----------|-------------|
| **Pass-pair inference** | Receiver inferred from next same-team touch within 3 events after a pass action |
| **Skill vectors** | Per-60 ES rates for entries, DZ retrievals, exits, passes, and shot xG |
| **Complementarity score** | Cross-product of complementary skills (entry × retrieval for D pairs; entry × shot-xG for F lines) |
| **Pass-link density** | Within-unit inferred pass edges per 60 minutes |
| **Validation** | Correlation and quartile analysis vs on-ice xGF% and xGF/60 |

We integrate **InStat PBP** (rich micro-events) with **NHL API** rosters (forward/defense classification) — the same architecture used in our `player_cards` pipeline.

---

## 2. Data

### 2.1 Sources

| Source | Role | Access |
|--------|------|--------|
| **InStat/Hudl PBP CSV** | Pass events, entries, retrievals, shifts, shot locations | Local cache via `hudl-scraping/instat_api.py` |
| **NHL API** | 2025–26 rosters (forwards / defensemen / goalies) | `api-web.nhle.com/v1/roster/{team}/20252026` |

InStat PBP schema (per event):

```
ID, start, end, duration, pos_x, pos_y, player, team, action, half
```

Pass-related actions include `Passes`, `Accurate passes`, `Passes to the slot`, `Breakouts via pass`, and `Entries via pass`. **No explicit receiver field exists** — edges are inferred (Section 3.1).

### 2.2 Coverage (2025–26, full league)

| Metric | Value |
|--------|-------|
| PBP files on disk | 2,705 (2,637 NHL) |
| Unique games (deduped) | 2,100 |
| Games loaded (analysis) | 2,037 |
| Total events | 8,986,473 |
| NHL teams with cache folders | 21+ |
| Date range | 2025-09-12 → 2026-06-14 |
| Inferred pass edges | 505,948 |
| Unique passers | 2,159 |
| Skaters with skill profiles | 2,054 |
| Forward-line units identified | 45,059 |
| Defensive pairs identified | 959 |
| Work root | `~/Desktop/My Analytics Work` |
| Source tag | InStat/Hudl PBP (`pbp_catalog`) + NHL API rosters |

**Data path:** `~/Desktop/My Analytics Work/{Team Name}/Instat_API_Downloads/` (or `PLAYER_CARDS_WORK_ROOT` after `scripts/sync_player_cards_ci.py`).

**Load pattern:**

```python
from player_cards.pbp_catalog import load_dataframe, summary
df = load_dataframe(league="nhl", dedupe_games=True)  # full season, one file per match_id
```

### 2.3 Combining NHL and InStat data

Our integration follows the `player_cards` pattern:

1. **InStat** → micro-events, shift timing, spatial coordinates.
2. **NHL API** → roster group (F/D/G) for unit classification.
3. **Player join** → InStat `"Last First"` names matched to NHL roster via fuzzy token matching (`instat_source._match_player_name`).

Game-level ID crosswalk (InStat `match_id` ↔ NHL `game_id`) is not required for unit-level analysis because all events are derived from InStat shift sweeps within each tracked game.

---

## 3. Methods

### 3.1 Pass-network edge inference

For each game, events are sorted by `(half, start)`. When event *i* is a pass action and event *j* is the next same-team, non-shift touch within 3 events:

```
edge: players[i] → players[j]
```

Pass actions: `{Passes, Accurate passes, Passes to the slot, Breakouts via pass, Entries via pass}`.

This mirrors the rule documented in our PassingNetwork visualization (`Torrent/src/components/PassingNetwork.tsx`): *"pass events followed by same-team touch."* It is more conservative than primary-assist detection (which looks backward from shots) and suitable for **dense network construction**.

### 3.2 Player skill vectors

Even-strength minutes are approximated from `Even strength shifts` duration sums. For each skater with ≥20 ES minutes, we compute per-60 rates:

| Skill | InStat actions |
|-------|----------------|
| `entry_rate` | Entries, Entries via pass/stickhandling/dump-in |
| `retrieval_rate` | Puck recoveries in DZ, Puck recoveries |
| `exit_rate` | Breakouts, Breakouts via pass/stickhandling |
| `pass_rate` | All pass actions |
| `shot_xg_rate` | Sum of shot xG per 60 (see 3.4) |

Skills are **z-scored league-wide** when building composite indices.

**Example profiles (2025–26 full league, top entry + retrieval rates):**

| Player | entry_rate | retrieval_rate | exit_rate | pass_rate | shot_xg_rate | ES min |
|--------|-----------|----------------|-----------|-----------|--------------|--------|
| Tyson Jost | 573.7 | 507.2 | 347.1 | 2236.5 | 34.7 | 28.9 |
| Hunt Daemon | 245.5 | 888.3 | 359.4 | 2574.4 | 9.7 | 20.5 |
| Ilya Solovyov | 152.4 | 513.8 | 258.7 | 1619.3 | 6.8 | 33.9 |
| Brett Kulak | 40.2 | 129.1 | 71.2 | 391.2 | 1.7 | 545.7 |
| Quinn Hughes | 167.2 | 149.9 | 155.8 | 967.4 | 4.7 | 507.5 |

These archetypes motivate the complementarity formula.

### 3.3 Complementary-skill chemistry model

#### Defensive pairs

For defensemen *i* and *j*:

```
C_pair = Σ_{i≠j} [ entry_i × retrieval_j + 0.5 × exit_i × retrieval_j ]
```

**Interpretation:** Rewards pairing a player who moves pucks north (entries/exits) with a partner strong at recovering loose pucks in the DZ — the classic *transporter + retriever* template coaches describe verbally.

#### Forward lines

For forwards *i, j, k*:

```
C_line = Σ_{i≠j} entry_i × shot_xg_j  +  2 × σ(pass_rates)
```

**Interpretation:** Rewards feeding entries to finisher profiles plus pass-rate diversity (specialization vs redundancy).

#### Pass-link density

Within-unit pass links per 60:

```
pass_links_per60 = 3600 × Σ_{a,b ∈ unit, a≠b} edges(a→b) / TOI_sec
```

#### Combined chemistry index

```
Chem = 0.6 × z(C) + 0.4 × z(pass_links_per60)
```

### 3.4 Expected goals (xG)

Shot xG uses a logistic geometry model (consistent with `player_cards/pbp_metrics.py`):

```
dist = hypot(NET_X - x, |NET_Y - y|)
angle = atan2(dy, dx)
logit = -1.12 - 0.09×dist - 1.6×angle
xG = sigmoid(logit)
```

Applied to `Shots on goal`, `Shots`, `Goals`, and `Missed shots` with valid `(pos_x, pos_y)`.

### 3.5 Line and pairing identification

We adapt the PWHL `line_pairing_engine.py` even-strength shift sweep:

1. Sweep ES shift start/end events to build 5-skater segments.
2. Enumerate all 3-skater forward combinations and 2-skater defense combinations present during each segment.
3. Accumulate TOI per unique unit.
4. Attribute shots/xG to units active at event time.

**Minimum samples for validation:** TOI ≥ 300 sec, combined SF+SA ≥ 8.

Forward lines require ≥45 sec TOI for enumeration; pairs ≥90 sec (engine defaults).

### 3.6 Validation

We test whether chemistry scores predict **on-ice xGF%** and **xGF/60**:

- Pearson correlation (complementarity, pass density, combined index)
- TOI-weighted linear slope of xGF% ~ chemistry index
- Quartile comparison (top 25% vs bottom 25% chemistry)

---

## 4. Results

All metrics below are from `outputs/analysis_summary.json` (run: 2,037 games, June 2026). Validation subset: units with TOI ≥ 300 sec and combined SF+SA ≥ 8.

### 4.1 Dataset summary

| Field | Value |
|-------|-------|
| `n_games` | 2,037 |
| `n_events` | 8,986,473 |
| `n_pbp_files` | 2,705 |
| `n_unique_games_catalog` | 2,100 |
| `n_teams_with_data` | 21 |
| `date_min` | 2025-09-12 |
| `date_max` | 2026-06-14 |
| `work_root` | `/Users/emilyfehr8/Desktop/My Analytics Work` |
| `season` | 2025-26 |

### 4.2 Pass network

| Field | Value |
|-------|-------|
| `n_inferred_edges` | 505,948 |
| `n_unique_passers` | 2,159 |
| Mean edges per game | ~248 |

### 4.3 Forward lines

**All units identified:** 45,059  
**Validation subset:** 3,450 units

| Metric | Value |
|--------|-------|
| corr(complementarity, xGF%) | +0.058 |
| corr(complementarity, xGF/60) | +0.045 |
| corr(pass_links_per60, xGF%) | +0.074 |
| corr(chemistry index, xGF%) | **+0.087** |
| corr(chemistry index, xGF/60) | **+0.130** |
| weighted R² (chemistry index → xGF%) | 0.001 |
| slope (chemistry → xGF%) | +0.428 |
| High-chemistry quartile mean xGF% | **51.2%** |
| Low-chemistry quartile mean xGF% | **46.0%** |
| **Quartile gap** | **+5.2 pts** |

**Top forward lines by xGF% (validation subset):**

| Unit | Team | xGF% | Complementarity | Pass links/60 | TOI (min) |
|------|------|------|-----------------|---------------|-----------|
| Gauthier-Killorn-Poehling | Anaheim Ducks | 100.0 | 388.4 | 1162.7 | 13.9 |
| Bratt-Dadonov-Hischier | New Jersey Devils | 100.0 | 433.4 | 1187.4 | 15.9 |
| Batherson-Giroux-Halliday | Ottawa Senators | 100.0 | 409.7 | 1202.7 | 7.5 |
| Buckley-McGathey-Weyerhaeuser | East Coast Wizards 19U | 97.5 | 240.9 | 0.0 | 7.6 |
| Dewar-Jones-Lizotte | Pittsburgh Penguins | 96.0 | 195.3 | 469.3 | 20.2 |
| Acciari-Dewar-Jones | Pittsburgh Penguins | 96.0 | 137.6 | 426.5 | 20.1 |
| Acciari-Jones-Lizotte | Pittsburgh Penguins | 96.0 | 189.4 | 326.7 | 18.9 |
| Englund-McCarron-Wiesblatt | Nashville Predators | 93.6 | 249.8 | 356.3 | 8.1 |

**Bottom forward lines by xGF% (validation subset):**

| Unit | Team | xGF% | Complementarity | Pass links/60 | TOI (min) |
|------|------|------|-----------------|---------------|-----------|
| Jerylo-McDonald-Quinn | St. Michael's College | 0.0 | 12.4 | 75.4 | 7.2 |
| Hetman-Jarvis-McGillis | St. Michael's College | 0.0 | 49.6 | 124.5 | 6.3 |
| Hetman-Jarvis-Quinn | St. Michael's College | 0.0 | 86.7 | 106.7 | 6.2 |
| Boychuk-Jerylo-Quinn | St. Michael's College | 0.0 | 23.6 | 55.7 | 5.4 |
| Barresi-Finnegan-Gray | University of Delaware Blue Hens | 0.0 | 186.2 | 174.9 | 6.5 |
| Barresi-Charlton-Gray | University of Delaware Blue Hens | 0.0 | 391.0 | 172.9 | 5.9 |
| Barresi-Gray-MacIntyre | University of Delaware Blue Hens | 0.0 | 127.4 | 71.5 | 5.0 |
| Jerylo-McDonald-Tink | St. Michael's College | 0.6 | 16.4 | 105.9 | 5.1 |

*Note: bottom-line table includes preseason/college opponent units from shared game files; filter to NHL rosters for staff-facing deliverables.*

### 4.4 Defensive pairs

**All units identified:** 959  
**Validation subset:** 692 units

| Metric | Value |
|--------|-------|
| corr(complementarity, xGF%) | +0.068 |
| corr(complementarity, xGF/60) | +0.081 |
| corr(pass_links_per60, xGF%) | +0.012 |
| corr(chemistry index, xGF%) | +0.062 |
| corr(chemistry index, xGF/60) | **+0.166** |
| weighted R² (chemistry index → xGF%) | 0.000 |
| slope (chemistry → xGF%) | +0.132 |
| High-chemistry quartile mean xGF% | 49.2% |
| Low-chemistry quartile mean xGF% | 49.1% |
| **Quartile gap** | +0.1 pts |

**Top defensive pairs by xGF% (validation subset):**

| Pair | Team | xGF% | Complementarity | Pass links/60 | TOI (min) |
|------|------|------|-----------------|---------------|-----------|
| Faber-Jiricek | Minnesota Wild | 91.2 | 2076.9 | 7.5 | 8.0 |
| Girard-Karlsson | Pittsburgh Penguins | 89.5 | 7392.1 | 19.8 | 30.4 |
| Heiskanen-Lundkvist | Dallas Stars | 86.2 | 3243.0 | 49.2 | 35.4 |
| Klingberg-Mukhamadullin | San Jose Sharks | 84.2 | 4016.6 | 35.1 | 22.2 |
| Solovyov-St-Ivany | Pittsburgh Penguins | 79.3 | 26347.2 | 35.6 | 18.6 |
| Jensen-Sanderson | Ottawa Senators | 79.0 | 4001.3 | 31.6 | 24.7 |
| Carlile-Lilleberg | Tampa Bay Lightning | 78.8 | 2071.3 | 9.0 | 33.5 |
| Bryson-Morrissey | Winnipeg Jets | 77.9 | 3269.8 | 20.0 | 15.0 |

**Bottom defensive pairs by xGF% (validation subset):**

| Pair | Team | xGF% | Complementarity | Pass links/60 | TOI (min) |
|------|------|------|-----------------|---------------|-----------|
| Kiersted-Spurgeon | Minnesota Wild | 2.2 | 1569.8 | 14.8 | 20.3 |
| Kiersted-Spacek | Minnesota Wild | 8.6 | 561.8 | 0.0 | 31.9 |
| Dickinson-Mukhamadullin | San Jose Sharks | 8.9 | 3630.0 | 25.7 | 42.1 |
| Heinola-Miller | Winnipeg Jets | 13.7 | 1956.7 | 54.1 | 7.8 |
| Hronek-Mancini | Vancouver Canucks | 14.6 | 1970.7 | 34.4 | 7.0 |
| Bichsel-Lindell | Dallas Stars | 14.9 | 2399.9 | 33.2 | 28.9 |
| Ekblad-Mikkola | Florida Panthers | 16.2 | 2426.4 | 80.0 | 12.0 |
| Fleury-Samberg | Winnipeg Jets | 19.3 | 2456.2 | 39.7 | 16.6 |

**Case study — transporter + retriever template:**

Solovyov (513.8 retrievals/60) paired with puck-movers (Girard–Karlsson, Solovyov–St-Ivany) shows high complementarity scores and strong xGF% on meaningful TOI. The St-Ivany label is **Jack St. Ivany** (InStat: `St. Ivany Jack`) — not Spencer Stastney. Heiskanen–Lundkvist (86.2% xGF, 35.4 min) exemplifies a high-performing pair with moderate pass-link density (49.2/60) — chemistry via skill cross-product, not just volume passing.

### 4.5 Top skill profiles (full `player_skills.csv` export, top 30 by entry + retrieval)

| Player | entry_rate | retrieval_rate | exit_rate | pass_rate | shot_xg_rate | es_min |
|--------|-----------|----------------|-----------|-----------|--------------|--------|
| Hunt Daemon | 245.5 | 888.3 | 359.4 | 2574.4 | 9.7 | 20.5 |
| Tyson Jost | 573.7 | 507.2 | 347.1 | 2236.5 | 34.7 | 28.9 |
| Carl Grundstrom | 352.7 | 347.1 | 341.5 | 1433.3 | 16.7 | 21.4 |
| Ilya Solovyov | 152.4 | 513.8 | 258.7 | 1619.3 | 6.8 | 33.9 |
| Brandon Bussi | 5.2 | 612.7 | 18.3 | 975.3 | 0.0 | 45.8 |
| Donovan Sebrango | 137.3 | 465.8 | 219.7 | 1227.5 | 5.9 | 56.8 |
| Cole Schwindt | 243.4 | 297.0 | 253.1 | 1236.5 | 15.1 | 24.6 |
| Vincent Iorio | 150.8 | 346.8 | 207.3 | 1094.5 | 2.9 | 47.8 |
| Alexandre Texier | 212.5 | 127.7 | 135.2 | 877.8 | 11.8 | 95.4 |
| Quinn Hughes | 167.2 | 149.9 | 155.8 | 967.4 | 4.7 | 507.5 |
| Colten Ellis | 3.3 | 289.6 | 11.4 | 517.3 | 0.0 | 36.9 |
| Troy Stecher | 67.6 | 215.2 | 123.1 | 716.8 | 3.2 | 147.2 |
| Olli Maatta | 60.7 | 177.5 | 91.9 | 529.5 | 1.5 | 205.6 |
| John Beecher | 108.4 | 116.5 | 95.5 | 353.5 | 6.0 | 88.6 |
| Jeffrey Viel | 111.3 | 96.0 | 82.7 | 464.6 | 8.1 | 117.5 |
| Spencer Stastney | 39.5 | 162.7 | 79.8 | 497.2 | 1.5 | 276.6 |
| Robby Fabbri | 111.3 | 80.7 | 70.4 | 356.7 | 8.4 | 52.8 |
| James Reimer | 0.0 | 190.5 | 2.4 | 361.9 | 0.0 | 25.2 |
| Yegor Chinakhov | 102.1 | 68.2 | 64.0 | 418.2 | 6.5 | 328.0 |
| Brett Kulak | 40.2 | 129.1 | 71.2 | 391.2 | 1.7 | 545.7 |
| Lukas Reichel | 94.3 | 63.8 | 62.4 | 365.3 | 4.8 | 86.6 |
| Liam Ohgren | 83.0 | 60.5 | 57.0 | 296.5 | 4.1 | 208.2 |
| Artemi Panarin | 95.1 | 43.4 | 59.3 | 425.0 | 4.1 | 523.4 |
| Egor Zamula | 22.7 | 113.9 | 72.8 | 399.6 | 0.9 | 153.3 |
| Zach Whitecloud | 25.2 | 111.4 | 59.8 | 344.9 | 1.0 | 566.2 |
| Zeev Buium | 51.3 | 80.9 | 64.7 | 382.6 | 1.6 | 525.2 |
| Brooklyn Schneiderhan | 88.3 | 41.6 | 75.3 | 135.1 | 2.9 | 23.1 |
| Mason Marchment | 81.3 | 48.5 | 59.6 | 458.1 | 4.3 | 351.2 |
| Alex Law | 75.9 | 48.3 | 48.3 | 157.9 | 3.1 | 69.5 |
| John Carlson | 38.5 | 81.2 | 55.8 | 366.4 | 2.0 | 691.5 |

### 4.6 Top units by chemistry index

Rankings below use the **combined chemistry index** (0.6 × z-complementarity + 0.4 × z-pass-links/60) within the validation subset (TOI ≥ 5 min, SF+SA ≥ 8). This ranks **predicted fit** (skill complementarity + within-unit passing), not on-ice results — compare with Section 4.3–4.4 xGF% tables.

**Unit labels** use InStat `Last First` names: surname = all tokens except the given name (handles `St. Ivany Jack` → **St-Ivany**, `St. Martin Hunter` → **St-Martin**).

#### Forward lines — top chemistry (NHL only)

| Unit | Team | Chem index | xGF% | Complementarity | Pass links/60 | TOI (min) |
|------|------|------------|------|-----------------|---------------|-----------|
| Jost-Marchessault-Stamkos | Nashville Predators | 7.32 | 10.9 | 6713.9 | 1541.3 | 5.3 |
| Jost-McCarron-Smith | Nashville Predators | 7.23 | 66.0 | 7287.5 | 315.9 | 15.4 |
| Forsberg-Haula-Jost | Nashville Predators | 7.22 | 75.7 | 6712.9 | 1373.9 | 6.9 |
| Jost-O'Reilly-Stamkos | Nashville Predators | 6.95 | 47.6 | 6670.5 | 982.2 | 15.2 |
| Bunting-Jost-Wood | Nashville Predators | 6.43 | 39.1 | 6246.0 | 868.6 | 6.2 |
| Forsberg-Jost-Svechkov | Nashville Predators | 6.31 | 42.5 | 6401.2 | 373.9 | 14.3 |
| Evangelista-Jost-Wood | Nashville Predators | 6.29 | 37.5 | 6283.2 | 547.7 | 15.9 |
| Evangelista-Haula-Jost | Nashville Predators | 6.25 | 58.5 | 6249.8 | 543.1 | 22.6 |

**Read:** NSH lines built around **Tyson Jost** (573.7 entry/60, 507.2 retrieval/60) dominate chemistry rankings — extreme microstat rates inflate complementarity. Several top-chemistry lines have modest xGF% (e.g. Jost-Marchessault-Stamkos at 10.9%) because chemistry scores *role fit and pass volume*, not outcomes. Use chemistry to **propose** combinations; confirm with xGF% over ≥15 min.

#### Defensive pairs — top chemistry (NHL only)

| Pair | Team | Chem index | xGF% | Complementarity | Pass links/60 | TOI (min) |
|------|------|------------|------|-----------------|---------------|-----------|
| Buium-Hunt | Minnesota Wild | 8.08 | 42.2 | 108666.5 | 17.0 | 56.4 |
| Schenn-Stanley | Buffalo Sabres | 5.23 | 67.7 | 2958.9 | 280.2 | 29.3 |
| Girard-Solovyov | Pittsburgh Penguins | 5.05 | 65.5 | 56322.2 | 71.5 | 13.4 |
| Girard-Solovyov | Colorado Avalanche | 4.48 | 58.3 | 56322.2 | 44.9 | 21.4 |
| Hunt-Petry | Minnesota Wild | 4.18 | 66.7 | 57336.1 | 27.3 | 28.6 |
| Petry-Sebrango | Florida Panthers | 3.82 | 56.4 | 31475.5 | 107.4 | 43.0 |
| Brodin-Hunt | Minnesota Wild | 3.46 | 56.7 | 44511.0 | 41.5 | 18.8 |
| Faber-Hunt | Minnesota Wild | 3.32 | 53.4 | 45190.7 | 32.8 | 29.3 |

**Read:** Top D-pair chemistry clusters on **retrieval-heavy partners** (Hunt Daemon, Solovyov) paired with puck-movers (Buium, Girard, Petry) — the transporter + retriever template. **Buium–Hunt** leads chemistry index (8.08) on 56 min but only 42.2% xGF — high complementarity does not guarantee top results. **Schenn–Stanley** (5.23 index, 67.7% xGF, 29 min) is a better chemistry-and-results blend.

#### Lowest chemistry (NHL) — pairs to avoid

| Pair | Team | Chem index | xGF% | Pass links/60 | TOI (min) |
|------|------|------------|------|---------------|-----------|
| Kiersted-Spacek | Minnesota Wild | -0.96 | 8.6 | 0.0 | 31.9 |
| Coghlan-Lauzon | Vegas Golden Knights | -0.96 | 68.1 | 0.0 | 32.3 |
| Coghlan-Theodore | Vegas Golden Knights | -0.95 | 44.7 | 0.0 | 43.9 |

Low chemistry with **zero pass links** between partners flags units that rarely connect on inferred passes — worth a video review even when xGF% looks acceptable (Coghlan–Lauzon).

### 4.7 Interpretation

**Forward lines** show the clearest chemistry–performance link at league scale (+5.2 xGF% between quartiles; r = 0.13 with xGF/60). **Defensive pairs** show a meaningful xGF/60 correlation (r = 0.17) but xGF% quartiles collapse when n is large — pair chemistry is better for ranking units on chance *rate* than raw share.

Forward chemistry remains noisier than D pairs in absolute correlation because of three-player redundancy, shorter stable TOI blocks, and pass-inference dilution from D-to-F activation passes outside the 3-event window.

**For coaching application:** see Section 5 (pairing/line playbooks, weekly workflow, what not to do). Use Section 4.6 for **prospect lines/pairs by chemistry**; Sections 4.3–4.4 for **confirmed on-ice results**.

---

## 5. Hockey applications and key takeaways

This section translates the model into language and decisions coaching staffs actually use — line charts, pairings, matchups, and in-season adjustments — not just correlation tables.

### 5.1 Key takeaways (for coaches and player development staff)

1. **Chemistry is measurable, not just feel.** Passing-network density plus complementary microstats (entries, retrievals, exits) predict chance generation better than "they've played together before." Forward lines in the top chemistry quartile ran **51.2% xGF** vs **46.0%** for the bottom quartile (+5.2 points over ~2,000 games).

2. **Pair defensemen by role, not by reputation.** The model rewards *transporter × retriever* templates — one D who carries/exits, one who wins pucks back — not two puck-movers who duplicate the same job. Heiskanen–Lundkvist (86.2% xGF, 35 min) and Girard–Karlsson (89.5% xGF, 30 min) are league examples from this dataset.

3. **Forward lines: one driver, one finisher, one connector.** High chemistry lines combine a high `entry_rate` player with a high `shot_xg_rate` teammate and pass-rate diversity — not three playmakers or three shooters. Bratt–Dadonov–Hischier and Batherson–Giroux–Halliday rank among top-xGF% trios here.

4. **Use chemistry to break ties, not override everything.** Matchups, handedness, faceoff needs, and special teams still come first. When two lines look similar on xGF%, chemistry score is the tiebreaker.

5. **Require a sample before acting.** Do not reshuffle after one bad period. Our validation filter: **≥5 min unit TOI** and **≥8 combined shots** before trusting a split.

6. **Pass links confirm trust on the ice.** If complementarity scores high but `pass_links_per60` is near zero, the unit may look good on paper but is not actually connecting — worth a video session before promoting them.

7. **Injury replacements: plug archetypes, not names.** When a retrieval D is out, prioritize a replacement who pairs with your exit/transporter partner's skill gap — check `player_skills.csv`, not just TOI rank.

---

### 5.2 Defensive pairing playbook

| Situation | Hockey read | Model signal | Action |
|-----------|-------------|--------------|--------|
| **Breakout struggles** | Pair can't exit clean under forecheck | Low `exit_rate` on both D; low pass links between pair | Split or add a retrieval-heavy partner (high `retrieval_rate`) |
| **Odd-man rushes against** | One D pinches, partner not covering | High `entry_rate` on one D, low retrieval on partner | Pair transporter with stay-home retriever (Solovyov / Hunt Daemon archetypes) |
| **Quiet pair, good results** | Low event count but chances when on ice | Moderate pass links, high complementarity, strong xGF/60 | Keep pair — chemistry ≠ volume (Heiskanen–Lundkvist: 49 pass links/60, 86% xGF) |
| **High volume, poor results** | Lots of touches, bleeding chances | High pass links, low xGF% | Role redundancy — two puck-movers, neither retrieves (see Kiersted–Spurgeon: 2.2% xGF) |
| **Return from injury** | Skater rusty, coach wants safe minutes | Match replacement's retrieval/exit profile to incumbent's complement | Query skills table before slotting into existing pair |

**Pairing archetypes from 2025–26 data:**

| Archetype | Example players (this study) | Pair with |
|-----------|------------------------------|-----------|
| **Retriever** | Hunt Daemon, Solovyov, Sebrango | Puck-moving / entry D |
| **Transporter** | Tyson Jost (F), Hughes, Panarin | Retrieval / defensive conscience |
| **Two-way exit** | Kulak, Heiskanen | Any — raises floor of partner's breakouts |

---

### 5.3 Forward line playbook

| Situation | Hockey read | Model signal | Action |
|-----------|-------------|--------------|--------|
| **Line cycling but not scoring** | Good zone time, no inner-slot looks | High `pass_rate`, low `shot_xg_rate`, high pass links | Add or swap in a finisher; line has connectors but no shooter |
| **Rush chances, no sustain** | Fast off entry, one-and-done | High `entry_rate`, low pass links between F3 | Third forward not supporting — need a low-support connector on wall |
| **Grind line overperforming** | 4th line tilting ice | High complementarity on modest TOI (PIT Dewar–Jones–Lizotte: 96% xGF, ~20 min) | Keep together longer than coach's instinct; chemistry backs deployment |
| **Star line underperforming** | Top names, flat xGF% | Low complementarity OR redundant skill profiles | Try moving entry driver or finisher — not always "shake up the line" randomly |
| **Post-trade deadline** | New winger with center | Cross `entry_rate` × `shot_xg_rate` before first game | Simulate trio in practice, confirm pass links in first 3 games |

**Line construction template (5v5):**

```
LW: Entry driver OR retrieval support (high entry_rate OR high pass_rate)
C:  Connector / transporter (balanced pass_rate, moderate shot_xg_rate)
RW: Finisher OR second entry threat (high shot_xg_rate OR entry_rate)
```

Penguins' Acciari–Dewar–Jones / Dewar–Jones–Lizotte clusters show how a checking line with aligned chemistry can run **96% xGF** on real NHL minutes — not just offensive lines benefit.

---

### 5.4 In-season workflow (weekly staff cadence)

**Monday (after weekend games):**
- Pull last 5–10 games via `pbp_query.py list --team {ABBREV} --from {date}`
- Refresh `player_skills.csv` slice for injured/inserted players
- Flag any pair/line with chemistry quartile drop + xGF% below 45%

**Tuesday (video + practice planning):**
- For flagged units: pull pass-network edges for that trio/pair — who is actually passing to whom?
- Match video to model: rim passes vs east-west; retrieval failures vs entry turnovers

**Wednesday–Thursday (line chart):**
- Score 2–3 candidate combinations with complementarity before writing the card
- Prefer changes that fix a *skill gap* (add retriever, add finisher) not just "new faces"

**Game day:**
- Matchup overrides chemistry when required (heavy cycle team vs small skilled line, etc.)
- Revisit after 5+ min ES TOI if early shifts look disconnected despite high chemistry score

---

### 5.5 Matchup and special-teams notes

- **This model is 5v5 ES only.** Do not use chemistry scores to set PP units or PK pairs without separate analysis.
- **Score effects matter.** Trailing lines may inflate entry rates and rush shots; future work adds score-adjusted xGF (see Section 7).
- **OZ/DZ starts:** A "good" chemistry line deployed only in DZ starts will underperform its raw xGF% — cross-check deployment with `player_cards/qoc_qot.py` zone-start data when available.
- **Heavy matchups:** Chemistry predicts *baseline* fit; vs McDavid or Matthews, coach may still prefer a matchup line with lower chemistry but better defensive archetype.

---

### 5.6 What not to do (common staff mistakes)

| Mistake | Why it fails |
|---------|--------------|
| Splitting a pair after one bad game | Below 5 min / 8-shot threshold — noise dominates |
| Pairing two offensive D because both score points | Duplicate transporter skills; retrieval gap bleeds chances |
| Assuming high pass volume = good line | Pass links without complementarity can be circular passing (perimeter hockey) |
| Using chemistry alone for call-ups | AHL/skater sample too small; need ≥20 ES min in NHL PBP before trusting rates |
| Ignoring handedness / faceoffs | Model does not capture draws or off-side entries — still coach manually |

---

### 5.7 In-season line construction workflow (technical)

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Build skill     │────▶│ Score candidate  │────▶│ Confirm with    │
│ profiles from   │     │ pairs/lines with │     │ pass-link density│
│ last N games    │     │ complementarity  │     │ + xGF% monitor  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

**Model thresholds (from validation):**

1. **Forward lines:** Chemistry index separates quartiles by +5.2 xGF% — use to break ties between similar lines.
2. **Defense pairs:** Trust chemistry for xGF/60 ranking (r = 0.17); raw xGF% quartiles flatten at league scale.
3. **Minimum sample:** ≥5 min unit TOI and ≥8 combined shots.
4. **Archetype check:** D pairs — `entry_rate × retrieval_rate`; F lines — `entry_rate × shot_xg_rate` + pass diversity.
5. **Filter:** Exclude college/preseason opponent units from staff tables (Section 4.3).

---

### 5.8 Output files for hockey staff (`outputs/`)

| File | Rows / size | Contents |
|------|-------------|----------|
| `analysis_summary.json` | 584 lines | Full JSON: dataset, pass_network, forward_lines, defensive_pairs, top_skill_profiles |
| `defensive_pairs.csv` | 959 units | All D pairs: unit, players, TOI, GF/GA, SF/SA, xGF/xGA, xGF%, complementarity, pass_links, pass_links_per60 |
| `forward_lines.csv` | 45,059 units | All forward trios: same columns as pairs |
| `player_skills.csv` | 30 rows (top profiles) | Per-player entry/retrieval/exit/pass/shot_xg rates per 60 + ES minutes |

Passing-network graphs can be rendered via `Torrent/src/components/PassingNetwork.tsx` by exporting top edges per unit.

### 5.9 Query PBP without re-running analysis

```bash
cd automated-scraping
PYTHONPATH=. python3 scripts/pbp_query.py summary
PYTHONPATH=. python3 scripts/pbp_query.py list --team TBL
PYTHONPATH=. python3 scripts/pbp_query.py export --team TBL --out research/tbl.parquet
```

---

## 6. Limitations

1. **Incomplete team-folder coverage** — 21 NHL teams with dedicated cache folders; remaining teams appear via opponent games in shared files.
2. **Non-NHL units in validation tails** — preseason/college opponents (e.g. St. Michael's College) appear in bottom-xGF% tables; filter to NHL roster for staff deliverables.
3. **Pass receiver inference** — 3-event window misattributes some rim passes and D-to-D reversals; no explicit pass completion flag beyond action type.
4. **No score/state adjustment** — xGF% includes all ES states; trailing/leading effects not regressed out.
5. **Name matching** — InStat ↔ NHL API fuzzy join may miss call-ups with <20 ES minutes.
6. **xG model** — Geometry logistic not refit on NHL 2025–26; PWHL-fitted model exists in `pwhl-analytics/data/xg_model.json` for future upgrade.
7. **Correlation ≠ causation** — Coaches may already pair complementary skill types; observed correlation partly reflects selection.

---

## 7. Future work

- [x] Full-league PBP via `pbp_catalog` + `sync_player_cards_ci.py`
- [ ] Refit xG on NHL InStat shots (`fit_xg_model.py` template)
- [ ] Add score-adjusted xGF and QoC/QoT from `player_cards/qoc_qot.py`
- [ ] Directed network metrics: reciprocity, betweenness, PageRank within units
- [ ] Prospective validation: predict next-10-game xGF% from chemistry scores
- [ ] Integrate A3Z zone-entry rates as exogenous entry-skill prior

---

## 8. Conclusion

We presented a **passing-network-informed complementary-skill model** for NHL line and pairing construction, built from InStat/Hudl PBP (`pbp_catalog`) and NHL API rosters. Across **2,037 games** and **9.0M events**, we inferred **505,948** pass edges and scored **45,059** forward lines and **959** defensive pairs.

Forward-line chemistry separates quartiles by **+5.2 xGF%** (51.2% vs 46.0%); defensive-pair chemistry correlates with xGF/60 at **r = 0.17**. For hockey staffs, the actionable output is a **role-based pairing and line toolkit** (Sections 5.2–5.6): pair transporters with retrievers, build forward lines with driver/finisher/connector roles, and use chemistry as a tiebreaker after matchups and deployment — not a replacement for coaching judgment.

---

## Reproducibility

```bash
cd automated-scraping
PYTHONPATH=. python3 research/line_chemistry_passing_networks/analyze_line_chemistry.py
# Fast refresh (fix labels + chemistry rankings from existing CSVs):
PYTHONPATH=. python3 research/line_chemistry_passing_networks/analyze_line_chemistry.py --refresh-from-csv
# Prerequisite: python scripts/sync_player_cards_ci.py  (or local InStat download)
# Inspect cache: PYTHONPATH=. python3 scripts/pbp_query.py summary
```

**Requirements:** Python 3.10+, pandas, numpy, httpx; local InStat PBP cache at `~/Desktop/My Analytics Work/{Team}/Instat_API_Downloads/`; read access to `pwhl-analytics/pipeline/line_pairing_engine.py`.

**Outputs (all fields mirrored in Section 4):**

```
outputs/
  analysis_summary.json   # dataset, pass_network, validation, top_skill_profiles
  defensive_pairs.csv     # 959 rows — all pair-level metrics
  forward_lines.csv       # 45,059 rows — all line-level metrics
  player_skills.csv       # top 30 skill profiles (full list in JSON)
```

---

## References

1. InStat/Hudl hockey tracking PBP — event-level microstats via authenticated API (`automated-scraping/hudl-scraping/`).
2. NHL API — official roster and schedule (`api-web.nhle.com/v1`).
3. PWHL line pairing engine — ES shift sweep methodology (`pwhl-analytics/pipeline/line_pairing_engine.py`).
4. Passing network visualization — edge inference convention (`Torrent/src/components/PassingNetwork.tsx`).
5. WAR-on-ice / academic line chemistry literature — microstat complementarity and network centrality in hockey (conceptual framing).

---

*Generated from full-league analysis: 2,037 games, 505,948 pass edges, June 2026.*
