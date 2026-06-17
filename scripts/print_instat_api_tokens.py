#!/usr/bin/env python3
"""Print InStat API headers for GitHub Actions secrets (one-time local helper)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hudl-scraping"))


async def main() -> None:
    from playwright.async_api import async_playwright
    from instat_api import InStatAPI

    auth = ROOT / "hudl-scraping" / "auth.json"
    if not auth.is_file():
        raise SystemExit(f"Missing {auth} — log in locally first or export tokens manually.")

    os.chdir(ROOT / "hudl-scraping")
    async with async_playwright() as p:
        api = InStatAPI()
        if not await api.init_session(p):
            raise SystemExit("Failed to capture InStat API headers")
        print("Add these GitHub repo secrets:")
        print(f"INSTAT_X_AUTH_TOKEN={api.auth_headers.get('x-auth-token', '')}")
        print(f"INSTAT_AUTHORIZATION={api.auth_headers.get('authorization', '')}")
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
