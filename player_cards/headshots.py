import json
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .nhl_bio import _norm, search_player

logger = logging.getLogger(__name__)

# Registry of known NCAA hockey domains powered by Sidearm Sports or similar platforms
NCAA_DOMAINS = {
    "PENN STATE": "gopsusports.com",
    "WISCONSIN": "uwbadgers.com",
    "MINNESOTA": "gophersports.com",
    "MICHIGAN": "mgoblue.com",
    "NOTRE DAME": "und.com",
    "BOSTON COLLEGE": "bceagles.com",
    "BOSTON UNIVERSITY": "goterriers.com",
    "DENVER": "denverpioneers.com",
    "MICHIGAN STATE": "msuspartans.com",
    "NORTH DAKOTA": "fightinghawks.com",
    "CORNELL": "cornellbigred.com",
    "QUINNIPIAC": "gobobcats.com",
    "ST. CLOUD STATE": "scsuhuskies.com",
    "WESTERN MICHIGAN": "wmubroncos.com",
    "MAINE": "goblackbears.com",
    "UMASS": "umassathletics.com",
    "PROVIDENCE": "friars.com",
    "OHIO STATE": "ohiostatebuckeyes.com",
    "NORTHEASTERN": "nuhuskies.com",
    "HARVARD": "gocrimson.com",
    "MIAMI": "miamiredhawks.com",
    "MINNESOTA DULUTH": "umdbulldogs.com",
    "COLGATE": "colgateathletics.com",
    "CLARKSON": "clarksonathletics.com",
    "RPI": "rpiathletics.com",
    "UNION": "unionathletics.com",
    "VERMONT": "uvmathletics.com",
    "MERRIMACK": "merrimackathletics.com",
}

# User agent header to avoid getting blocked by crawlers blocks
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def fetch_sidearm_roster_photos(domain: str) -> dict[str, str]:
    """Scrape collegiate roster page to map player names to their headshot URLs."""
    urls = [
        f"https://{domain}/sports/womens-ice-hockey/roster",
        f"https://{domain}/sports/womens-hockey/roster",
        f"https://{domain}/sports/mens-ice-hockey/roster",
        f"https://{domain}/sports/hockey/roster",
        f"https://{domain}/sports/mens-hockey/roster",
    ]
    photo_map: dict[str, str] = {}
    
    for url in urls:
        try:
            logger.info("Scraping Sidearm roster at %s...", url)
            resp = httpx.get(url, headers=HEADERS, timeout=10.0, follow_redirects=True)
            if resp.status_code != 200:
                continue
                
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # 1. Try Nuxt preloaded data block if present (modern Sidearm/WMT SPAs)
            nuxt_script = soup.find("script", id="__NUXT_DATA__")
            if nuxt_script and nuxt_script.string:
                try:
                    data = json.loads(nuxt_script.string)
                    def deref(x):
                        if isinstance(x, int) and 0 <= x < len(data):
                            return data[x]
                        return x
                    
                    def walk(obj):
                        if isinstance(obj, dict):
                            first = deref(obj.get("first_name")) or deref(obj.get("firstName"))
                            last = deref(obj.get("last_name")) or deref(obj.get("lastName"))
                            full = deref(obj.get("full_name")) or deref(obj.get("fullName"))
                            if (first and last) or full:
                                name_key = str(full or f"{first} {last}").strip().lower()
                                photo_obj = (
                                    deref(obj.get("master_photo")) or 
                                    deref(obj.get("masterPhoto")) or 
                                    deref(obj.get("photo")) or 
                                    deref(obj.get("image")) or 
                                    deref(obj.get("headshot"))
                                )
                                if isinstance(photo_obj, dict):
                                    srcset = deref(photo_obj.get("srcset")) or deref(photo_obj.get("url"))
                                    if isinstance(srcset, str):
                                        parts = srcset.split(",")
                                        url_part = parts[0].strip().split()[0]
                                        if url_part.startswith("/"):
                                            url_part = f"https://{domain}{url_part}"
                                        elif url_part.startswith("//"):
                                            url_part = f"https:{url_part}"
                                        photo_map[name_key] = url_part
                            for k, v in obj.items():
                                walk(v)
                        elif isinstance(obj, list):
                            for x in obj:
                                walk(x)

                    walk(data)
                except Exception as ex:
                    logger.debug("Failed parsing Nuxt data for %s: %s", domain, ex)

            # 2. Classic Sidearm HTML layout scraper (Fallback)
            if not photo_map:
                players = soup.find_all(class_=re.compile(r"roster-player|roster-grid-item|roster-card|player-card"))
                for p in players:
                    name_tag = p.find(class_=re.compile(r"name|player-name")) or p.find("a", href=re.compile(r"/roster/"))
                    img_tag = p.find("img")
                    if name_tag and img_tag:
                        name = name_tag.get_text(strip=True)
                        src = img_tag.get("data-src") or img_tag.get("src")
                        if name and src:
                            name_clean = re.sub(r"\s+", " ", name).strip().lower()
                            if src.startswith("/"):
                                src = f"https://{domain}{src}"
                            elif src.startswith("//"):
                                src = f"https:{src}"
                            photo_map[name_clean] = src
                            
            if photo_map:
                logger.info("Successfully loaded %s roster player images from %s", len(photo_map), domain)
                return photo_map
        except Exception as e:
            logger.warning("Sidearm Sports scrape failed for %s: %s", domain, e)
            
    return photo_map


EP_PHOTO_BASE = "https://files.eliteprospects.com/layout/players/"
EP_AUTOCOMPLETE = "https://autocomplete.eliteprospects.com/all"
EP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.eliteprospects.com/",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.eliteprospects.com",
}


def search_eliteprospects_player_photo(player_name: str) -> str | None:
    """Resolve EP photo URL via the public autocomplete API (no auth required)."""
    try:
        resp = httpx.get(
            EP_AUTOCOMPLETE,
            params={"q": player_name, "type": "player"},
            headers=EP_HEADERS,
            timeout=8.0,
        )
        if resp.status_code != 200:
            logger.debug("EP autocomplete returned %s for %s", resp.status_code, player_name)
            return None
        results = resp.json()
        if not isinstance(results, list):
            return None
        norm_target = _norm(player_name)
        for hit in results[:5]:
            if _norm(hit.get("fullname", "")) == norm_target:
                photo = hit.get("photo", "").strip()
                if photo:
                    url = EP_PHOTO_BASE + photo
                    r2 = httpx.get(url, timeout=5.0, follow_redirects=True)
                    if r2.status_code == 200:
                        logger.info("Found EP autocomplete headshot for %s: %s", player_name, url)
                        return url
        # Fuzzy fallback — first result with a photo
        for hit in results[:3]:
            photo = hit.get("photo", "").strip()
            if photo:
                url = EP_PHOTO_BASE + photo
                r2 = httpx.get(url, timeout=5.0, follow_redirects=True)
                if r2.status_code == 200:
                    logger.info("Found EP autocomplete headshot (fuzzy) for %s: %s", player_name, url)
                    return url
    except Exception as e:
        logger.warning("EP autocomplete lookup failed for %s: %s", player_name, e)
    return None

def search_hockeydb_player_photo(player_name: str) -> str | None:
    """Scrape hockeydb.com database to resolve a player's photo URL."""
    search_url = "https://www.hockeydb.com/ihdb/stats/find_player.php"
    logger.info("Searching HockeyDB for %s...", player_name)
    try:
        resp = httpx.get(search_url, params={"full_name": player_name}, headers=HEADERS, timeout=10.0, follow_redirects=True)
        if resp.status_code != 200:
            return None
            
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # If it redirected directly to the player page
        if "/pdisplay.php" in str(resp.url):
            return _extract_hockeydb_photo(soup)
            
        # Otherwise, parse search result table links
        links = soup.find_all("a", href=re.compile(r"pdisplay\.php\?pid=\d+"))
        for link in links:
            link_name = link.get_text(strip=True)
            if link_name and _norm(player_name) == _norm(link_name):
                player_url = link["href"]
                if not player_url.startswith("http"):
                    player_url = f"https://www.hockeydb.com{player_url}"
                logger.info("Fetching matched HockeyDB player profile: %s", player_url)
                player_resp = httpx.get(player_url, headers=HEADERS, timeout=10.0)
                if player_resp.status_code == 200:
                    player_soup = BeautifulSoup(player_resp.text, "html.parser")
                    return _extract_hockeydb_photo(player_soup)
    except Exception as e:
        logger.warning("HockeyDB lookup failed for %s: %s", player_name, e)
    return None


def _extract_hockeydb_photo(soup: BeautifulSoup) -> str | None:
    img = soup.find("img", src=re.compile(r"/ihdb/photos/"))
    if img:
        src = img["src"]
        if src.startswith("/"):
            src = f"https://www.hockeydb.com{src}"
        return src
    return None


# Hardcoded overrides for high-res action shots or players who fail all endpoints
PROSPECT_HEADSHOT_OVERRIDES = {
    "gavin mckenna": "https://upload.wikimedia.org/wikipedia/en/4/46/Gavin_McKenna_of_the_Penn_State_Nittany_Lions_playing_against_the_Wisconsin_Badgers_in_a_January_23%2C_2026_men%27s_ice_hockey_game_at_the_Kohl_Center_in_Madison_%28IMG_1%29.jpg",
    "ivar stenberg": "https://upload.wikimedia.org/wikipedia/commons/e/ec/2025-10-07_Eisb%C3%A4ren_Berlin_gegen_Fr%C3%B6lunda_HC_%28Champions_Hockey_League_2025-26%29_by_Sandro_Halank%E2%80%93043.jpg",
    "daxon rudolph": "https://upload.wikimedia.org/wikipedia/commons/e/ed/Daxon_Rudolph_2026.03.08.jpg",
    "keaton verhoeff": "https://upload.wikimedia.org/wikipedia/commons/2/2b/Verhoeff2-21-26_%28cropped%29.jpg",
    "liam ruck": "https://upload.wikimedia.org/wikipedia/commons/f/f0/Liam_Ruck_2026.03.07.jpg",
}

def resolve_prospect_headshot(player_name: str, amateur_club: str | None = None) -> str | None:
    """Resolve a unified headshot URL for a prospect checking all endpoints."""
    name_clean = _norm(player_name)
    if name_clean in PROSPECT_HEADSHOT_OVERRIDES:
        logger.info("Using hardcoded override for %s", player_name)
        return PROSPECT_HEADSHOT_OVERRIDES[name_clean]

    # 1. NHL Search API
    try:
        hit = search_player(player_name)
        if hit and hit.get("playerId"):
            hit_name = hit.get("name", "")
            if hit_name and _norm(hit_name) == _norm(player_name):
                pid = hit["playerId"]
                team = hit.get("teamAbbrev") or hit.get("lastTeamAbbrev") or "NHL"
                url = f"https://assets.nhle.com/mugs/nhl/20252026/{team}/{pid}.png"
                
                # Verify that the URL doesn't redirect to a default placeholder
                r = httpx.get(url, headers=HEADERS, timeout=5.0, follow_redirects=True)
                if r.status_code == 200:
                    if "default-" in str(r.url) or "silhouette" in str(r.url):
                        logger.info("NHL API headshot for %s is a default placeholder. Skipping.", player_name)
                    else:
                        logger.info("Found NHL API headshot URL for %s: %s", player_name, url)
                        return url
    except Exception as e:
        logger.debug("NHL headshot check failed: %s", e)

    # 2. NCAA Sidearm sports
    if amateur_club:
        club_upper = amateur_club.upper().strip()
        matched_domain = None
        for key, domain in NCAA_DOMAINS.items():
            if key in club_upper or club_upper in key:
                matched_domain = domain
                break
                
        if matched_domain:
            roster_map = fetch_sidearm_roster_photos(matched_domain)
            url = roster_map.get(player_name.lower().strip())
            if url:
                logger.info("Found NCAA Sidearm headshot URL for %s: %s", player_name, url)
                return url

    # 3. HockeyDB (unblocked, contains junior/collegiate/European pictures)
    hdb_url = search_hockeydb_player_photo(player_name)
    if hdb_url:
        logger.info("Found HockeyDB headshot URL for %s: %s", player_name, hdb_url)
        return hdb_url

    # 4. Elite Prospects (covers NCAA/OHL/WHL/SHL/Liiga/etc. as fallback)
    ep_url = search_eliteprospects_player_photo(player_name)
    if ep_url:
        logger.info("Found Elite Prospects headshot URL for %s: %s", player_name, ep_url)
        return ep_url

    return None
