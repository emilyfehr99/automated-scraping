#!/usr/bin/env python3
"""CI Helper: mint verified InStat JWTs for parallel shards.

Hudl routinely revokes JWTs. Do not treat repo secrets / cache as durable.
Default CI path is --force-remint (dedicated-account Playwright login).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hudl-scraping"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ci_instat_auth")

# Build jobs can run for hours; refuse short-lived mints.
_MIN_TTL_HOURS = float(os.getenv("INSTAT_MIN_TTL_HOURS", "6"))


def _flag(name: str) -> bool:
    return name in sys.argv


def _ttl_hours(token: str | None) -> float | None:
    from instat_api import _jwt_exp

    exp = _jwt_exp(token)
    if not exp:
        return None
    return (exp - time.time()) / 3600.0


def _assert_ttl(token: str, authorization: str) -> None:
    xt_h = _ttl_hours(token)
    auth_h = _ttl_hours(authorization)
    logger.info("JWT TTL x-auth=%.1fh authorization=%.1fh", xt_h or -1, auth_h or -1)
    for label, hours in (("x-auth-token", xt_h), ("authorization", auth_h)):
        if hours is None:
            raise SystemExit(f"Minted {label} has no exp claim — refusing to continue")
        if hours < _MIN_TTL_HOURS:
            raise SystemExit(
                f"Minted {label} TTL {hours:.1f}h < required {_MIN_TTL_HOURS:.1f}h"
            )


async def main() -> None:
    from instat_api import InStatAPI

    force = _flag("--force-remint")
    tokens_only = _flag("--tokens-only")
    if force and tokens_only:
        raise SystemExit("Pass only one of --force-remint / --tokens-only")

    hudl_dir = ROOT / "hudl-scraping"
    hudl_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(hudl_dir)

    # Restore auth.json if provided in env (cookie jar for remint / fallback)
    auth_json_b64 = os.getenv("INSTAT_AUTH_JSON", "").strip()
    if auth_json_b64:
        try:
            auth_file = hudl_dir / "auth.json"
            auth_file.write_bytes(base64.b64decode(auth_json_b64))
            logger.info("Restored auth.json from INSTAT_AUTH_JSON")
        except Exception as exc:
            logger.warning("Failed to decode INSTAT_AUTH_JSON: %s", exc)

    api = InStatAPI()

    if not force:
        logger.info("Checking if existing InStat tokens are valid...")
        try:
            if await api.init_session(None):
                token = api.auth_headers.get("x-auth-token")
                auth_header = api.auth_headers.get("authorization")
                if token and auth_header:
                    try:
                        _assert_ttl(token, auth_header)
                    except SystemExit as exc:
                        logger.warning("%s — will remint", exc)
                    else:
                        logger.info("Existing InStat API tokens are valid!")
                        _export_tokens(token, auth_header, reminted=False)
                        await api.close()
                        return
        except Exception as exc:
            logger.warning("Initial token check raised: %s", exc)

        if tokens_only:
            await api.close()
            logger.error("Existing tokens are not valid (--tokens-only)")
            raise SystemExit(1)

    # Force path / fallback: dedicated-account Playwright login.
    from playwright.async_api import async_playwright

    logger.info("Minting fresh InStat JWTs via dedicated-account Playwright login...")
    async with async_playwright() as p:
        try:
            if not await api.ensure_auth(p, force=True):
                await api.login(p)
        except Exception as exc:
            logger.error("Playwright login attempt failed: %s", exc)

    if not await api.probe_auth():
        logger.error("InStat auth probe failed after login attempt")
        await api.close()
        raise SystemExit(1)

    token = api.auth_headers.get("x-auth-token")
    auth_header = api.auth_headers.get("authorization")
    if not token or not auth_header:
        logger.error("Auth probe succeeded but tokens missing from headers")
        await api.close()
        raise SystemExit(1)

    _assert_ttl(token, auth_header)
    logger.info("Successfully minted and verified fresh InStat tokens!")
    _export_tokens(token, auth_header, reminted=True)
    await api.close()


def _export_tokens(token: str, authorization: str, *, reminted: bool) -> None:
    import json
    import shutil

    auth_dir = ROOT / "instat_auth_session"
    auth_dir.mkdir(parents=True, exist_ok=True)
    cache_payload = {
        "x-auth-token": token,
        "authorization": authorization,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reminted": reminted,
    }
    (auth_dir / "instat_headers_cache.json").write_text(json.dumps(cache_payload, indent=2))
    auth_json = ROOT / "hudl-scraping" / "auth.json"
    if auth_json.is_file():
        shutil.copy2(auth_json, auth_dir / "auth.json")

    # Keep home cache warm for any follow-up steps on the same runner.
    home_cache = Path.home() / ".cache" / "player-cards" / "instat_headers_cache.json"
    home_cache.parent.mkdir(parents=True, exist_ok=True)
    home_cache.write_text(json.dumps(cache_payload, indent=2))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write("auth_ok=true\n")
            f.write(f"reminted={'true' if reminted else 'false'}\n")
    logger.info("Exported InStat auth cache to %s (reminted=%s)", auth_dir, reminted)


if __name__ == "__main__":
    asyncio.run(main())
