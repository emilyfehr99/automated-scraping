"""NHL player microstat cards — NHL API + A3Z + InStat PBP."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "build_player_card_profile",
    "generate_player_card",
    "load_stored_profile",
    "open_store",
    "CardStore",
    "DEFAULT_STORE_PATH",
    "render_player_card_html",
    "write_player_card_html",
    "html_to_png",
    "render_player_card",
]

_LAZY: dict[str, tuple[str, str]] = {
    "build_player_card_profile": (".profile", "build_player_card_profile"),
    "generate_player_card": (".generators", "generate_card"),
    "load_stored_profile": (".card_store", "load_stored_profile"),
    "open_store": (".card_store", "open_store"),
    "CardStore": (".card_store", "CardStore"),
    "DEFAULT_STORE_PATH": (".card_store", "DEFAULT_STORE_PATH"),
    "render_player_card_html": (".html_renderer", "render_player_card_html"),
    "write_player_card_html": (".html_renderer", "write_player_card_html"),
    "render_player_card": (".html_renderer", "render_player_card"),
    "html_to_png": (".png_export", "html_to_png"),
}


def __getattr__(name: str) -> Any:
    spec = _LAZY.get(name)
    if spec is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = spec
    value = getattr(import_module(module_name, __name__), attr)
    globals()[name] = value
    return value
