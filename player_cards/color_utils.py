"""Contrast helpers for team-branded card fills."""

from __future__ import annotations


def _parse_hex(hex_color: str) -> tuple[int, int, int] | None:
    raw = str(hex_color or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return None
    try:
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        return None


def luminance(hex_color: str) -> float:
    rgb = _parse_hex(hex_color)
    if rgb is None:
        return 0.5
    r, g, b = rgb
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def text_on_background(hex_color: str) -> str:
    """Return #111 or #fff for readable text on a solid fill."""
    return "#111" if luminance(hex_color) > 0.58 else "#fff"


def elite_tile_fill(primary: str, accent: str) -> str:
    """Brand fill for 90+ percentile tiles and the Game Score hero."""
    if luminance(accent) > 0.82:
        return primary
    return accent


def emphasis_on_white(primary: str, accent: str) -> str:
    """Brand color for elite percentile labels on white/near-white backgrounds."""
    return primary if luminance(primary) <= luminance(accent) else accent


def photo_overlay_text(primary: str, accent: str) -> str:
    """Jersey / placeholder text over the photo column."""
    return accent if luminance(accent) >= luminance(primary) else primary


def theme_text_vars(primary: str, accent: str) -> dict[str, str]:
    elite_fill = elite_tile_fill(primary, accent)
    return {
        "primary_text": text_on_background(primary),
        "accent_text": text_on_background(accent),
        "elite_fill": elite_fill,
        "elite_fill_text": text_on_background(elite_fill),
        "elite_em": emphasis_on_white(primary, accent),
        "photo_overlay": photo_overlay_text(primary, accent),
    }
