"""Cell-level shape cache for baseplate and baseplate support."""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import Callable

import Part

_CELL_CACHE_MAX = 64
_CELL_CACHE: OrderedDict[str, Part.Shape] = OrderedDict()


def set_cell_cache_max_entries(max_entries: int) -> None:
    global _CELL_CACHE_MAX
    _CELL_CACHE_MAX = max(0, int(max_entries))
    if _CELL_CACHE_MAX == 0:
        _CELL_CACHE.clear()
        return
    while len(_CELL_CACHE) > _CELL_CACHE_MAX:
        _CELL_CACHE.popitem(last=False)


def normalize(value: object) -> object:
    if is_dataclass(value):
        return {
            field.name: normalize(getattr(value, field.name)) for field in dataclass_fields(value)
        }
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 4)
    if hasattr(value, "Value"):
        try:
            return round(float(value), 4)  # type: ignore[arg-type]
        except Exception:
            return str(value)
    return str(value)


def make_key(payload: dict) -> str:
    return json.dumps(normalize(payload), sort_keys=True, separators=(",", ":"))


def get_or_build(key: str, build_fn: Callable[[], Part.Shape]) -> Part.Shape:
    if _CELL_CACHE_MAX <= 0:
        return build_fn()
    cached = _CELL_CACHE.get(key)
    if cached is not None:
        _CELL_CACHE.move_to_end(key)
        return cached.copy()
    shape = build_fn()
    _CELL_CACHE[key] = shape
    _CELL_CACHE.move_to_end(key)
    while len(_CELL_CACHE) > _CELL_CACHE_MAX:
        _CELL_CACHE.popitem(last=False)
    return shape.copy()
