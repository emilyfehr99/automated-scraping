"""Render HTML player cards to PNG via Playwright in a thread-safe manner."""

from __future__ import annotations

import threading
from pathlib import Path

# Threading lock to serialize all Playwright calls to prevent thread-safety deadlocks
_lock = threading.Lock()


def html_to_png(
    html_path: Path | str,
    png_path: Path | str,
    *,
    width: int = 1540,
    device_scale_factor: int = 3,
    reuse_browser: bool = True,
) -> Path:
    """Export card PNG at ~4K (1400 CSS px × 3 device scale) in a thread-safe lock context."""
    html_path = Path(html_path).resolve()
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError("Playwright required for PNG export: pip install playwright && playwright install chromium") from e

    with _lock:
        p = sync_playwright().start()
        try:
            browser = p.chromium.launch()
            try:
                context = browser.new_context(
                    viewport={"width": width, "height": 900},
                    device_scale_factor=device_scale_factor,
                )
                try:
                    page = context.new_page()
                    page.goto(html_path.as_uri(), wait_until="domcontentloaded")
                    page.wait_for_function(
                        """() => {
                          const imgs = [...document.querySelectorAll('img.photo, img.team-logo')];
                          if (!imgs.length) return true;
                          return imgs.every((img) => {
                            const src = img.getAttribute('src');
                            if (!src) return true;
                            if (img.complete && img.naturalWidth === 0) return true;
                            return img.complete && img.naturalWidth > 0;
                          });
                        }""",
                        timeout=8_000,
                    )
                    page.locator(".card").screenshot(path=str(png_path), type="png")
                finally:
                    context.close()
            finally:
                browser.close()
        finally:
            p.stop()

    return png_path
