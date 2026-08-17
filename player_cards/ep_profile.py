"""EliteProspects full player-profile enrichment for undrafted prospects.

Cloudflare blocks plain httpx against player pages, so we:
1. Prefer on-disk cache under ``player_cards/data/ep/<slug>.json``
2. Optionally refresh via Playwright when ``EP_PLAYWRIGHT=1``
3. Fall back to autocomplete-only stubs when neither is available
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from .disk_cache import cache_path, load_json, save_json

logger = logging.getLogger(__name__)

EP_DATA_DIR = Path(__file__).resolve().parent / "data" / "ep"
EP_CACHE_TTL = 7 * 86_400

# Tournaments / invite showcases — kept on the career list but not for PBP.
_TOURNAMENT_LEAGUES = {
    "WSI U15",
    "TELUS CUP",
    "CIRCLE K CLASSIC",
    "HLINKA GRETZKY CUP",
    "BRICK INVITATIONAL",
    "CWENCH",
}

# Leagues where InStat PBP may exist in our Prospects/ caches.
_PBP_LEAGUES = {"WHL", "OHL", "QMJHL", "USHL", "NCAA", "AHL", "NHL", "KHL", "SHL", "LIIGA"}


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _parse_height(raw: str | None) -> tuple[str | None, int | None]:
    """Return (display like 5'10\", inches)."""
    if not raw:
        return None, None
    m = re.search(r"(\d+)\s*'\s*(\d+)", raw)
    if m:
        feet, inches = int(m.group(1)), int(m.group(2))
        return f"{feet}'{inches}\"", feet * 12 + inches
    m = re.search(r"(\d+)\s*cm", raw)
    if m:
        cm = int(m.group(1))
        total = round(cm / 2.54)
        return f"{total // 12}'{total % 12}\"", total
    return raw.strip(), None


def _parse_weight_lbs(raw: str | None) -> int | None:
    if not raw:
        return None
    m = re.search(r"(\d+)\s*lbs?", raw, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*kg", raw, re.I)
    if m:
        return round(int(m.group(1)) * 2.20462)
    if str(raw).isdigit():
        return int(raw)
    return None


def _parse_chl_draft(raw: str) -> dict[str, Any] | None:
    """Parse strings like 'Drafted 2025, 1 #3 by Regina Pats in the WHL Prospects Draft'."""
    if not raw:
        return None
    m = re.search(
        r"Drafted\s+(\d{4}),\s*(\d+)\s*#(\d+)\s*by\s+(.+?)\s+in the\s+(WHL|OHL|QMJHL|CHL)",
        raw,
        re.I,
    )
    if not m:
        return None
    return {
        "year": int(m.group(1)),
        "round": int(m.group(2)),
        "pick": int(m.group(3)),
        "team": m.group(4).strip(),
        "league": m.group(5).upper(),
        "raw": raw.strip(),
    }


def _seed_path(slug: str) -> Path:
    return EP_DATA_DIR / f"{slug}.json"


def _load_seed(slug: str | None) -> dict[str, Any] | None:
    if not slug:
        return None
    path = _seed_path(slug)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed reading EP seed %s: %s", path, exc)
        return None


def _career_clubs(seasons: list[dict[str, Any]]) -> list[str]:
    """Ordered unique clubs from league seasons (tournaments last / de-emphasised)."""
    primary: list[str] = []
    secondary: list[str] = []
    seen: set[str] = set()
    for row in seasons:
        team = str(row.get("team") or "").strip()
        league = str(row.get("league") or "").strip()
        if not team:
            continue
        key = _norm(team)
        if key in seen:
            continue
        seen.add(key)
        if league.upper() in _TOURNAMENT_LEAGUES:
            secondary.append(team)
        else:
            primary.append(team)
    return primary + secondary


def _pbp_club_names(seasons: list[dict[str, Any]], amateur_club: str | None) -> list[str]:
    """Clubs we should try to load InStat PBP for (WHL/CHL/NCAA first)."""
    clubs: list[str] = []
    seen: set[str] = set()

    def add(name: str | None) -> None:
        n = (name or "").strip()
        if not n:
            return
        # Strip suffixes like ' "A"' from EP
        n = re.sub(r'\s+"[A-Z]"\s*$', "", n).strip()
        key = _norm(n)
        if key in seen:
            return
        seen.add(key)
        clubs.append(n)

    if amateur_club:
        add(amateur_club)
    for row in seasons:
        league = str(row.get("league") or "").upper()
        if league in _PBP_LEAGUES or league.startswith("SMAAAHL") or "CSSHL" in league:
            add(str(row.get("team") or ""))
    return clubs


def load_ep_profile(player_name: str, *, slug: str | None = None) -> dict[str, Any] | None:
    """Load a full EP profile from seed/cache (and optional Playwright refresh)."""
    from .nhl_bio import fetch_eliteprospects_player

    ep_hit = fetch_eliteprospects_player(player_name) or {}
    slug = slug or ep_hit.get("slug")
    if not slug and ep_hit.get("fullname"):
        slug = re.sub(r"[^a-z0-9]+", "-", _norm(str(ep_hit["fullname"]))).strip("-")

    disk = cache_path("ep_profile", f"{slug or _norm(player_name)}.json")
    cached = load_json(disk, ttl_seconds=EP_CACHE_TTL)
    if isinstance(cached, dict) and cached.get("height"):
        return cached

    seed = _load_seed(slug) if slug else None
    if seed is None:
        # try matching any seed by player name
        for path in EP_DATA_DIR.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if _norm(payload.get("name") or path.stem.replace("-", " ")) == _norm(player_name):
                seed = payload
                slug = path.stem
                break
            if slug and path.stem == slug:
                seed = payload
                break

    if os.getenv("EP_PLAYWRIGHT", "").strip() == "1" and slug:
        scraped = scrape_ep_player_page(slug)
        if scraped:
            save_json(disk, scraped)
            return scraped

    if seed:
        # Ensure derived fields exist
        out = dict(seed)
        out.setdefault("name", player_name)
        seasons = list(out.get("career_seasons") or [])
        out["career_clubs"] = _career_clubs(seasons)
        out["pbp_clubs"] = _pbp_club_names(seasons, out.get("amateur_club"))
        if out.get("chl_draft") and isinstance(out["chl_draft"], str):
            out["chl_draft"] = _parse_chl_draft(out["chl_draft"])
        save_json(disk, out)
        return out

    return None


def scrape_ep_player_page(slug: str) -> dict[str, Any] | None:
    """Best-effort Playwright scrape of an EP player page (Cloudflare-sensitive)."""
    url = f"https://www.eliteprospects.com/player/{slug}" if "/" not in slug else (
        slug if slug.startswith("http") else f"https://www.eliteprospects.com/player/{slug}"
    )
    # Accept "701503/landon-dupont" or "landon-dupont"
    if re.fullmatch(r"\d+/[a-z0-9-]+", slug):
        url = f"https://www.eliteprospects.com/player/{slug}"
    elif re.fullmatch(r"[a-z0-9-]+", slug):
        # Prefer id/slug when we have seed
        seed = _load_seed(slug) or {}
        if seed.get("ep_id"):
            url = f"https://www.eliteprospects.com/player/{seed['ep_id']}/{slug}"
        else:
            url = f"https://www.eliteprospects.com/player/{slug}"

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        logger.warning("Playwright unavailable for EP scrape: %s", exc)
        return None

    profile_dir = os.getenv("EP_CHROME_PROFILE", "").strip() or str(
        Path.home() / ".ep-chrome-profile"
    )
    cdp = os.getenv("EP_CDP_URL", "").strip()

    try:
        with sync_playwright() as p:
            if cdp:
                browser = p.chromium.connect_over_cdp(cdp)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.new_page()
                owns = False
            else:
                Path(profile_dir).mkdir(parents=True, exist_ok=True)
                context = p.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=os.getenv("EP_HEADLESS", "1").strip() not in {"0", "false"},
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    ),
                    args=["--disable-blink-features=AutomationControlled"],
                )
                page = context.new_page()
                owns = True
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3000)
            if "Just a moment" in page.title():
                page.wait_for_timeout(5000)
            if "Just a moment" in page.title():
                logger.warning("EP Cloudflare challenge for %s — using seed/cache", slug)
                if owns:
                    context.close()
                else:
                    page.close()
                return None
            data = page.evaluate(
                """() => {
                  const text = document.body.innerText;
                  const after = (label) => {
                    const i = text.indexOf(label);
                    if (i < 0) return null;
                    return text.slice(i + label.length, i + label.length + 80).trim().split('\\n')[0].trim();
                  };
                  const seasons = [];
                  document.querySelectorAll('table tr').forEach(tr => {
                    const cells = [...tr.querySelectorAll('td,th')].map(c => c.innerText.replace(/\\s+/g,' ').trim());
                    if (cells.length >= 3 && /^\\d{4}-\\d{2}$/.test(cells[0])) {
                      seasons.push({
                        season: cells[0], team: cells[1], league: cells[2],
                        gp: cells[3], g: cells[4], a: cells[5], tp: cells[6],
                      });
                    }
                  });
                  const drafted = [...text.matchAll(/Drafted[^\\n]{0,120}/g)].map(m => m[0]);
                  const nhl = (text.match(/eligible for the (\\d{4}) NHL/i) || [])[1] || null;
                  return {
                    height: after('Height'), weight: after('Weight'), shoots: after('Shoots'),
                    position: after('Position'), dob: after('Date of Birth'),
                    place: after('Place of Birth'), drafted, nhl_year: nhl, seasons,
                  };
                }"""
            )
            if owns:
                context.close()
            else:
                page.close()
    except Exception as exc:
        logger.warning("EP Playwright scrape failed for %s: %s", slug, exc)
        return None

    height, inches = _parse_height(data.get("height"))
    weight = _parse_weight_lbs(data.get("weight"))
    chl = None
    for line in data.get("drafted") or []:
        chl = _parse_chl_draft(line)
        if chl:
            break
    seasons = []
    for row in data.get("seasons") or []:
        seasons.append(
            {
                "season": row.get("season"),
                "team": row.get("team"),
                "league": row.get("league"),
                "gp": _int_or_none(row.get("gp")),
                "g": _int_or_none(row.get("g")),
                "a": _int_or_none(row.get("a")),
                "tp": _int_or_none(row.get("tp")),
            }
        )
    place = data.get("place") or ""
    city = place.split(",")[0].strip() if place else None
    country = "CAN" if "CAN" in place.upper() or "CANADA" in place.upper() else (
        "USA" if "USA" in place.upper() else None
    )
    nhl_year = data.get("nhl_year")
    out = {
        "slug": slug.split("/")[-1],
        "height": height,
        "height_inches": inches,
        "weight_lbs": weight,
        "shoots": (data.get("shoots") or "").strip()[:1].upper() or None,
        "position": data.get("position"),
        "dob": data.get("dob"),
        "birth_city": city,
        "birth_country": country,
        "nhl_draft_year": int(nhl_year) if nhl_year else None,
        "nhl_draft_info": f"{nhl_year} NHL Draft Eligible" if nhl_year else "NHL Draft Eligible",
        "chl_draft": chl,
        "career_seasons": seasons,
        "career_clubs": _career_clubs(seasons),
        "pbp_clubs": _pbp_club_names(seasons, None),
        "amateur_club": None,
    }
    return out


def _int_or_none(v: Any) -> int | None:
    try:
        if v in (None, "", "-", "–"):
            return None
        return int(str(v).replace(",", ""))
    except Exception:
        return None


def format_chl_draft_line(chl: dict[str, Any] | None) -> str | None:
    if not chl:
        return None
    return f"{chl.get('year')} {chl.get('league')} · Rd {chl.get('round')} #{chl.get('pick')} ({chl.get('team')})"
