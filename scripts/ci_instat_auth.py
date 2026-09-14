#!/usr/bin/env python3
"""CI Helper: obtain and verify InStat API tokens for parallel shards."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hudl-scraping"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ci_instat_auth")


async def main() -> None:
    from playwright.async_api import async_playwright
    from instat_api import InStatAPI

    hudl_dir = ROOT / "hudl-scraping"
    hudl_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(hudl_dir)

    # 1. Restore auth.json if provided in env
    auth_json_b64 = os.getenv("INSTAT_AUTH_JSON", "").strip()
    if auth_json_b64:
        try:
            auth_file = hudl_dir / "auth.json"
            auth_file.write_bytes(base64.b64decode(auth_json_b64))
            logger.info("Restored auth.json from INSTAT_AUTH_JSON")
        except Exception as exc:
            logger.warning("Failed to decode INSTAT_AUTH_JSON: %s", exc)

    api = InStatAPI()

    # 2. First check if existing tokens (from env/secrets or cache) are valid
    logger.info("Checking if existing InStat tokens are valid...")
    try:
        if await api.init_session(None):
            token = api.auth_headers.get("x-auth-token")
            auth_header = api.auth_headers.get("authorization")
            if token and auth_header:
                logger.info("Existing InStat API tokens are valid!")
                _export_tokens(token, auth_header)
                await api.close()
                return
    except Exception as exc:
        logger.warning("Initial token check raised: %s", exc)

    # 3. If not valid, perform credential login with Playwright
    logger.info("Tokens expired or missing. Minting fresh tokens via Playwright login...")
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

    logger.info("Successfully minted and verified fresh InStat tokens!")
    _export_tokens(token, auth_header)
    await api.close()


def _export_tokens(token: str, authorization: str) -> None:
    import json
    import shutil

    auth_dir = ROOT / "instat_auth_session"
    auth_dir.mkdir(parents=True, exist_ok=True)
    cache_payload = {
        "x-auth-token": token,
        "authorization": authorization,
    }
    (auth_dir / "instat_headers_cache.json").write_text(json.dumps(cache_payload, indent=2))
    auth_json = ROOT / "hudl-scraping" / "auth.json"
    if auth_json.is_file():
        shutil.copy2(auth_json, auth_dir / "auth.json")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write("auth_ok=true\n")
    logger.info("Exported InStat auth cache to %s", auth_dir)


if __name__ == "__main__":
    asyncio.run(main())
