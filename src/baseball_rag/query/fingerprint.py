"""Order-independent fingerprints for complete published source rows."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Iterable

_MODULUS = 1 << 256


class RowFingerprint:
    """Streaming multiset fingerprint over typed, ordered row values."""

    def __init__(self) -> None:
        self._count = 0
        self._sum = 0
        self._xor = 0

    def add(self, values: Iterable[object]) -> None:
        encoded = json.dumps(
            [_scalar(value) for value in values],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        value = int.from_bytes(hashlib.sha256(encoded).digest())
        self._count += 1
        self._sum = (self._sum + value) % _MODULUS
        self._xor ^= value

    def hexdigest(self) -> str:
        summary = f"{self._count}:{self._sum:064x}:{self._xor:064x}".encode()
        return hashlib.sha256(summary).hexdigest()


def _scalar(value: object) -> str | int | float | bool | None:
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"Cannot fingerprint scalar type {type(value).__name__!r}.")
