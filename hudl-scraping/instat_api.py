"""
InStat Hybrid API — Direct Backend Data Extraction
===================================================
Uses Playwright ONLY for authentication, then fires raw API calls
to the InStat backend to extract all match/player/goalie data
without ever touching the UI.

Usage:
    python3 instat_api.py
"""

import asyncio
import csv
import json
import os
import logging
import sqlite3
import hashlib
import time
import argparse
import random
from pathlib import Path
from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("api.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ─── Configuration ───────────────────────────────────────────────
def _credential(name: str, fallback: str = "") -> str:
    return os.getenv(name, fallback).strip()


try:
    from hudl_credentials import HUDL_PASSWORD as _HUDL_PASSWORD
    from hudl_credentials import HUDL_USERNAME as _HUDL_USERNAME
except ImportError:
    _HUDL_USERNAME = ""
    _HUDL_PASSWORD = ""

USERNAME = _credential("HUDL_USERNAME", _HUDL_USERNAME)
PASSWORD = _credential("HUDL_PASSWORD", _HUDL_PASSWORD)

# Shared Hudl/InStat accounts: a new login invalidates other sessions.
# Default = never auto-login. Opt in with ALLOW_INSTAT_LOGIN=1 or
# INSTAT_DEDICATED_ACCOUNT=1 (automation bot account — preferred durable path).
if os.getenv("DISABLE_AUTO_LOGIN") is None:
    os.environ["DISABLE_AUTO_LOGIN"] = "1"


def _login_allowed() -> bool:
    """Password login is opt-in only (shared Hudl accounts get kicked).

    Set ALLOW_INSTAT_LOGIN=1 (one-shot) or INSTAT_DEDICATED_ACCOUNT=1 (bot account).
    """
    if os.getenv("ALLOW_INSTAT_LOGIN", "").strip() == "1":
        return True
    if os.getenv("INSTAT_DEDICATED_ACCOUNT", "").strip() == "1":
        return True
    return False


def _headers_cache_path() -> Path:
    override = os.getenv("INSTAT_HEADERS_CACHE", "").strip()
    if override:
        return Path(override).expanduser()
    try:
        from instat_config import HEADERS_CACHE
        return Path(HEADERS_CACHE)
    except Exception:
        return Path.home() / ".cache" / "player-cards" / "instat_headers_cache.json"


def _headers_bak_path() -> Path:
    return _headers_cache_path().with_suffix(_headers_cache_path().suffix + ".bak_expired")


async def _launch_chromium(playwright, *, headless: bool = True, proxy=None):
    """Launch Chromium; fall back to system Chrome when Playwright browsers missing."""
    last_err: Exception | None = None
    for attempt in (
        {"headless": headless, "proxy": proxy},
        {"headless": headless, "proxy": proxy, "channel": "chrome"},
    ):
        try:
            return await playwright.chromium.launch(**{k: v for k, v in attempt.items() if v is not None or k == "headless"})
        except Exception as e:
            last_err = e
            if "Executable doesn't exist" not in str(e) and "chrome-headless-shell" not in str(e):
                raise
            logger.warning("Chromium launch failed (%s) — trying next launcher", e)
    raise last_err or RuntimeError("Could not launch Chromium/Chrome")


async def _launch_persistent(playwright, profile: Path, *, headless: bool = True, proxy=None, args=None):
    last_err: Exception | None = None
    launch_args = args or ["--disable-blink-features=AutomationControlled"]
    for channel in (None, "chrome"):
        try:
            kwargs: dict = {
                "headless": headless,
                "args": launch_args,
            }
            if proxy is not None:
                kwargs["proxy"] = proxy
            if channel:
                kwargs["channel"] = channel
            return await playwright.chromium.launch_persistent_context(str(profile), **kwargs)
        except Exception as e:
            last_err = e
            if "Executable doesn't exist" not in str(e) and "chrome-headless-shell" not in str(e):
                raise
            logger.warning("Persistent Chromium failed (%s) — trying channel=chrome", e)
    raise last_err or RuntimeError("Could not launch persistent Chromium/Chrome")


def _jwt_exp(token: str | None) -> int | None:
    """Return JWT exp (unix) or None if not a JWT."""
    if not token:
        return None
    raw = token[7:].strip() if token.lower().startswith("bearer ") else token.strip()
    parts = raw.split(".")
    if len(parts) < 2:
        return None
    import base64

    pad = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(pad.encode("ascii")))
        exp = payload.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


def _auth_file_path() -> str:
    return os.getenv("INSTAT_AUTH_FILE", AUTH_FILE)


def _user_data_dir() -> Path | None:
    raw = os.getenv("INSTAT_USER_DATA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    # Default durable profile beside auth.json
    root = Path(_auth_file_path()).expanduser().resolve().parent
    return root / ".instat_browser_profile"


def _cdp_url() -> str | None:
    u = os.getenv("INSTAT_CDP_URL", "").strip()
    return u or None
TEAM_ID = 25195
SEASON_ID = 36
AUTH_FILE = "auth.json"
OUTPUT_DIR = os.path.expanduser("~/Desktop/Instat_API_Downloads")
try:
    from instat_config import apply_to_instat_module

    apply_to_instat_module()
except ImportError:
    pass
# Set a default proxy server here (e.g. "socks5://127.0.0.1:9050" or "http://username:password@ip:port")
# If set, all traffic will route through it. If None, it checks environment variables or uses direct connection.
PROXY_URL = None
API_BASE = "https://www.hudl.com/app/metropole/shim/api-hockey.instatscout.com"
DATA_URL = f"{API_BASE}/data"
STATS_URL = f"{API_BASE}/stats/add"


class InStatCache:
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(__file__), "instat_cache.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS api_cache (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url TEXT NOT NULL,
                        payload_hash TEXT NOT NULL,
                        payload_raw TEXT,
                        response TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_url_payload_hash 
                    ON api_cache (url, payload_hash)
                """)
        except Exception as e:
            logger.error(f"Failed to initialize SQLite cache database at {self.db_path}: {e}")

    def get(self, url, payload_hash):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT response FROM api_cache WHERE url = ? AND payload_hash = ?",
                    (url, payload_hash)
                )
                row = cursor.fetchone()
                if row:
                    return row[0]
        except Exception as e:
            logger.error(f"Error reading from SQLite cache: {e}")
        return None

    def set(self, url, payload_hash, payload_raw, response):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO api_cache (url, payload_hash, payload_raw, response)
                    VALUES (?, ?, ?, ?)
                    """,
                    (url, payload_hash, payload_raw, response)
                )
        except Exception as e:
            logger.error(f"Error writing to SQLite cache: {e}")


class InStatAPI:
    def __init__(self):
        self.context = None
        self.page = None
        self.browser = None
        self.auth_headers = {}
        self._playwright = None
        self._http_client = None
        self.team_map = self._load_team_map()
        self.cache = InStatCache()
        self._request_lock = asyncio.Lock()
        self._last_request_time = 0.0
        # Spacing between request *starts* (sync layer may run 3–5 concurrent).
        self._cooldown = float(os.getenv("INSTAT_MIN_INTERVAL", "0.35"))
        self._gear_cache: dict[int, list] = {}
        self._pbp_metrics_cache: list[str] | None = None
        self._col_map_cache: dict[int, dict] = {}
        self._headers_fingerprint: str | None = None

    def _load_env_auth(self) -> bool:
        """Use captured API headers from env or local file cache (no Hudl login / Playwright)."""
        x_token = os.getenv("INSTAT_X_AUTH_TOKEN", "").strip()
        authorization = os.getenv("INSTAT_AUTHORIZATION", "").strip()
        if not x_token or not authorization:
            for cache_file in (_headers_cache_path(), _headers_bak_path()):
                if not cache_file.exists():
                    continue
                try:
                    data = json.loads(cache_file.read_text(encoding="utf-8"))
                    if data.get("x-auth-token") and data.get("authorization"):
                        self.auth_headers = {
                            "x-auth-token": data["x-auth-token"],
                            "authorization": data["authorization"],
                        }
                        src = "bak_expired" if cache_file == _headers_bak_path() else "cache"
                        logger.info("InStat API auth loaded from local headers %s file", src)
                        return True
                except Exception as e:
                    logger.debug("Failed to load cached headers (%s): %s", cache_file, e)
            return False
        self.auth_headers = {
            "x-auth-token": x_token,
            "authorization": authorization,
        }
        logger.info("InStat API auth loaded from environment")
        return True

    def headers_near_expiry(self, hours: float = 36.0) -> bool:
        """True if either JWT is missing or expires within `hours`."""
        now = time.time()
        threshold = now + hours * 3600
        for key in ("authorization", "x-auth-token"):
            exp = _jwt_exp(self.auth_headers.get(key))
            if exp is None or exp <= threshold:
                return True
        return False

    def invalidate_cached_headers(self, *, discard_memory: bool = True) -> None:
        """Park dead tokens as bak — never delete last-known JWTs.

        Important: keep bak forever so a failed Playwright refresh cannot leave
        zero cache files. Soft mode (discard_memory=False) parks disk copy while
        refresh is in flight without wiping in-memory tokens until new ones land.
        """
        if discard_memory:
            self.auth_headers = {}
            self._headers_fingerprint = None
        cache = _headers_cache_path()
        bak = _headers_bak_path()
        if cache.is_file():
            try:
                if bak.is_file():
                    bak.unlink()
                cache.replace(bak)
                logger.info("Parked headers cache → %s (kept for recovery)", bak)
            except Exception as e:
                logger.debug("Could not park headers cache: %s", e)
        os.environ.pop("INSTAT_X_AUTH_TOKEN", None)
        os.environ.pop("INSTAT_AUTHORIZATION", None)

    async def _ensure_http_client(self) -> None:
        if self._http_client is None:
            import httpx

            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(90.0, connect=20.0),
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            )

    def _persist_auth_headers(self) -> None:
        if not self.auth_headers.get("x-auth-token"):
            return
        fingerprint = (
            f"{self.auth_headers.get('x-auth-token', '')[:24]}|"
            f"{self.auth_headers.get('authorization', '')[:24]}"
        )
        if fingerprint == self._headers_fingerprint:
            return
        try:
            cache = _headers_cache_path()
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(
                json.dumps({
                    "x-auth-token": self.auth_headers.get("x-auth-token", ""),
                    "authorization": self.auth_headers.get("authorization", ""),
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }, indent=2),
                encoding="utf-8",
            )
            self._headers_fingerprint = fingerprint
            logger.info("Persisted InStat auth headers to %s", cache)
        except Exception as e:
            logger.debug("Could not persist auth headers: %s", e)

    async def _post(self, url: str, payload: dict, *, allow_auth_refresh: bool = True) -> tuple[int, str | bytes]:
        max_attempts = 5
        status = 0
        body: str | bytes = b""
        auth_retried = False
        for attempt in range(max_attempts):
            headers = await self._get_auth_headers()
            if self._http_client is not None:
                response = await self._http_client.post(url, json=payload, headers=headers)
                status = response.status_code
                body = response.content
            elif self.context is not None:
                response = await self.context.request.post(url, data=payload, headers=headers)
                status = response.status
                body = await response.body()
            else:
                logger.error("No HTTP client or Playwright context for POST")
                return 0, b""

            if status == 401 and allow_auth_refresh and not auth_retried:
                auth_retried = True
                if getattr(self, "_refreshing_auth", False):
                    return status, body
                if await self.refresh_auth():
                    continue
                return status, body
            if status in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                delay = min(2 ** attempt + random.uniform(0, 0.5), 12.0)
                if status == 429:
                    delay = max(delay, 3.0)
                logger.warning("HTTP %s from InStat — retrying in %.1fs", status, delay)
                await asyncio.sleep(delay)
                continue
            return status, body
        return status, body

    async def probe_auth(self) -> bool:
        """Cheap auth check: matches list for configured team/season.

        Never triggers refresh_auth (avoids 401 recursion).
        """
        await self._ensure_http_client()
        status, body = await self._post(
            DATA_URL,
            {
                "proc": "scout_uni_advanced_matches_list",
                "params": {"_p_season_id": SEASON_ID, "_p_team_id": TEAM_ID},
            },
            allow_auth_refresh=False,
        )
        if 200 <= status < 300:
            self._persist_auth_headers()
            return True
        logger.error("InStat auth probe failed: HTTP %s", status)
        if isinstance(body, (bytes, bytearray)) and body:
            logger.debug("Probe body: %s", body[:200])
        return False

    def _load_team_map(self):
        """Load team ID mappings from target_team_ids.json"""
        path = os.path.join(os.path.dirname(__file__), "target_team_ids.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return {}

    async def get_team_id(self, team_name):
        """Find a team ID by name (case-insensitive)"""
        # 1. Direct match in team_map
        if team_name in self.team_map:
            return self.team_map[team_name]["id"]
        
        # 2. Fuzzy match in team_map
        for name, data in self.team_map.items():
            if team_name.lower() in name.lower() or team_name.lower() in data["full_name"].lower():
                return data["id"]
        
        # 3. Fallback: Search the InStat database via API
        logger.info(f"Team '{team_name}' not in local map. Searching InStat database...")
        search_result = await self.find_team_by_name(team_name)
        if search_result:
            return search_result
        
        # 4. Fallback: try to treat as ID if it's numeric
        try:
            return int(team_name)
        except ValueError:
            logger.error(f"Could not find team ID for: {team_name}")
            return None

    async def find_team_by_name(self, query):
        """Search for a team ID by name using the scout_uni_search procedure"""
        payload = {
            "params": {
                "_ps_any_text": query
            },
            "proc": "scout_uni_search"
        }
        
        # Determine preferred gender (1 = Men, 2 = Women)
        # Default to 2 (Women) since this is a women's hockey analytics system,
        # unless "men" or similar is explicitly mentioned in the query.
        preferred_gender = 2
        query_lower = query.lower()
        if "men" in query_lower or "male" in query_lower or "(m)" in query_lower:
            preferred_gender = 1
        elif "women" in query_lower or "female" in query_lower or "(w)" in query_lower:
            preferred_gender = 2
            
        try:
            # Use data endpoint for this procedure
            response = await self.api_call("scout_uni_search", payload["params"])
            logger.info(f"Search API Response: {json.dumps(response)[:500]}...")
            if response and 'data' in response and len(response['data']) > 0:
                raw_results = response['data'][0].get("scout_uni_search", {})
                
                # The response is a dict with keys like 'teams', 'tournaments', etc.
                # We are primarily interested in 'teams'
                teams = raw_results.get("teams") or []
                if not teams and isinstance(raw_results, list):
                    # Fallback if it actually is a list in some cases
                    teams = raw_results

                parsed_teams = []
                for res in teams:
                    if isinstance(res, str):
                        try: res = json.loads(res)
                        except: continue
                    if isinstance(res, dict):
                        parsed_teams.append(res)

                if parsed_teams:
                    norm_q = query_lower.replace(" men", "").replace(" male", "").strip()

                    def _name(t: dict) -> str:
                        return (t.get("name_eng") or t.get("n_en") or "").strip()

                    # 1. Exact NHL name + preferred gender (e.g. "Dallas Stars" not youth squads)
                    for t in parsed_teams:
                        t_name = _name(t)
                        if t_name.lower() == norm_q and t.get("gender") == preferred_gender:
                            logger.info(
                                f"Found exact name match: {t_name} (ID: {t.get('id')}, Gender: {t.get('gender')})"
                            )
                            return t.get("id")

                    # 2. First team with preferred gender
                    for t in parsed_teams:
                        t_gender = t.get("gender")
                        if t_gender == preferred_gender:
                            t_id = t.get("id")
                            t_name = _name(t)
                            logger.info(f"Found preferred gender match: {t_name} (ID: {t_id}, Gender: {t_gender})")
                            return t_id
                    
                    # 2. Fallback to other gender if preferred not found
                    other_gender = 1 if preferred_gender == 2 else 2
                    for t in parsed_teams:
                        t_gender = t.get("gender")
                        if t_gender == other_gender:
                            t_id = t.get("id")
                            t_name = t.get("name_eng") or t.get("n_en")
                            logger.info(f"Found fallback gender match: {t_name} (ID: {t_id}, Gender: {t_gender})")
                            return t_id

                    # 3. Fallback to the very first parsed team in search results
                    t_first = parsed_teams[0]
                    t_id = t_first.get("id")
                    t_name = t_first.get("name_eng") or t_first.get("n_en")
                    logger.info(f"Fallback to first search result: {t_name} (ID: {t_id})")
                    return t_id
            return None
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return None

    # ─── Authentication ──────────────────────────────────────────
    def _get_proxy_config(self):
        """Parse proxy options from config or environment variables"""
        proxy_env = PROXY_URL or os.getenv("INSTAT_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        if not proxy_env:
            return None
        
        server = proxy_env
        username = None
        password = None
        
        if "@" in proxy_env:
            try:
                parts = proxy_env.split("@")
                server_part = parts[1]
                cred_part = parts[0]
                
                proto = "http://"
                if "://" in cred_part:
                    proto, cred_part = cred_part.split("://")
                    proto = proto + "://"
                
                server = proto + server_part
                if ":" in cred_part:
                    username, password = cred_part.split(":")
                else:
                    username = cred_part
            except Exception as e:
                logger.warning(f"Failed parsing proxy format: {e}. Using raw proxy string.")
                server = proxy_env

        proxy_opts = {"server": server}
        if username:
            proxy_opts["username"] = username
        if password:
            proxy_opts["password"] = password
            
        logger.info(f"Configuring Playwright proxy: {server} (authenticated: {bool(username)})")
        return proxy_opts

    async def login(self, playwright):
        """Credential login — kicks other users on shared Hudl accounts.

        Refused unless ALLOW_INSTAT_LOGIN=1 or INSTAT_DEDICATED_ACCOUNT=1.
        """
        if not _login_allowed():
            raise RuntimeError(
                "InStat credential login blocked (protects shared sessions). "
                "For a dedicated automation account set INSTAT_DEDICATED_ACCOUNT=1 "
                "(and HUDL_USERNAME / HUDL_PASSWORD). "
                "Or one-shot: ALLOW_INSTAT_LOGIN=1."
            )
        if not USERNAME or not PASSWORD:
            raise RuntimeError(
                "Hudl credentials missing. Set HUDL_USERNAME / HUDL_PASSWORD "
                "or provide hudl_credentials.py."
            )
        logger.warning(
            "Performing credential login (INSTAT_DEDICATED_ACCOUNT / ALLOW_INSTAT_LOGIN). "
            "If this is a shared scout account, other sessions will be kicked."
        )
        proxy_opts = self._get_proxy_config()
        browser = await _launch_chromium(playwright, headless=True, proxy=proxy_opts)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto("https://app.hudl.com/instat/hockey/login", wait_until="load")
        await asyncio.sleep(3)

        await page.fill('input[type="email"]', USERNAME)
        await page.click('button:has-text("Continue")')
        await asyncio.sleep(3)

        await page.fill('input[type="password"]', PASSWORD)
        await page.click('button:has-text("Continue")')
        # Wait until Auth0 hands us back to the Hudl SPA (or timeout).
        try:
            await page.wait_for_url(
                lambda u: "identity.hudl.com" not in u and "/login" not in u,
                timeout=90000,
            )
        except Exception:
            await asyncio.sleep(12)

        auth_path = _auth_file_path()
        await context.storage_state(path=auth_path)
        logger.info("Session saved to %s", auth_path)

        # Mint API JWTs from this live session before closing.
        self.browser = browser
        self.context = context
        self.page = page
        self._playwright = playwright
        ok = await self._goto_and_capture(page)
        await context.storage_state(path=auth_path)
        await browser.close()
        self.browser = None
        self.context = None
        self.page = None
        if not ok:
            raise RuntimeError("Hudl login completed but InStat JWT capture/probe failed")
        logger.info("Credential login minted verified InStat JWTs")
        return True

    def _attach_header_capture(self, page) -> None:
        async def capture_headers(request):
            if "api-hockey.instatscout.com/data" in request.url and request.method == "POST":
                h = request.headers
                if "x-auth-token" in h:
                    self.auth_headers["x-auth-token"] = h["x-auth-token"]
                if "authorization" in h:
                    self.auth_headers["authorization"] = h["authorization"]
                if self.auth_headers.get("x-auth-token") and self.auth_headers.get("authorization"):
                    # Memory only — never persist until probe_auth() succeeds.
                    pass

        page.on("request", capture_headers)

    async def _wait_for_captured_headers(self, timeout_s: float = 20.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.auth_headers.get("x-auth-token") and self.auth_headers.get("authorization"):
                return True
            await asyncio.sleep(0.5)
        return bool(self.auth_headers.get("x-auth-token") and self.auth_headers.get("authorization"))

    async def _tokens_from_local_storage(self, page) -> bool:
        """Mint API headers from Hudl SPA localStorage (no login, no kick)."""
        try:
            ls = await page.evaluate(
                """() => ({
                  auth0_token: localStorage.getItem('auth0_token'),
                  id_token: localStorage.getItem('id_token'),
                  AuthUser: localStorage.getItem('AuthUser'),
                })"""
            )
        except Exception as e:
            logger.debug("localStorage read failed: %s", e)
            return False
        auth0 = (ls or {}).get("auth0_token") or ""
        xt = (ls or {}).get("id_token") or ""
        if not xt:
            try:
                au = json.loads((ls or {}).get("AuthUser") or "{}")
                xt = au.get("token") or ""
            except Exception:
                xt = ""
        if not auth0 or not xt:
            return False
        authorization = auth0 if auth0.lower().startswith("bearer ") else f"Bearer {auth0}"
        self.auth_headers = {
            "x-auth-token": xt,
            "authorization": authorization,
        }
        # Memory only — probe_auth() persists on success.
        return True

    async def _goto_and_capture(self, page, url: str | None = None) -> bool:
        target = url or f"https://app.hudl.com/instat/hockey/teams/{TEAM_ID}/games"
        self.auth_headers = {}
        self._attach_header_capture(page)
        logger.info("Navigating to InStat to capture auth tokens...")
        await page.goto(target, wait_until="load", timeout=60000)
        await asyncio.sleep(6)
        if "identity.hudl.com" in page.url or "/login" in page.url:
            logger.warning("Redirected to login — browser session is dead")
            self.auth_headers = {}
            return False
        ok = await self._wait_for_captured_headers()
        if not ok:
            # SPA localStorage often has usable tokens even if no API POST fired yet
            ok = await self._tokens_from_local_storage(page)
            if ok:
                logger.info("Captured auth from Hudl localStorage (silent, no login)")
        if not ok:
            return False
        await self._ensure_http_client()
        if not await self.probe_auth():
            logger.warning("Captured tokens failed auth probe — discarding")
            self.auth_headers = {}
            return False
        try:
            if self.context is not None:
                await self.context.storage_state(path=_auth_file_path())
                logger.info("Rolled auth.json storage_state (session keep-alive)")
        except Exception as e:
            logger.debug("Could not persist storage_state: %s", e)
        return True

    async def refresh_from_storage_state(self, playwright) -> bool:
        """Mint JWTs from auth.json cookies (shared-account safe when cookies live)."""
        auth_path = _auth_file_path()
        if not os.path.exists(auth_path):
            logger.info("No auth.json at %s — skip cookie capture", auth_path)
            return False
        proxy_opts = self._get_proxy_config()
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        self.browser = await _launch_chromium(playwright, headless=True, proxy=proxy_opts)
        self.context = await self.browser.new_context(storage_state=auth_path)
        self.page = await self.context.new_page()
        self._playwright = playwright
        ok = await self._goto_and_capture(self.page)
        if ok:
            logger.info("Cookie capture auth verified")
            return True
        return False

    async def refresh_from_persistent_profile(self, playwright) -> bool:
        """Use a durable Chromium user-data-dir that is already logged into Hudl.

        Shared-account safe: never fills username/password (that kicks sessions).
        If the profile is logged out, returns False so CDP / manual login can help.
        """
        profile = _user_data_dir()
        if profile is None:
            return False
        profile.mkdir(parents=True, exist_ok=True)
        proxy_opts = self._get_proxy_config()
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        self.context = await _launch_persistent(
            playwright,
            profile,
            headless=True,
            proxy=proxy_opts,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.browser = self.context.browser
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self._playwright = playwright
        ok = await self._goto_and_capture(self.page)
        if not ok:
            logger.warning(
                "Persistent profile is logged out — not auto-filling credentials "
                "(shared-account safe). Log in once in the InStat Chrome debug window."
            )
            return False
        logger.info("Persistent-profile auth verified")
        return True

    async def refresh_from_cdp(self, playwright, cdp_url: str | None = None) -> bool:
        """Attach to an already-logged-in Chrome (chrome --remote-debugging-port=9222).

        Shared-account safe: reuses a live browser session; never submits a password.
        """
        url = cdp_url or _cdp_url() or "http://127.0.0.1:9222"
        try:
            self.browser = await playwright.chromium.connect_over_cdp(url)
        except Exception as e:
            logger.warning("CDP attach failed (%s): %s", url, e)
            return False
        contexts = self.browser.contexts
        self.context = contexts[0] if contexts else await self.browser.new_context()
        # Prefer an existing Hudl tab if present
        self.page = None
        for p in self.context.pages:
            u = (p.url or "").lower()
            if "hudl.com" in u or "instat" in u:
                self.page = p
                break
        if self.page is None:
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        self._playwright = playwright
        ok = await self._goto_and_capture(self.page)
        if ok:
            logger.info("CDP auth verified (no login — reused live Chrome session)")
            return True
        return False

    async def ensure_auth(self, playwright=None, *, force: bool = False) -> bool:
        """Token-only auth. Never password-login.

        Order: env/cache/bak JWTs → auth.json cookie harvest → live CDP →
        already-logged-in persistent profile. Recovery without login: token bridge.
        """
        if playwright is not None:
            self._playwright = playwright

        live_ok = False
        if self._load_env_auth():
            await self._ensure_http_client()
            if await self.probe_auth():
                live_ok = True
                if not force and not self.headers_near_expiry():
                    logger.info("InStat token auth verified")
                    return True
                logger.info(
                    "InStat tokens valid%s — attempting silent mint (no login)",
                    " but near expiry" if self.headers_near_expiry() else " (force refresh)",
                )
            else:
                logger.warning(
                    "Cached InStat JWTs rejected (401) despite future exp — "
                    "revoked server-side; trying silent cookie/CDP mint (no login)…"
                )

        pw = self._playwright or playwright
        if pw is None and (force or not live_ok or self.headers_near_expiry()):
            try:
                from playwright.async_api import async_playwright

                self._pw_cm = await async_playwright().start()
                self._playwright = self._pw_cm
                pw = self._playwright
            except Exception as e:
                if live_ok:
                    logger.info("Playwright unavailable — continuing with probed tokens")
                    return True
                logger.error("Cannot mint fresh tokens without Playwright: %s", e)
                return False

        if not live_ok:
            self.invalidate_cached_headers(discard_memory=True)

        if pw is not None:
            try:
                if await self.refresh_from_storage_state(pw):
                    return True
            except Exception as e:
                logger.warning("Cookie capture failed: %s", e)

            try:
                cdp = _cdp_url() or "http://127.0.0.1:9222"
                try:
                    import urllib.request

                    urllib.request.urlopen(cdp + "/json/version", timeout=1)
                    cdp_up = True
                except Exception:
                    cdp_up = False
                if cdp_up and await self.refresh_from_cdp(pw):
                    return True
                if not cdp_up:
                    logger.info("No live CDP at %s — skip (will not launch login Chrome)", cdp)
            except Exception as e:
                logger.warning("CDP refresh failed: %s", e)

            try:
                if await self.refresh_from_persistent_profile(pw):
                    return True
            except Exception as e:
                logger.warning("Persistent profile refresh failed: %s", e)

            # Opt-in password login (ALLOW_INSTAT_LOGIN / INSTAT_DEDICATED_ACCOUNT).
            if _login_allowed() and USERNAME and PASSWORD:
                try:
                    await self.login(pw)
                    if self.auth_headers.get("x-auth-token") and await self.probe_auth():
                        return True
                    if await self.refresh_from_storage_state(pw):
                        return True
                except Exception as e:
                    logger.error("Credential login failed: %s", e)

        if live_ok:
            logger.warning("Silent mint failed — keeping currently valid tokens")
            self._load_env_auth()
            return True

        logger.error(
            "InStat JWTs revoked and cannot be minted. Options:\n"
            "  ALLOW_INSTAT_LOGIN=1 python3 instat_auth.py --i-accept-kicking-others\n"
            "  python3 instat_token_bridge.py   # bookmarklet while already in InStat\n"
            "  INSTAT_DEDICATED_ACCOUNT=1       # bot account that can auto-login"
        )
        return False

    async def init_session(self, playwright=None):
        """Initialize authenticated session (delegates to ensure_auth)."""
        self._playwright = playwright
        return await self.ensure_auth(playwright)

    async def refresh_auth(self) -> bool:
        """Refresh auth mid-batch (401 handler) — full ensure_auth cascade."""
        if getattr(self, "_refreshing_auth", False):
            return False
        self._refreshing_auth = True
        try:
            prev = self._headers_fingerprint
            if self._load_env_auth():
                fingerprint = (
                    f"{self.auth_headers.get('x-auth-token', '')[:24]}|"
                    f"{self.auth_headers.get('authorization', '')[:24]}"
                )
                # Only accept cache reload if tokens actually changed AND probe ok
                if fingerprint and fingerprint != prev:
                    await self._ensure_http_client()
                    if await self.probe_auth():
                        self._headers_fingerprint = fingerprint
                        logger.info("Reloaded newer InStat tokens from environment/cache")
                        return True
            # Force full cascade (cookies / profile / CDP / login)
            self.invalidate_cached_headers()
            pw = self._playwright
            if pw is None:
                try:
                    from playwright.async_api import async_playwright
                    self._pw_cm = await async_playwright().start()
                    self._playwright = self._pw_cm
                    pw = self._playwright
                except Exception as e:
                    logger.error("Cannot start Playwright for auth refresh: %s", e)
                    return False
            return await self.ensure_auth(pw, force=True)
        finally:
            self._refreshing_auth = False
    async def _get_auth_headers(self):
        """Build standard headers with captured auth tokens"""
        return {
            "content-type": "application/json",
            **self.auth_headers
        }

    # ─── Helpers for caching/throttling ──────────────────────────
    def _normalize_payload(self, payload):
        if payload is None:
            return ""
        if isinstance(payload, bytes):
            payload = payload.decode('utf-8', errors='ignore')
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return payload
        
        def sort_nested(item):
            if isinstance(item, dict):
                return {k: sort_nested(v) for k, v in sorted(item.items())}
            elif isinstance(item, list):
                return [sort_nested(x) for x in item]
            else:
                return item

        try:
            return json.dumps(sort_nested(payload), sort_keys=True)
        except Exception:
            return str(payload)

    def _hash_payload(self, normalized_payload):
        return hashlib.sha256(normalized_payload.encode("utf-8")).hexdigest()

    def _should_cache(self, url, proc=None, payload=None):
        # Do not cache matches list
        if proc == "scout_uni_advanced_matches_list":
            return False
        # Do not cache team overview stats or team shots map
        if isinstance(payload, dict):
            p_type = payload.get("type")
            if p_type in ["team_shots", "team_stats"]:
                return False
        return True

    async def _throttle(self):
        """Space request starts; lock only covers scheduling (not the HTTP call)."""
        async with self._request_lock:
            now = time.time()
            elapsed = now - self._last_request_time
            required = self._cooldown + random.uniform(0.05, 0.2)
            if elapsed < required:
                await asyncio.sleep(required - elapsed)
            self._last_request_time = time.time()

    # ─── Core API Call ───────────────────────────────────────────
    async def api_call(self, proc, params, bypass_cache=False):
        """Fire a direct API call to the InStat backend"""
        payload = {"proc": proc, "params": params}
        
        # 1. Check cache
        use_cache = not bypass_cache and os.getenv("BYPASS_INSTAT_CACHE") != "1" and self._should_cache(DATA_URL, proc, payload)
        payload_raw = self._normalize_payload(payload)
        payload_hash = self._hash_payload(payload_raw)
        
        if use_cache:
            cached_val = self.cache.get(DATA_URL, payload_hash)
            if cached_val is not None:
                logger.info(f"Cache HIT for API call: {proc}")
                try:
                    return json.loads(cached_val)
                except Exception as e:
                    logger.error(f"Failed to decode cached JSON for {proc}: {e}")
        
        # 2. Throttle before outbound request
        await self._throttle()
        
        # 3. Perform request
        status, body = await self._post(DATA_URL, payload)
        if 200 <= status < 300:
            data = json.loads(body)
            if use_cache:
                self.cache.set(DATA_URL, payload_hash, payload_raw, json.dumps(data))
            return data
        logger.error(f"API call {proc} failed: {status}")
        return None

    # ─── Data Extraction Methods ─────────────────────────────────
    async def get_matches_list(self):
        """Get all matches for the season"""
        result = await self.api_call("scout_uni_advanced_matches_list", {
            "_p_season_id": SEASON_ID,
            "_p_team_id": TEAM_ID
        })
        if result and "data" in result:
            matches = result["data"]
            logger.info(f"Retrieved {len(matches)} matches from API")
            return matches
        return []

    async def get_match_info(self, match_id):
        """Get match metadata (teams, date, score)"""
        result = await self.api_call("scout_uni_match_inf", {"_p_match_id": match_id})
        if result and "data" in result and result["data"]:
            return result["data"][0].get("scout_uni_match_inf", {})
        return {}

    async def get_match_overview(self, match_id):
        """Get match overview stats (team-level stats)"""
        result = await self.api_call("scout_uni_overview_match_stat", {"_p_match_id": match_id})
        if result and "data" in result and result["data"]:
            return result["data"][0].get("scout_uni_overview_match_stat", {})
        return {}

    async def get_match_players(self, match_id):
        """Get per-player stats for a match (skaters + goalies)"""
        result = await self.api_call("scout_uni_match_players_stat", {"_p_match_id": match_id})
        if result and "data" in result and result["data"]:
            return result["data"][0].get("scout_uni_match_players_stat", {})
        return {}

    async def get_export_params(self, match_id):
        """Get export config with player roster and stat column definitions"""
        result = await self.api_call("scout_export_params", {"_p_match_id": match_id})
        if result and "data" in result and result["data"]:
            return result["data"][0].get("scout_export_params", {})
        return {}

    async def get_gear(self, params_type=15):
        """Get stat column definitions (the 'gear' that defines what each column means)"""
        if params_type in self._gear_cache:
            return self._gear_cache[params_type]
        result = await self.api_call("scout_uni_gear", {"_p_params_type": params_type})
        gear = []
        if result and "data" in result and result["data"]:
            gear = result["data"][0].get("scout_uni_gear", []) or []
        self._gear_cache[params_type] = gear
        return gear

    async def get_labels(self, phrase_ids):
        """Get human-readable labels for stat columns"""
        result = await self.api_call("scout_param_lexical", {"lang": "en", "phrases": phrase_ids})
        if result and "data" in result and result["data"]:
            return result["data"][0].get("scout_param_lexical", {})
        return {}

    # ─── Team-Level Aggregate Endpoints (Skaters/Goalies/Lines) ──
    async def get_team_skaters(self, match_ids):
        """Get season-aggregate skater stats (the Skaters tab)"""
        result = await self.api_call("scout_uni_team_players_stat", {
            "_p_team_id": TEAM_ID,
            "_p_match_arr": match_ids
        })
        if result and "data" in result and result["data"]:
            return result["data"][0].get("scout_uni_team_players_stat", {})
        return {}

    async def get_team_goalies(self, match_ids):
        """Get season-aggregate goalie stats (the Goalies tab)"""
        result = await self.api_call("scout_uni_team_players_stat", {
            "_is_gk": 1,
            "_p_team_id": TEAM_ID,
            "_p_match_arr": match_ids
        })
        if result and "data" in result and result["data"]:
            return result["data"][0].get("scout_uni_team_players_stat", {})
        return {}

    async def get_team_lines(self, match_ids, unit_type=2):
        """Get season-aggregate line combination stats (the Lines tab)"""
        result = await self.api_call("scout_uni_team_units_stat", {
            "_c_player_unit_type": unit_type,
            "_p_team_id": TEAM_ID,
            "_p_match_arr": match_ids
        })
        if result and "data" in result and result["data"]:
            return result["data"][0].get("scout_uni_team_units_stat", {})
        return {}

    async def get_team_match_stats(self, match_ids):
        """Get per-game team stats across the season (the Games tab table)"""
        result = await self.api_call("scout_uni_team_matches_stat", {
            "_p_team_id": TEAM_ID,
            "_p_match_arr": match_ids
        })
        if result and "data" in result and result["data"]:
            return result["data"][0].get("scout_uni_team_matches_stat", {})
        return {}

    # ─── Helpers ──────────────────────────────────────────────────
    def _extract_match_ids(self, matches):
        """Parse match IDs from the API response, filtering out metadata IDs"""
        match_ids = []
        if isinstance(matches, list) and matches:
            first = matches[0]
            if isinstance(first, dict) and "scout_uni_advanced_matches_list" in first:
                ml = first["scout_uni_advanced_matches_list"]
                items = ml if isinstance(ml, list) else []
                if isinstance(ml, dict):
                    for v in ml.values():
                        if isinstance(v, list):
                            items.extend(v)
                for m in items:
                    mid = m.get("match_id") or m.get("id")
                    if mid:
                        match_ids.append(int(mid))
        if not match_ids:
            for m in matches:
                if isinstance(m, dict):
                    mid = m.get("match_id") or m.get("id")
                    if mid:
                        match_ids.append(int(mid))
        # Filter out known non-match IDs (season/tournament metadata)
        match_ids = [m for m in match_ids if m > 100000]
        return match_ids

    async def _build_col_map(self, gear_type=15):
        """Build a (param_id, option_id) → readable_name mapping from ALL gear types + labels"""
        # Full map is identical regardless of gear_type arg (always scans 1–19 once).
        if 0 in self._col_map_cache:
            return self._col_map_cache[0]
        # Option ID → situation suffix
        OPTION_SUFFIXES = {
            0: "", 4: " (PP)", 5: " (SH)", 6: " (P1)", 7: " (P2)", 8: " (P3)",
            9: " (ES)", 10: " (OT)", 11: " (3v3)", 12: " (OZ)", 13: " (PP-OZ)",
            14: " (SH-OZ)", 15: " (NZ)", 16: " (PP-NZ)", 17: " (SH-NZ)",
            18: " (DZ)", 265: " (Avg)"
        }

        # Hardcoded English names for params that only have Russian labels in gear
        PARAM_NAMES = {
            18: "C+", 47: "GA", 48: "GA", 49: "TA", 50: "TOI", 52: "DI", 53: "DO",
            55: "TOI", 56: "S%", 64: "CA%", 72: "PID", 73: "P", 75: "FO%",
            84: "SOG For", 86: "Rush S", 88: "DKS-", 91: "SOG Against", 92: "FO-",
            104: "END", 105: "ENS", 110: "PP%", 111: "OZP", 112: "DZP",
            116: "Pass Entry", 117: "FO-", 118: "H-", 119: "SOG Against",
            120: "PSP", 121: "SC", 130: "PK%", 131: "SBL",
            179: "SO", 184: "GGE", 185: "SH Shifts", 186: "PP Shifts",
            188: "RT", 191: "A", 192: "Age", 197: "SC",
            238: "+", 239: "-", 240: "GF", 241: "GA",
            242: "xGPS", 243: "xGF", 244: "xGF", 245: "xGA", 246: "xG+/-",
            249: "xGPG", 271: "Slot Pass", 272: "CORSI%",
            292: "Breakaway S", 293: "Breakaway G",
            300: "FF", 301: "FA", 303: "CF%", 304: "FF%",
            306: "HDSC", 307: "HDSC-G", 308: "HDSC-Miss", 309: "HDSC-SOG",
            311: "LDSC", 312: "LDSC-G", 313: "LDSC-Miss", 314: "LDSC-SOG",
            316: "SC Total", 317: "SC-G", 318: "SC-Miss", 319: "SC-SOG",
            321: "Slot SBL", 322: "Outer SBL",
            327: "Loose Puck RT", 328: "Shot RT",
            344: "Shot RT", 348: "Hand", 350: "Puck Poss",
            1000: "DOB", 1001: "Nationality", 1002: "National Team",
        }

        # Query ALL gear types (1-19) to build the most complete map possible
        all_gear = []
        for gt in range(1, 20):
            gear = await self.get_gear(gt)
            if gear:
                all_gear.extend(gear)

        # Collect label IDs
        label_ids = set()
        for block in all_gear:
            if not isinstance(block, dict):
                continue
            for param in (block.get("params") or []):
                for key in ["lexica_short", "lexica"]:
                    v = param.get(key, "")
                    if v:
                        label_ids.add(str(v))
        labels = await self.get_labels(list(label_ids)) if label_ids else {}

        # Build base name map: param_id → short label (from gear with option_id=0 preferred)
        base_names = {}  # param_id → name
        col_map = {}     # (param_id, option_id) → display name

        for block in all_gear:
            if not isinstance(block, dict):
                continue
            for param in (block.get("params") or []):
                pid = param.get("param_id", 0)
                oid = param.get("option_id", 0)
                short = str(param.get("lexica_short", ""))
                full = str(param.get("lexica", ""))
                name = (labels.get(short, {}).get("text", "")
                        or labels.get(full, {}).get("text", "")
                        or param.get("param_name", ""))
                if name:
                    if pid not in base_names or oid == 0:
                        base_names[pid] = name
                    suffix = OPTION_SUFFIXES.get(oid, f" (o{oid})")
                    col_map[(pid, oid)] = f"{name}{suffix}" if suffix else name

        # Fill any remaining gaps from hardcoded PARAM_NAMES
        for pid, name in PARAM_NAMES.items():
            if pid not in base_names:
                base_names[pid] = name

        # For any (pid, oid) not directly in gear, try to derive from base_names
        # This handles the many o4/o5/o9 variants that share a base param
        def get_col_name(pid, oid):
            if (pid, oid) in col_map:
                return col_map[(pid, oid)]
            base = base_names.get(pid, f"p{pid}")
            suffix = OPTION_SUFFIXES.get(oid, f" (o{oid})")
            return f"{base}{suffix}" if suffix else base

        # Store fallback data for _parse_player_rows to use
        self._base_names = base_names
        self._option_suffixes = OPTION_SUFFIXES
        self._col_map_cache[0] = col_map
        return col_map

    async def _pbp_metric_ids(self) -> list[str]:
        """Derive PBP export metric keys from scout gear (replaces hardcoded list)."""
        if self._pbp_metrics_cache is not None:
            return self._pbp_metrics_cache
        shift_pids = {2, 191, 72, 15, 73, 75, 8, 9, 16, 91, 179, 185, 186}
        allowed_options = {0, 4, 5, 6, 7, 8, 9}
        metric_ids: set[str] = set()
        for gear_type in (15, 14, 13, 12):
            gear = await self.get_gear(gear_type)
            for block in gear or []:
                if not isinstance(block, dict):
                    continue
                for param in block.get("params") or []:
                    pid = int(param.get("param_id") or 0)
                    oid = int(param.get("option_id") or 0)
                    if pid in shift_pids or oid in allowed_options:
                        metric_ids.add(f"{pid}_{oid}")
        for required in (
            "2_0", "191_0", "72_0", "15_0", "73_0", "75_0", "8_0", "9_0", "16_0", "91_0",
            "179_0", "8_4", "8_5", "55_0", "56_0", "96_0", "131_0", "29_0", "27_0", "28_0",
            "271_0", "48_0", "49_0", "50_0", "116_0", "117_0", "118_0", "47_0", "119_0",
            "120_0", "121_0", "12_0", "13_0", "92_0", "17_9", "186_0", "185_0",
        ):
            metric_ids.add(required)
        self._pbp_metrics_cache = sorted(metric_ids)
        return self._pbp_metrics_cache

    def _rows_to_csv(self, rows, output_path):
        """Write a list of row dicts to CSV"""
        if not rows:
            return False
        all_cols = list(dict.fromkeys(k for row in rows for k in row))
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return True

    def _parse_player_rows(self, data, col_map, meta=None):
        """Parse player stat entries into flat row dicts"""
        rows = []
        if isinstance(data, dict) and "stat" in data:
            # Single team format
            teams = [(data.get("name_eng", "Team"), data)]
        elif isinstance(data, dict) and ("team1" in data or "team2" in data):
            teams = []
            for tk in ["team1", "team2"]:
                td = data.get(tk, {})
                if td:
                    teams.append((td.get("name_eng", tk), td))
        elif isinstance(data, list):
            teams = [("", {"stat": data})]
        else:
            return rows

        for team_name, team_data in teams:
            for player in team_data.get("stat", []):
                row = {**(meta or {}), "Team": team_name,
                       "Player": player.get("name_eng", ""),
                       "Number": player.get("num", "")}
                for p in player.get("params", []):
                    pid, oid, val = p.get("p", 0), p.get("o", 0), p.get("v")
                    if (pid, oid) in col_map:
                        col_name = col_map[(pid, oid)]
                    elif hasattr(self, '_base_names') and pid in self._base_names:
                        suffix = self._option_suffixes.get(oid, f" (o{oid})")
                        col_name = f"{self._base_names[pid]}{suffix}" if suffix else self._base_names[pid]
                    else:
                        col_name = f"p{pid}_o{oid}"
                    row[col_name] = val
                rows.append(row)
        return rows

    # ─── CSV Export Methods ──────────────────────────────────────
    async def export_match_csv(self, match_id, output_path):
        """Export a single match's player stats to CSV"""
        match_info = await self.get_match_info(match_id)
        if not match_info:
            logger.warning(f"  No match info for {match_id}")
            return False
        players_data = await self.get_match_players(match_id)
        if not players_data:
            logger.warning(f"  No player data for {match_id}")
            return False
        col_map = await self._build_col_map(15)
        raw_date = match_info.get("match_date", "")
        meta = {"Match_ID": match_id, "Date": raw_date.split("T")[0] if raw_date else ""}
        rows = self._parse_player_rows(players_data, col_map, meta)
        return self._rows_to_csv(rows, output_path)

    async def export_pbp_csv(self, match_id, output_path, bypass_cache=False, team_id=None):
        """Extract full play-by-play events from the 'scout_uni_team_players_stat' API"""
        if team_id is None:
            team_id = TEAM_ID
            
        match_info = await self.get_match_info(match_id)
        if not match_info:
            return False
        
        # Get all players for the match (to get the IDs)
        players_stat = await self.get_match_players(match_id)
        if not players_stat:
            return False
        
        # Collect all player IDs correctly
        player_ids = []
        available_teams = [str(t.get("id")) for t in (players_stat.values() if isinstance(players_stat, dict) else players_stat)]
        team_data = next((t for t in (players_stat.values() if isinstance(players_stat, dict) else players_stat) if str(t.get("id")) == str(team_id)), None)
        if not team_data:
            logger.warning(f"No team data found for match {match_id} and team {team_id}. Available teams: {available_teams}")
            return False
            
        # Collect all player IDs from BOTH teams for the PBP export
        for t_data in (players_stat.values() if isinstance(players_stat, dict) else players_stat):
            for p in t_data.get("stat", []):
                pid = p.get("player_id")
                if pid:
                    player_ids.append(int(pid))
        
        # Build metric list from gear definitions (falls back to core shift/action IDs)
        metrics = await self._pbp_metric_ids()
        
        payload = {
            "name": f"{match_id}_pbp",
            "params": {
                "_p_match_id": int(match_id),
                "_p_halfs": [1, 2, 3, 4, 5], # Include OT/SO
                "_p_lang_id": 1,
                "_p_params_arr": metrics,
                "_p_players_arr": player_ids,
                "_p_teams_arr": None
            },
            "type": "csv"
        }
        
        url = "https://www.hudl.com/app/metropole/shim/api-hockey.instatscout.com/data/export"
        
        # Check cache
        use_cache = not bypass_cache and os.getenv("BYPASS_INSTAT_CACHE") != "1"
        payload_raw = self._normalize_payload(payload)
        payload_hash = self._hash_payload(payload_raw)
        
        if use_cache:
            cached_val = self.cache.get(url, payload_hash)
            if cached_val is not None:
                logger.info(f"Cache HIT for PBP Export of match {match_id}")
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(cached_val)
                return True

        # Throttle before outbound request
        await self._throttle()

        status, body = await self._post(url, payload)
        if 200 <= status < 300:
            content = body.decode("utf-8") if isinstance(body, bytes) else body
            if use_cache:
                self.cache.set(url, payload_hash, payload_raw, content)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        logger.error(f"  PBP Export failed for {match_id}: {status}")
        return False

    async def export_season_games_csv(self, match_ids, output_path):
        """Export season-level match summary by aggregating player stats (Team vs Opponent)"""
        col_map = await self._build_col_map(1) # skater stats gear
        match_rows = []
        
        for mid in match_ids:
            logger.info(f"    Aggregating Games summary for match {mid}...")
            match_info = await self.get_match_info(mid)
            players_data = await self.get_match_players(mid)
            
            if not players_data or not match_info:
                continue
                
            # Find target team name matching TEAM_ID
            target_team_name = ""
            for tk in ["team1", "team2"]:
                t_meta = match_info.get(tk, {})
                if t_meta.get("id") == TEAM_ID:
                    target_team_name = t_meta.get("name_eng") or t_meta.get("n_en")
                    break
            
            row = {
                "Match_ID": mid,
                "Date": match_info.get("match_date", "").split("T")[0]
            }
            
            # Get actual team names from match_info
            team1_actual = match_info.get("team1", {}).get("name_eng", "") or match_info.get("team1", {}).get("n_en", "team1")
            team2_actual = match_info.get("team2", {}).get("name_eng", "") or match_info.get("team2", {}).get("n_en", "team2")
            
            # Map of prefix -> team totals for score calculation
            goals_map = {"Team_": 0, "Opp_": 0}
            
            # Aggregate stats for each team
            for team_key, team_info in players_data.items():
                actual_name = team1_actual if team_key == "team1" else team2_actual
                is_target = False
                if target_team_name:
                    is_target = (actual_name.lower() == target_team_name.lower())
                else:
                    # Fallback to name check
                    is_target = ("clarkson" in actual_name.lower() or "wisconsin" in actual_name.lower())
                    
                is_opp = not is_target
                prefix = "Opp_" if is_opp else "Team_"
                row[f"{prefix}Name"] = actual_name
                
                # Sum up all numeric params for the team
                team_totals = {}
                for p_item in team_info.get("stat", []):
                    for p in p_item.get("params", []):
                        pid, oid, val = p.get("p"), p.get("o"), p.get("v")
                        if isinstance(val, (int, float)):
                            key = (pid, oid)
                            team_totals[key] = team_totals.get(key, 0) + val
                
                # Extract goals for score calculation (Goals is param 2, option 9 or 0)
                goals = team_totals.get((2, 9), team_totals.get((2, 0), 0))
                goals_map[prefix] = int(goals)
                
                # Add to row
                for (pid, oid), total in team_totals.items():
                    col_name = col_name = col_map.get((pid, oid), f"p{pid}_o{oid}")
                    row[f"{prefix}{col_name}"] = total
            
            # Reconstruct score if match_info scores are None
            score1 = match_info.get('score1')
            score2 = match_info.get('score2')
            if score1 is not None and score2 is not None:
                row["Score"] = f"{score1}:{score2}"
            else:
                # Find which team corresponds to team1/team2 to align goals_map
                team1_name = (match_info.get("team1", {})).get("name_eng", "")
                is_team1_target = False
                if target_team_name and team1_name:
                    is_team1_target = (team1_name.lower() == target_team_name.lower())
                else:
                    is_team1_target = ("clarkson" in team1_name.lower() or "wisconsin" in team1_name.lower())
                
                if is_team1_target:
                    row["Score"] = f"{goals_map['Team_']}:{goals_map['Opp_']}"
                else:
                    row["Score"] = f"{goals_map['Opp_']}:{goals_map['Team_']}"
            
            match_rows.append(row)
            await asyncio.sleep(0.1)

        if not match_rows:
            return False
            
        return self._rows_to_csv(match_rows, output_path)






    async def export_skaters_csv(self, match_ids, output_path):
        """Export season-aggregate skater stats to CSV"""
        data = await self.get_team_skaters(match_ids)
        if not data:
            logger.warning("No skater data returned")
            return False
        col_map = await self._build_col_map(1)  # gear type 1 = skaters
        rows = self._parse_player_rows(data, col_map)
        return self._rows_to_csv(rows, output_path)

    async def export_goalies_csv(self, match_ids, output_path):
        """Export season-aggregate goalie stats to CSV"""
        data = await self.get_team_goalies(match_ids)
        if not data:
            logger.warning("No goalie data returned")
            return False
        col_map = await self._build_col_map(9)  # gear type 9 = goalies
        rows = self._parse_player_rows(data, col_map)
        return self._rows_to_csv(rows, output_path)

    async def export_lines_csv(self, match_ids, output_path=None, unit_type=2):
        """Export season-aggregate line combination stats (returns rows or saves to CSV)"""
        col_map = await self._build_col_map(14)  # gear type 14 = lines
        all_rows = []
        batch_size = 10

        for i in range(0, len(match_ids), batch_size):
            batch = match_ids[i:i + batch_size]
            logger.info(f"    Fetching unit type {unit_type} for matches {i+1}-{i+len(batch)}...")
            data = await self.get_team_lines(batch, unit_type=unit_type)
            if not data:
                continue

            stat_list = data.get("stat", []) if isinstance(data, dict) else data if isinstance(data, list) else []
            for unit in stat_list:
                # Lines use 'unit_content' for player names, not 'players'
                players_list = unit.get("unit_content", unit.get("players", []))
                players = ", ".join(p.get("name_eng", "") for p in players_list)
                row = {"Line": players, "Games": unit.get("matches_count", "")}
                for p in unit.get("params", []):
                    pid, oid, val = p.get("p", 0), p.get("o", 0), p.get("v")
                    row[col_map.get((pid, oid), f"p{pid}_o{oid}")] = val
                all_rows.append(row)
            await asyncio.sleep(0.5)

        logger.info(f"    Total line combinations: {len(all_rows)}")
        if output_path:
            return self._rows_to_csv(all_rows, output_path)
        return all_rows

    # ─── Main Pipeline ───────────────────────────────────────────
    async def direct_post(self, url, payload, bypass_cache=False):
        """Fire a raw POST (httpx token path or Playwright context)."""
        use_cache = (
            not bypass_cache
            and os.getenv("BYPASS_INSTAT_CACHE") != "1"
            and self._should_cache(url, payload=payload)
        )
        payload_raw = self._normalize_payload(payload)
        payload_hash = self._hash_payload(payload_raw)

        if use_cache:
            cached_val = self.cache.get(url, payload_hash)
            if cached_val is not None:
                logger.info("Cache HIT for direct_post: %s", url)
                try:
                    return json.loads(cached_val)
                except Exception as e:
                    logger.error("Failed to decode cached JSON for %s: %s", url, e)

        await self._throttle()
        await self._ensure_http_client()
        status, body = await self._post(url, payload)
        if 200 <= status < 300:
            try:
                data = json.loads(body) if isinstance(body, (bytes, bytearray, str)) else body
            except Exception as e:
                logger.error("direct_post JSON decode failed (%s): %s", status, e)
                return None
            if use_cache:
                self.cache.set(url, payload_hash, payload_raw, json.dumps(data))
            return data

        logger.error("POST failed with status %s", status)
        if isinstance(body, (bytes, bytearray)) and body:
            logger.error("Response: %s", body[:200])
        return None

    async def export_shot_map_csv(self, filename):
        """Extract full season shot map via direct API"""
        # Corrected payload based on live traffic inspection
        payload = {
            "type": "team_shots",
            "team_id": TEAM_ID,
            "season_id": SEASON_ID,
            "tournament_id": 3202  # NCAA Division I (W)
        }
        logger.info(f"Fetching full season shot map for Team {TEAM_ID}...")
        try:
            data = await self.direct_post(STATS_URL, payload)
            if not data:
                logger.warning("No data returned from direct_post")
                return False
            
            logger.info(f"API Response keys: {list(data.keys())}")
            if 'data' not in data:
                logger.warning(f"Missing 'data' key in API response. Keys found: {list(data.keys())}")
                return False
            
            rows = data['data']
            if not rows:
                logger.warning("Shot map data is empty")
                return False
            
            # Identify ALL unique keys across all rows to ensure no data (like attack_type) is lost
            all_keys = set()
            for row in rows:
                all_keys.update(row.keys())
            
            # Use a consistent order for columns
            fieldnames = sorted(list(all_keys))
            
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(rows)
            
            logger.info(f"✓ Saved {len(rows)} shots to {os.path.basename(filename)}")
            return True
        except Exception as e:
            logger.error(f"Shot Map Error: {e}")
            return False

    async def export_overview_csv(self, filename):
        """Extract team season overview via direct API"""
        payload = {
            "type": "team_stats",
            "team_id": TEAM_ID,
            "season_id": SEASON_ID,
            "tournament_id": 3202
        }
        try:
            data = await self.direct_post(STATS_URL, payload)
            if not data or 'data' not in data:
                return False
            rows = data['data']
            if not rows: return False
            
            # Detect columns dynamically
            all_keys = set()
            for row in rows: all_keys.update(row.keys())
            fieldnames = sorted(list(all_keys))

            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(rows)
            return True
        except Exception as e:
            logger.error(f"Overview Error: {e}")
            return False

    async def run_full_extraction(self):
        """Extract ALL data: per-game CSVs + season skaters/goalies/lines"""
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # Step 1: Get all match IDs
        logger.info("=" * 60)
        logger.info("STEP 1: Fetching season match list via API...")
        logger.info("=" * 60)
        matches = await self.get_matches_list()
        if not matches:
            logger.error("No matches found!")
            return
        match_ids = self._extract_match_ids(matches)
        logger.info(f"Found {len(match_ids)} matches for the season")

        # Step 2: Per-game stats (Box Score + PBP)
        logger.info("=" * 60)
        logger.info("STEP 2: Extracting per-game stats (Box Score + PBP)...")
        logger.info("=" * 60)
        s, sk, f = 0, 0, 0
        for i, mid in enumerate(match_ids):
            box_path = os.path.join(OUTPUT_DIR, f"game_{mid}.csv")
            pbp_path = os.path.join(OUTPUT_DIR, f"game_{mid}_pbp.csv")
            
            # Extract Box Score
            if not os.path.exists(box_path):
                logger.info(f"  [{i+1}/{len(match_ids)}] Box Score: Extracting match {mid}...")
                try:
                    if await self.export_match_csv(mid, box_path):
                        logger.info(f"    ✓ Box Score saved")
                    else:
                        logger.warning(f"    ✗ Box Score failed")
                except Exception as e:
                    logger.error(f"    ✗ Box Score Error: {e}")
            
            # Extract PBP (Play-by-Play)
            if not os.path.exists(pbp_path):
                logger.info(f"  [{i+1}/{len(match_ids)}] PBP: Extracting match {mid}...")
                try:
                    if await self.export_pbp_csv(mid, pbp_path):
                        logger.info(f"    ✓ PBP saved")
                        s += 1
                    else:
                        logger.warning(f"    ✗ PBP failed")
                        f += 1
                except Exception as e:
                    f += 1
                    logger.error(f"    ✗ PBP Error: {e}")
            else:
                sk += 1

            await asyncio.sleep(0.5)
        logger.info(f"  Matches processed: {s} saved, {sk} skipped, {f} failed")

        # Step 3: Season-aggregate Skaters
        logger.info("=" * 60)
        logger.info("STEP 3: Extracting season SKATERS stats...")
        logger.info("=" * 60)
        skaters_path = os.path.join(OUTPUT_DIR, "season_skaters.csv")
        if await self.export_skaters_csv(match_ids, skaters_path):
            logger.info(f"  ✓ Skaters saved to {skaters_path}")
        else:
            logger.warning("  ✗ Skaters extraction failed")

        # Step 4: Season-aggregate Goalies
        logger.info("=" * 60)
        logger.info("STEP 4: Extracting season GOALIES stats...")
        logger.info("=" * 60)
        goalies_path = os.path.join(OUTPUT_DIR, "season_goalies.csv")
        if await self.export_goalies_csv(match_ids, goalies_path):
            logger.info(f"  ✓ Goalies saved to {goalies_path}")
        else:
            logger.warning("  ✗ Goalies extraction failed")

        # Step 5: Season-aggregate Lines
        logger.info("=" * 60)
        logger.info("STEP 5: Extracting season LINES stats...")
        logger.info("=" * 60)
        lines_path = os.path.join(OUTPUT_DIR, "season_lines.csv")
        if await self.export_lines_csv(match_ids, lines_path):
            logger.info(f"  ✓ Lines saved to {lines_path}")
        else:
            logger.warning("  ✗ Lines extraction failed")

        # Step 6: Season-aggregate Games (Team vs Opponent)
        logger.info("=" * 60)
        logger.info("STEP 6: Extracting season GAMES summary (Team vs Opponent)...")
        logger.info("=" * 60)
        games_path = os.path.join(OUTPUT_DIR, "season_games.csv")
        if await self.export_season_games_csv(match_ids, games_path):
            logger.info(f"  ✓ Season Games saved to {games_path}")
        else:
            logger.warning("  ✗ Season Games extraction failed")

        # Step 7: Season-aggregate Shot Map
        logger.info("=" * 60)
        logger.info("STEP 7: Extracting full season SHOT MAP (with Shot Types & IDs)...")
        logger.info("=" * 60)
        shot_map_path = os.path.join(OUTPUT_DIR, "season_shot_map_API_FINAL.csv")
        if await self.export_shot_map_csv(shot_map_path):
            logger.info(f"  ✓ Shot Map saved to {shot_map_path}")
        else:
            logger.warning("  ✗ Shot Map extraction failed")

        # Step 8: Season Overview
        logger.info("=" * 60)
        logger.info("STEP 8: Extracting Team Season OVERVIEW...")
        logger.info("=" * 60)
        overview_path = os.path.join(OUTPUT_DIR, "season_overview_API_FINAL.csv")
        if await self.export_overview_csv(overview_path):
            logger.info(f"  ✓ Overview saved to {overview_path}")
        else:
            logger.warning("  ✗ Overview extraction failed")

        logger.info(f"  Output dir: {OUTPUT_DIR}")
        logger.info("=" * 60)

    async def close(self):
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        if self.browser:
            await self.browser.close()


async def main():
    parser = argparse.ArgumentParser(description="InStat API Data Extractor")
    parser.add_argument("--team", type=str, default="Clarkson", help="Team ID or Name")
    parser.add_argument("--season", type=int, default=None, help="Season ID")
    parser.add_argument("--config", type=str, default=None, help="Path to clarkson_config.json")
    args = parser.parse_args()

    try:
        from instat_config import apply_to_instat_module, load_team_config

        cfg = load_team_config(args.config)
        apply_to_instat_module(cfg)
    except ImportError:
        cfg = {}

    async with async_playwright() as p:
        api = InStatAPI()
        if await api.init_session(p):
            global TEAM_ID, SEASON_ID, OUTPUT_DIR
            if args.season is not None:
                SEASON_ID = args.season
            elif cfg.get("season_id"):
                SEASON_ID = cfg["season_id"]
            if str(args.team).isdigit():
                TEAM_ID = int(args.team)
            else:
                team_id = await api.get_team_id(args.team)
                if not team_id:
                    logger.error(f"Could not resolve team: {args.team}")
                    return
                TEAM_ID = team_id
            if cfg.get("output_dir"):
                OUTPUT_DIR = str(cfg["output_dir"])
            else:
                clean_team = "".join(c for c in args.team if c.isalnum() or c in (" ", "_", "-")).strip()
                clean_team = clean_team.replace(" ", "_")
                OUTPUT_DIR = os.path.expanduser(
                    f"~/Desktop/My Analytics Work/{clean_team}/Instat_API_Downloads"
                )
            logger.info(f"TEAM_ID={TEAM_ID} SEASON_ID={SEASON_ID} OUTPUT_DIR={OUTPUT_DIR}")
            await api.run_full_extraction()
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
