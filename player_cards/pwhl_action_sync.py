"""Automated PWHL action-photo discovery via OurSports Central (no per-player config)."""

from __future__ import annotations

import html as html_module
import logging
import re
import time
import unicodedata
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

from .disk_cache import cache_path, load_json, save_json
from .pwhl_action_photos import (
    _merge_index,
    _norm_name,
    load_action_index,
    osc_picture_url,
    parse_osc_release_photos,
    register_action_photo,
    save_action_index,
)
from .leagues import PWHL_TEAM_SEARCH
from .pwhl_action_photos import resolve_pwhl_action_photo
from .pwhl_photos import PWHL_HOCKEYTECH_TEAM_IDS, _fetch_ht_roster

logger = logging.getLogger(__name__)

_TEAM_SEEDS_PATH = Path(__file__).resolve().parent / "data" / "pwhl_team_action_seeds.json"
_PLAYER_SEEDS_PATH = Path(__file__).resolve().parent / "data" / "pwhl_player_action_seeds.json"

OSC_PHOTO_URL = "https://www.oursportscentral.com/services/photo/photo/x/n-{photo_id}"
OSC_RELEASE_URL = "https://www.oursportscentral.com/services/releases/x/n-{release_id}"
OSC_HEADERS = {"User-Agent": "PlayerCards/1.0 (pwhl-action-sync)"}

PWHL_SUBMITTERS = (
    "Boston Fleet",
    "Minnesota Frost",
    "Montreal Victoire",
    "New York Sirens",
    "Ottawa Charge",
    "Seattle Torrent",
    "Toronto Sceptres",
    "Vancouver Goldeneyes",
)

DEFAULT_PHOTO_ID_START = 68_800
DEFAULT_RELEASE_ID_START = 6_250_000
SYNC_META_TTL = 86_400


def _meta_path():
    return cache_path("pwhl", "action_sync_meta.json")


def _load_meta() -> dict[str, Any]:
    hit = load_json(_meta_path(), ttl_seconds=SYNC_META_TTL)
    return hit if isinstance(hit, dict) else {}


def _save_meta(meta: dict[str, Any]) -> None:
    save_json(_meta_path(), meta)


def build_roster_index() -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """Map normalized name keys and ht ids -> (ht_player_id, display_name)."""
    by_key: dict[str, tuple[str, str]] = {}
    by_id: dict[str, str] = {}
    for _tri, team_id in PWHL_HOCKEYTECH_TEAM_IDS.items():
        for row in _fetch_ht_roster(team_id):
            pid = str(row.get("player_id") or "")
            name = str(row.get("name") or "").strip()
            if not pid or not name:
                continue
            by_id[pid] = name
            keys = {_norm_name(name)}
            parts = name.split()
            if len(parts) >= 2:
                keys.add(_norm_name(f"{parts[-1]} {parts[0]}"))
                keys.add(_norm_name(parts[-1]))
                keys.add(_norm_name(" ".join(parts[1:] + [parts[0]])))
            for key in keys:
                if len(key) >= 4:
                    by_key[key] = (pid, name)
    return by_key, by_id


def _clean_text(text: str) -> str:
    return _norm_name(html_module.unescape(str(text or "")))


def match_players_in_text(text: str, roster: dict[str, tuple[str, str]]) -> list[tuple[str, str]]:
    blob = _clean_text(text)
    if not blob:
        return []
    hits: list[tuple[int, str, str]] = []
    for key, (pid, name) in roster.items():
        if len(key) < 5:
            continue
        if key in blob:
            hits.append((len(key), pid, name))
    hits.sort(key=lambda row: row[0], reverse=True)
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for _score, pid, name in hits:
        if pid in seen:
            continue
        seen.add(pid)
        out.append((pid, name))
    return out


def _is_pwhl_photo_page(html: str) -> bool:
    if "G League" in html or "Cleveland Charge" in html:
        return False
    if re.search(r'alt="PWHL[\s"]', html):
        return True
    if "Professional Women" in html:
        return True
    for team in PWHL_SUBMITTERS:
        if f"Submitted by {team}" in html:
            return True
    return False


def _is_pwhl_release_page(html: str) -> bool:
    if "G League" in html:
        return False
    return "PWHL" in html or "Professional Women" in html


def _photo_title_score(title: str, player_count: int, filename: str = "") -> int:
    score = 0
    tl = title.lower()
    if player_count == 1:
        score += 40
    elif player_count <= 3:
        score += 15
    for verb in ("scores", "shoots", "skates", "looks for", "in action", "goal", "celebrate"):
        if verb in tl:
            score += 8
    blob = filename or title
    m = re.search(r"lg(\d{8})-", blob)
    if m:
        score += int(m.group(1)) // 10_000
    return score


def _strip_accents(text: str) -> str:
    s = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in s if not unicodedata.combining(c))


def _team_aliases(tri: str, full: str) -> list[str]:
    aliases = [full.lower(), _strip_accents(full).lower()]
    if tri == "MVL":
        aliases.extend(["montréal victoire", "montreal victoire", "victoire"])
    if tri == "TSR":
        aliases.extend(["toronto sceptres", "sceptres"])
    if tri == "BPF":
        aliases.extend(["boston fleet", "fleet"])
    return list(dict.fromkeys(a for a in aliases if a))


def _match_team_in_text(text: str) -> str | None:
    raw_l = _strip_accents(html_module.unescape(str(text or ""))).lower()
    best: tuple[int, str] | None = None
    for tri, full in PWHL_TEAM_SEARCH.items():
        for alias in _team_aliases(tri, full):
            idx = raw_l.find(alias)
            if idx >= 0 and (best is None or idx < best[0]):
                best = (idx, tri)
                break
    return best[1] if best else None


def _register_team_photo(
    tri: str,
    *,
    filename: str,
    alt: str,
    source: str,
    title: str,
    force: bool = False,
) -> bool:
    index = load_action_index(refresh=True)
    by_team = dict(index.get("by_team") or {})
    existing = by_team.get(tri) or {}
    new_score = _photo_title_score(title or alt, 99, filename)
    old_score = _photo_title_score(str(existing.get("alt") or ""), 99, str(existing.get("filename") or ""))
    if existing and not force and new_score < old_score:
        return False
    by_team[tri] = {
        "url": osc_picture_url(filename),
        "filename": filename,
        "alt": alt,
        "source": source,
        "team": tri,
    }
    try:
        from io import BytesIO

        from PIL import Image

        from .photo_layout import fetch_photo

        data, _ = fetch_photo(by_team[tri]["url"])
        with Image.open(BytesIO(data)) as im:
            by_team[tri]["width"], by_team[tri]["height"] = im.size
    except Exception:
        pass
    save_action_index(
        {
            "by_ht_id": dict(index.get("by_ht_id") or {}),
            "by_name": dict(index.get("by_name") or {}),
            "by_team": by_team,
        }
    )
    return True


def _register_match(
    pid: str,
    name: str,
    *,
    filename: str,
    alt: str,
    source: str,
    title: str,
    player_count: int,
) -> bool:
    index = load_action_index(refresh=True)
    existing = (index.get("by_ht_id") or {}).get(str(pid)) or {}
    new_score = _photo_title_score(title or alt, player_count, filename)
    old_alt = str(existing.get("alt") or "")
    old_file = str(existing.get("filename") or "")
    old_score = _photo_title_score(old_alt, 1 if old_alt else 99, old_file)
    if existing and new_score < old_score:
        return False
    register_action_photo(
        pid,
        filename=filename,
        player_name=name,
        alt=alt or title,
        source=source,
    )
    return True


def _scan_photo_page(photo_id: int, roster: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    try:
        resp = httpx.get(
            OSC_PHOTO_URL.format(photo_id=photo_id),
            timeout=12.0,
            follow_redirects=True,
            headers=OSC_HEADERS,
        )
    except Exception:
        return []
    if resp.status_code != 200 or len(resp.text) < 2_500:
        return []
    if not _is_pwhl_photo_page(resp.text):
        return []
    files = re.findall(r"graphics/pictures/(lg[^\"']+\.jpg)", resp.text, flags=re.I)
    if not files:
        return []
    title_m = re.search(r"<h1[^>]*>([^<]+)</h1>", resp.text, flags=re.I)
    title = html_module.unescape(title_m.group(1).strip()) if title_m else ""
    players = match_players_in_text(title, roster)
    out: list[dict[str, Any]] = []
    if players:
        for pid, name in players:
            out.append(
                {
                    "kind": "player",
                    "ht_player_id": pid,
                    "name": name,
                    "filename": files[0],
                    "alt": title,
                    "source": "osc_photo",
                    "title": title,
                    "player_count": len(players),
                    "photo_id": photo_id,
                }
            )
        return out
    tri = _match_team_in_text(title)
    if tri:
        out.append(
            {
                "kind": "team",
                "team": tri,
                "filename": files[0],
                "alt": title,
                "source": "osc_photo",
                "title": title,
                "photo_id": photo_id,
            }
        )
    return out


def _scan_release_page(release_id: int, roster: dict[str, tuple[str, str]]) -> list[dict[str, Any]]:
    try:
        resp = httpx.get(
            OSC_RELEASE_URL.format(release_id=release_id),
            timeout=12.0,
            follow_redirects=True,
            headers=OSC_HEADERS,
        )
    except Exception:
        return []
    if resp.status_code != 200 or len(resp.text) < 3_500:
        return []
    if not _is_pwhl_release_page(resp.text):
        return []
    photos = parse_osc_release_photos(resp.text)
    if not photos:
        return []
    title_m = re.search(r"<h1[^>]*>([^<]+)</h1>", resp.text, flags=re.I)
    title = html_module.unescape(title_m.group(1).strip()) if title_m else ""
    out: list[dict[str, Any]] = []
    for photo in photos:
        blob = f"{title} {photo.get('alt') or ''}"
        players = match_players_in_text(blob, roster)
        if players:
            for pid, name in players:
                out.append(
                    {
                        "kind": "player",
                        "ht_player_id": pid,
                        "name": name,
                        "filename": photo["filename"],
                        "alt": photo.get("alt") or title,
                        "source": "osc_release",
                        "title": blob,
                        "player_count": len(players),
                        "release_id": release_id,
                    }
                )
            continue
        tri = _match_team_in_text(blob)
        if tri:
            out.append(
                {
                    "kind": "team",
                    "team": tri,
                    "filename": photo["filename"],
                    "alt": photo.get("alt") or title,
                    "source": "osc_release",
                    "title": blob,
                    "release_id": release_id,
                }
            )
    return out


def _apply_rows(rows: list[dict[str, Any]]) -> int:
    added = 0
    for row in rows:
        if row.get("kind") == "team":
            if _register_team_photo(
                str(row["team"]),
                filename=str(row["filename"]),
                alt=str(row.get("alt") or ""),
                source=str(row.get("source") or "osc"),
                title=str(row.get("title") or row.get("alt") or ""),
            ):
                added += 1
            continue
        if _register_match(
            str(row["ht_player_id"]),
            str(row["name"]),
            filename=str(row["filename"]),
            alt=str(row.get("alt") or ""),
            source=str(row.get("source") or "osc"),
            title=str(row.get("title") or row.get("alt") or ""),
            player_count=int(row.get("player_count") or 1),
        ):
            added += 1
    return added


def _scan_ids(
    scan_fn,
    id_range: range,
    roster: dict[str, tuple[str, str]],
    *,
    workers: int,
    label: str,
) -> tuple[int, int]:
    """Scan OSC ids, registering matches as they arrive."""
    matched_pages = 0
    added = 0
    pending = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(scan_fn, item_id, roster): item_id for item_id in id_range}
        for fut in as_completed(futs):
            rows = fut.result()
            pending += 1
            if rows:
                matched_pages += 1
                added += _apply_rows(rows)
            if pending % 250 == 0:
                logger.info("%s: scanned %s/%s, +%s players indexed", label, pending, len(futs), added)
    return matched_pages, added


def bootstrap_player_action_seeds() -> dict[str, Any]:
    """Register curated in-game press photos for players missing OSC coverage."""
    seeds = load_json(_PLAYER_SEEDS_PATH) if _PLAYER_SEEDS_PATH.is_file() else {}
    if not isinstance(seeds, dict):
        seeds = {}
    added: list[str] = []
    for pid, row in seeds.items():
        if not isinstance(row, dict) or not row.get("url"):
            continue
        register_action_photo(
            str(pid),
            url=str(row["url"]),
            player_name=str(row.get("player_name") or ""),
            alt=str(row.get("alt") or ""),
            source=str(row.get("source") or "seed"),
            width=row.get("width"),
            height=row.get("height"),
        )
        added.append(str(pid))
    return {"seeded_players": added}


def bootstrap_team_fallbacks() -> dict[str, Any]:
    """Ensure every PWHL team has an in-game action still for roster-wide coverage."""
    index = load_action_index(refresh=True)
    by_team = dict(index.get("by_team") or {})
    by_id = dict(index.get("by_ht_id") or {})
    seeds = load_json(_TEAM_SEEDS_PATH) if _TEAM_SEEDS_PATH.is_file() else {}
    if not isinstance(seeds, dict):
        seeds = {}

    added: list[str] = []
    still_missing: list[str] = []

    for tri, ht_team_id in PWHL_HOCKEYTECH_TEAM_IDS.items():
        seed = seeds.get(tri)
        if isinstance(seed, dict) and seed.get("filename"):
            if _register_team_photo(
                tri,
                filename=str(seed["filename"]),
                alt=str(seed.get("alt") or tri),
                source=str(seed.get("source") or "osc_seed"),
                title=str(seed.get("alt") or tri),
                force=True,
            ):
                if tri not in by_team:
                    added.append(tri)
            continue

        if tri in by_team:
            continue

        best_row: dict[str, Any] | None = None
        best_score = -1
        for row in _fetch_ht_roster(ht_team_id):
            pid = str(row.get("player_id") or "")
            player_row = by_id.get(pid)
            if not isinstance(player_row, dict):
                continue
            fn = str(player_row.get("filename") or "")
            alt = str(player_row.get("alt") or "")
            score = _photo_title_score(alt, 1, fn)
            if score > best_score:
                best_score = score
                best_row = player_row

        if best_row and _register_team_photo(
            tri,
            filename=str(best_row.get("filename") or ""),
            alt=str(best_row.get("alt") or tri),
            source=f"{best_row.get('source') or 'osc'}_derived",
            title=str(best_row.get("alt") or tri),
        ):
            added.append(tri)
            by_team[tri] = best_row
        else:
            still_missing.append(tri)

    teams = sorted((load_action_index(refresh=True).get("by_team") or {}).keys())
    return {"added_teams": added, "still_missing": still_missing, "teams_with_fallback": teams}


def effective_action_coverage(*, discover: bool = False, allow_team_fallback: bool = False) -> dict[str, Any]:
    """Roster coverage for player-matched action stills (optional team fallback for API)."""
    _, by_id = build_roster_index()
    bootstrap_player_action_seeds()
    bootstrap_team_fallbacks()

    pid_team: dict[str, str] = {}
    for tri, team_id in PWHL_HOCKEYTECH_TEAM_IDS.items():
        for row in _fetch_ht_roster(team_id):
            pid = str(row.get("player_id") or "")
            if pid:
                pid_team[pid] = tri

    with_hero = 0
    missing: list[dict[str, str]] = []
    for pid, name in sorted(by_id.items(), key=lambda kv: kv[1]):
        tri = pid_team.get(pid, "")
        from .pwhl_photos import _card_photo_from_ht_player

        photo = _card_photo_from_ht_player(
            pid,
            {"name": name, "team": tri},
            player_name=name,
            team_abbrev=tri,
        )
        if allow_team_fallback and (not photo or photo.get("card_photo_kind") != "hero"):
            photo = resolve_pwhl_action_photo(
                pid,
                name,
                team_abbrev=tri,
                discover=discover,
                allow_team_fallback=True,
            )
            if photo:
                photo = {**photo, "card_photo_kind": "hero"}
        if photo and photo.get("card_photo_kind") == "hero":
            with_hero += 1
        else:
            missing.append({"ht_player_id": pid, "name": name, "team": tri})

    index = load_action_index()
    direct_ids = set((index.get("by_ht_id") or {}).keys()) & set(by_id.keys())
    return {
        "roster_size": len(by_id),
        "with_action_photo": with_hero,
        "indexed_players": len(direct_ids),
        "coverage_pct": round(100.0 * with_hero / max(len(by_id), 1), 1),
        "teams_with_fallback": sorted((index.get("by_team") or {}).keys()),
        "players_missing": missing,
    }


def sync_pwhl_action_photos(
    *,
    incremental: bool = True,
    photo_span: int = 1_800,
    release_span: int = 6_000,
    workers: int = 20,
    full: bool = False,
) -> dict[str, Any]:
    """Crawl OSC photo + release pages and map action stills to PWHL roster players."""
    t0 = time.perf_counter()
    meta = _load_meta()
    roster, by_id = build_roster_index()

    photo_hi = int(meta.get("last_photo_id") or 71_200)
    release_hi = int(meta.get("last_release_id") or 6_320_000)

    if full:
        photo_lo = DEFAULT_PHOTO_ID_START
        photo_hi_scan = max(photo_hi + 300, 71_500)
        release_lo = 6_308_000
        release_hi_scan = max(release_hi + 500, 6_325_000)
        photo_step = 2
        release_step = 8
    elif incremental:
        photo_lo = max(DEFAULT_PHOTO_ID_START, photo_hi - photo_span)
        photo_hi_scan = photo_hi + 150
        release_lo = max(DEFAULT_RELEASE_ID_START, release_hi - release_span)
        release_hi_scan = release_hi + 200
        photo_step = 3
        release_step = 10
    else:
        photo_lo = DEFAULT_PHOTO_ID_START
        photo_hi_scan = photo_hi + 300
        release_lo = DEFAULT_RELEASE_ID_START
        release_hi_scan = release_hi + 500
        photo_step = 2
        release_step = 8

    photo_matched, photo_added = _scan_ids(
        _scan_photo_page,
        range(photo_lo, photo_hi_scan + 1, photo_step),
        roster,
        workers=workers,
        label="osc_photo",
    )
    release_matched, release_added = _scan_ids(
        _scan_release_page,
        range(release_lo, release_hi_scan + 1, release_step),
        roster,
        workers=workers,
        label="osc_release",
    )

    added = photo_added + release_added
    bootstrap_team_fallbacks()
    index = load_action_index(refresh=True)
    covered = sorted(set((index.get("by_ht_id") or {}).keys()) & set(by_id.keys()))
    effective = effective_action_coverage()

    meta.update(
        {
            "last_photo_id": photo_hi_scan,
            "last_release_id": release_hi_scan,
            "last_sync_epoch": int(time.time()),
            "last_added": added,
        }
    )
    _save_meta(meta)

    result = {
        "roster_size": len(by_id),
        "indexed_players": len(covered),
        "with_action_photo": effective["with_action_photo"],
        "teams_with_fallback": effective["teams_with_fallback"],
        "coverage_pct": effective["coverage_pct"],
        "direct_index_pct": round(100.0 * len(covered) / max(len(by_id), 1), 1),
        "added_this_run": added,
        "photo_pages_matched": photo_matched,
        "release_pages_matched": release_matched,
        "photo_id_range": [photo_lo, photo_hi_scan],
        "release_id_range": [release_lo, release_hi_scan],
        "seconds": round(time.perf_counter() - t0, 1),
        "missing_players": [row["name"] for row in effective["players_missing"]],
    }
    logger.info(
        "PWHL action photos: %s/%s players (%.1f%% effective), +%s this run",
        effective["with_action_photo"],
        len(by_id),
        result["coverage_pct"],
        added,
    )
    return result


def discover_action_photo_for_player(
    ht_player_id: str | int,
    player_name: str,
    *,
    lookback_photos: int = 3_000,
    lookback_releases: int = 8_000,
    workers: int = 16,
) -> dict[str, Any] | None:
    """On-demand OSC scan for one player (used when index has no hit)."""
    roster, _ = build_roster_index()
    meta = _load_meta()
    pid = str(ht_player_id)
    name = str(player_name or roster.get(_norm_name(player_name), ("", ""))[1] or "").strip()
    if not name:
        return None

    photo_hi = int(meta.get("last_photo_id") or 71_000)
    photo_lo = max(DEFAULT_PHOTO_ID_START, photo_hi - lookback_photos)
    release_hi = int(meta.get("last_release_id") or 6_320_000)
    release_lo = max(DEFAULT_RELEASE_ID_START, release_hi - lookback_releases)

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_scan_photo_page, photo_id, roster) for photo_id in range(photo_hi, photo_lo, -3)]
        futs += [pool.submit(_scan_release_page, rid, roster) for rid in range(release_hi, release_lo, -8)]
        for fut in as_completed(futs):
            for row in fut.result():
                if str(row.get("ht_player_id")) == pid:
                    rows.append(row)

    if not rows:
        return None

    rows.sort(
        key=lambda r: _photo_title_score(
            str(r.get("title") or ""),
            int(r.get("player_count") or 1),
            str(r.get("filename") or ""),
        ),
        reverse=True,
    )
    best = rows[0]
    _register_match(
        pid,
        name,
        filename=str(best["filename"]),
        alt=str(best.get("alt") or ""),
        source=str(best.get("source") or "osc"),
        title=str(best.get("title") or ""),
        player_count=int(best.get("player_count") or 1),
    )
    return load_action_index(refresh=True).get("by_ht_id", {}).get(pid)


def action_photo_coverage() -> dict[str, Any]:
    return _action_photo_coverage_report()


def _action_photo_coverage_report() -> dict[str, Any]:
    """Backward-compatible coverage dict with named player lists."""
    effective = effective_action_coverage()
    _, by_id = build_roster_index()
    missing_ids = {row["ht_player_id"] for row in effective["players_missing"]}
    meta = _load_meta()
    return {
        **effective,
        "last_sync_epoch": meta.get("last_sync_epoch"),
        "last_photo_id": meta.get("last_photo_id"),
        "last_release_id": meta.get("last_release_id"),
        "players_with_photos": sorted(by_id[pid] for pid in by_id if pid not in missing_ids),
        "players_missing": sorted(by_id[pid] for pid in missing_ids),
    }


def ensure_pwhl_action_index(*, min_coverage_pct: float = 0.0, force: bool = False) -> dict[str, Any]:
    """Sync OSC action photos if stale or coverage is below threshold."""
    meta = _load_meta()
    bootstrap_team_fallbacks()
    cov = effective_action_coverage()
    stale = not meta.get("last_sync_epoch") or (time.time() - float(meta["last_sync_epoch"])) > SYNC_META_TTL
    if force or stale or cov["coverage_pct"] < min_coverage_pct:
        return sync_pwhl_action_photos(incremental=not force, full=force)
    return {**_action_photo_coverage_report(), "skipped": True, "reason": "index_fresh"}
