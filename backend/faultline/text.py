"""Plain-English helpers for text people read (stage notes, reasons, reports): counts with the right plural and lists
joined with commas, never "(s)" or a Python list."""

from __future__ import annotations

from collections.abc import Iterable

_IRREGULAR = {"person": "people", "family": "families", "policy": "policies", "query": "queries"}


def plural(n: int | float, word: str, many: str | None = None) -> str:
    """'1 incident', '2 incidents', '1 person', '3 people'."""
    one = abs(n) == 1
    return f"{n:g} {word if one else (many or _IRREGULAR.get(word) or (word + 'es' if word.endswith(('s', 'sh', 'ch', 'x')) else word + 's'))}"


def joined(items: Iterable[object], empty: str = "none") -> str:
    """'a, b, c' (or `empty` when there is nothing)."""
    xs = [str(x) for x in items]
    return ", ".join(xs) if xs else empty


__all__ = ["joined", "plural"]
