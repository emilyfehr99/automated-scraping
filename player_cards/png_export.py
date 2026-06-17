"""Render HTML player cards to PNG via Playwright."""

from __future__ import annotations

import atexit
from pathlib import Path
from typing import Any

_browser: Any = None
_playwright: Any = None


def _shutdown_browser() -> None:
    global _browser, _playwright
    try:
        if _browser is not None:
            _browser.close()
    except Exception:
        pass
    try:
        if _playwright is not None:
            _playwright.stop()
    except Exception:
        pass
    _browser = None
    _playwright = None


atexit.register(_shutdown_browser)


def _get_browser():
    global _browser, _playwright
    if _browser is not None:
        return _browser
    from playwright.sync_api import sync_playwright

    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch()
    return _browser


def html_to_png(
    html_path: Path | str,
    png_path: Path | str,
    *,
    width: int = 1540,
    device_scale_factor: int = 3,
    reuse_browser: bool = True,
) -> Path:
    """Export card PNG at ~4K (1400 CSS px × 3 device scale)."""
    html_path = Path(html_path).resolve()
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("Playwright required for PNG export: pip install playwright && playwright install chromium") from e

    owns_browser = not reuse_browser
    if reuse_browser:
        browser = _get_browser()
        p = None
    else:
        p = sync_playwright().start()
        browser = p.chromium.launch()

    context = browser.new_context(
        viewport={"width": width, "height": 900},
        device_scale_factor=device_scale_factor,
    )
    page = context.new_page()
    page.goto(html_path.as_uri(), wait_until="domcontentloaded")
    page.wait_for_function(
        """() => {
          const img = document.querySelector('img.photo');
          if (!img) return true;
          return img.complete && img.naturalWidth >= 320;
        }""",
        timeout=8_000,
    )
    page.locator(".card").screenshot(path=str(png_path), type="png")
    context.close()
    if owns_browser and p is not None:
        browser.close()
        p.stop()
    return png_path
