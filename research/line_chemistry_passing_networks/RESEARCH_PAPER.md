# Line and Pairing Chemistry via Passing Networks: A Complementary-Skill Model Validated Against On-Ice Expected Goals

**Authors:** Analytics Research (Cascade Projects)  
**Date:** June 2026  
**Data:** NHL 2025–26 season (partial), InStat/Hudl tracking PBP + NHL API rosters  
**Code:** `automated-scraping/research/line_chemistry_passing_networks/analyze_line_chemistry.py`

---

## Abstract

Every NHL coaching staff faces the same in-season problem: which forwards and defensemen actually *fit* together? Traditional line charts describe who plays together, but not *why* a combination works. We propose a **complementary-skill chemistry model** built from InStat/Hudl play-by-play (PBP) passing events and microstat skill profiles, validated against on-ice expected goals (xG).

Using **916 games** and **5.85 million** tracked events from 12 NHL teams (1,095 InStat PBP files), we:

1. Infer **312,207** passer→receiver edges from sequential pass-touch events.
2. Build per-player skill vectors (zone-entry rate, defensive-zone retrieval rate, exit rate, pass volume, shot-xG rate).
3. Score forward trios and defensive pairs with a **cross-skill complementarity index** and within-unit **pass-link density**.
4. Attribute on-ice xGF/xGA to identified units via even-strength shift sweeps.

**Key finding:** For defensive pairs with ≥20 minutes TOI and ≥8 combined shot attempts, complementarity correlates with xGF/60 at **r = 0.17** and with a combined chemistry index at **r = 0.22**. Pairs in the top chemistry quartile average **50.1% xGF** vs **47.2%** for the bottom quartile (+2.9 points). Forward lines show a weaker signal, consistent with three-player skill redundancy and shorter stable TOI blocks.

The framework is directly actionable for line construction: identify a high zone-entry/transporter forward or defenseman, pair with a high retrieval/exit partner, and confirm with within-pair pass-network density before deployment.

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

### 2.2 Coverage (2025–26, as of June 2026)

| Metric | Value |
|--------|-------|
| PBP files | 1,095 |
| Unique games | 916 |
| Total events | 5,854,262 |
| Teams with cached PBP | 12 (ANA, BOS, BUF, CAR, CGY, CHI, CBJ, COL, DAL, PIT, SJS, WPG + opponents in those games) |
| Inferred pass edges | 312,207 |
| Skaters with skill profiles | 1,020 |
| Identified forward-line units | 12,168 |
| Identified defensive pairs | 828 |

> **Note:** Full-league coverage requires completing `instat_pbp_fetch.batch_download_team_pbp` for remaining franchises. Analysis includes opponent events from games involving cached teams, yielding 32 team labels in the combined dataset.

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

**Example profiles (2025–26 partial season):**

| Player | entry_rate | retrieval_rate | Role archetype |
|--------|-----------|----------------|----------------|
| Tyson Jost | 336.7 | 251.5 | Elite transporter |
| Ilya Solovyov | 202.0 | 628.9 | Elite retriever |
| Brett Kulak | 123.3 | 406.5 | Two-way exit/retrieval D |

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

### 4.1 Defensive pairs — complementarity predicts chance share

| Metric | Value | n units |
|--------|-------|---------|
| corr(complementarity, xGF%) | **+0.106** | 680 |
| corr(complementarity, xGF/60) | **+0.167** | 680 |
| corr(chemistry index, xGF/60) | **+0.216** | 680 |
| corr(pass_links_per60, xGF%) | +0.018 | 680 |
| Top-quartile mean xGF% | **50.1%** | — |
| Bottom-quartile mean xGF% | **47.2%** | — |
| **Quartile gap** | **+2.9 pts** | — |

The signal is modest but directionally correct and **coaching-relevant at the margin**: a 3-point xGF% swing over hundreds of minutes is roughly 0.5–1 expected goal per 60 depending on shot volume.

**Top pairs by xGF% (≥20 min TOI, ≥20 combined shots):**

| Pair | Team | TOI | xGF% | Complementarity |
|------|------|-----|------|-----------------|
| Heiskanen–Lundkvist | DAL | 35.4 min | 83.5% | 3,285 |
| Miller–Nikishin | CAR | 51.8 min | 74.3% | 2,443 |
| Burns–Makar | COL | 61.2 min | 72.6% | 3,920 |
| Nikishin–Slavin | CAR | 39.5 min | 70.8% | 2,226 |
| Makar–Manson | COL | 61.2 min | 69.4% | 4,412 |

**Case study — Colorado Avalanche retrieval/transporter template:**

Solovyov (628.9 retrievals/60) paired with puck-movers Makar, Kulak, and Malinski produces complementarity scores >20,000 and xGF% consistently above 56% on ≥30 min samples. This is the quantitative signature of *pairing a high zone-entry/exiting defenseman with a strong retrieval defenseman* — the hypothesis stated at project inception.

### 4.2 Forward lines — weaker but interpretable null

| Metric | Value | n units |
|--------|-------|---------|
| corr(complementarity, xGF%) | −0.021 | 2,449 |
| corr(chemistry index, xGF/60) | +0.060 | 2,449 |
| Top-quartile mean xGF% | 49.3% | — |
| Bottom-quartile mean xGF% | 48.6% | — |

Forward chemistry is noisier because:

1. **Three-body redundancy** — any of three forwards can entry, pass, or finish.
2. **Shorter stable TOI** — coaches rotate wings more frequently than D pairs.
3. **Pass inference dilution** — F-to-F links compete with D-to-F activation passes outside the 3-event window.

Pass-link density alone is near-zero correlated with xGF% for lines (+0.007), suggesting forward *quality* dominates forward *network density* at 5v5.

### 4.3 Passing network scale

| Stat | Value |
|------|-------|
| Inferred edges | 312,207 |
| Unique passers | 1,092 |
| Mean edges/game | ~341 |

At the team level, top pass-link pairs within D units average 20–55 links/60 — enough signal for visualization in our PassingNetwork component.

---

## 5. Coaching applications

### 5.1 In-season line construction workflow

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Build skill     │────▶│ Score candidate  │────▶│ Confirm with    │
│ profiles from   │     │ pairs/lines with │     │ pass-link density│
│ last N games    │     │ complementarity  │     │ + xGF% monitor  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

**Practical rules extracted from results:**

1. **Defense first.** Complementarity signal is strongest for D pairs (+0.17 to +0.22 vs xG). When a retrieval-heavy D returns from injury, prioritize pairing with your highest entry/exit D, not highest point total.
2. **Threshold before trust.** Require ≥20 min combined ES TOI before acting on xGF% splits; chemistry scores are more stable than raw percentages below that.
3. **Archetype checklist.** For each candidate pair, ask: *does A's entry_rate × B's retrieval_rate rank in the top tertile league-wide?* If yes, green-light for a trial deployment.
4. **Forward trios.** Use complementarity to **break ties** between similar-xGF lines, not as a primary driver. Prioritize known finishers and matchups; use pass density to detect disconnected trios (low internal links/60).

### 5.2 What to show a coaching staff

Deliverables already generated in `outputs/`:

| File | Use |
|------|-----|
| `defensive_pairs.csv` | All pairs with TOI, xGF%, complementarity, pass links |
| `forward_lines.csv` | Same for forward trios |
| `player_skills.csv` | Per-player skill vectors for custom pairing queries |
| `analysis_summary.json` | Validation metrics for methodology slide |

Passing-network graphs can be rendered via `Torrent/src/components/PassingNetwork.tsx` by exporting top edges per unit.

---

## 6. Limitations

1. **Partial league coverage** — 12/32 teams fully cached; opponent-only players have thinner skill estimates.
2. **Pass receiver inference** — 3-event window misattributes some rim passes and D-to-D reversals; no explicit pass completion flag beyond action type.
3. **No score/state adjustment** — xGF% includes all ES states; trailing/leading effects not regressed out.
4. **Name matching** — InStat ↔ NHL API fuzzy join may miss call-ups with <20 ES minutes.
5. **xG model** — Geometry logistic not refit on NHL 2025–26; PWHL-fitted model exists in `pwhl-analytics/data/xg_model.json` for future upgrade.
6. **Correlation ≠ causation** — Coaches may already pair complementary skill types; observed correlation partly reflects selection.

---

## 7. Future work

- [ ] Complete NHL-wide PBP download via `instat_pbp_fetch.batch_download_team_pbp`
- [ ] Refit xG on NHL InStat shots (`fit_xg_model.py` template)
- [ ] Add score-adjusted xGF and QoC/QoT from `player_cards/qoc_qot.py`
- [ ] Directed network metrics: reciprocity, betweenness, PageRank within units
- [ ] Prospective validation: predict next-10-game xGF% from chemistry scores
- [ ] Integrate A3Z zone-entry rates as exogenous entry-skill prior

---

## 8. Conclusion

We presented a **passing-network-informed complementary-skill model** for NHL line and pairing construction, built entirely from InStat/Hudl PBP and NHL API rosters. Across 916 tracked games, defensive-pair complementarity — explicitly modeling the transporter/retriever template — correlates with on-ice xGF/60 at **r ≈ 0.17–0.22** and separates high- vs low-chemistry quartiles by **~3 xGF% points**.

Forward lines show weaker network effects, reinforcing that **pair chemistry is the sharper actionable signal** for in-season deployment decisions. The pipeline is reproducible, extensible to full-league coverage, and aligned with existing `player_cards` and PWHL analytics infrastructure.

---

## Reproducibility

```bash
cd automated-scraping/research/line_chemistry_passing_networks
python3 analyze_line_chemistry.py
```

**Requirements:** Python 3.10+, pandas, numpy, httpx; local InStat PBP cache at `~/Desktop/My Analytics Work/{Team}/Instat_API_Downloads/`; read access to `pwhl-analytics/pipeline/line_pairing_engine.py`.

**Outputs:**

```
outputs/
  analysis_summary.json
  defensive_pairs.csv
  forward_lines.csv
  player_skills.csv
```

---

## References

1. InStat/Hudl hockey tracking PBP — event-level microstats via authenticated API (`automated-scraping/hudl-scraping/`).
2. NHL API — official roster and schedule (`api-web.nhle.com/v1`).
3. PWHL line pairing engine — ES shift sweep methodology (`pwhl-analytics/pipeline/line_pairing_engine.py`).
4. Passing network visualization — edge inference convention (`Torrent/src/components/PassingNetwork.tsx`).
5. WAR-on-ice / academic line chemistry literature — microstat complementarity and network centrality in hockey (conceptual framing).

---

*Generated from live analysis run: 916 games, 312,207 pass edges, June 17 2026.*
