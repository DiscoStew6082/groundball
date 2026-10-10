"""Resource bounds for already-materialized external JSON values.

Check each collection's size before iterating it. Iterative traversal also bounds
cycles, depth and total work before any copying or JSON serialization.
"""

from __future__ import annotations

import json
import math
from typing import Any

MAX_ITEMS = 128
MAX_FIELDS = 64
MAX_NODES = 4096
MAX_STRING_BYTES = 4096


def validate_envelope(value: Any, *, max_bytes: int, max_depth: int) -> None:
    pending = [(value, 0)]
    nodes = size = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > MAX_NODES or depth > max_depth:
            raise ValueError("External JSON structure is too large or deep.")
        if type(item) is dict:
            if len(item) > MAX_FIELDS:
                raise ValueError("External JSON object has too many fields.")
            size += 2 + 2 * len(item)
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("External JSON keys must be strings.")
                pending.append((key, depth + 1))
                pending.append((child, depth + 1))
        elif type(item) is list:
            if len(item) > MAX_ITEMS:
                raise ValueError("External JSON array has too many items.")
            size += 2 + len(item)
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            if len(item) > MAX_STRING_BYTES:
                raise ValueError("External JSON string is too large.")
            encoded = item.encode("utf-8")
            if len(encoded) > MAX_STRING_BYTES:
                raise ValueError("External JSON string is too large.")
            size += len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        elif item is None or type(item) is bool:
            size += 5
        elif type(item) is int:
            if item.bit_length() > 256:
                raise ValueError("External JSON integer is too large.")
            size += len(str(item))
        elif type(item) is float and math.isfinite(item):
            size += len(str(item))
        else:
            raise ValueError("External envelope must contain finite JSON values.")
        if size > max_bytes:
            raise ValueError("External JSON envelope is too large.")
