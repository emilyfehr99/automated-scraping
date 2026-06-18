"""JSON helpers — strict output safe for browser JSON.parse (no NaN/Infinity)."""

from __future__ import annotations

import json
import math
from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(n) or math.isinf(n):
        return default
    return n


def sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(v) for v in obj]
    return obj


def dumps_json(obj: Any, *, indent: int | None = None) -> str:
    clean = sanitize_for_json(obj)
    if indent is None:
        return json.dumps(clean, separators=(",", ":"), allow_nan=False)
    return json.dumps(clean, indent=indent, allow_nan=False)
