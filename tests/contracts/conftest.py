"""Shape extraction for contract snapshot tests.

`extract_shape` turns a real JSON response into a key+type skeleton.
The snapshot pins the skeleton, not the values, so:

  * adding/seeding more rows doesn't churn the snapshot,
  * removing a Pydantic field surfaces immediately,
  * changing a field's type surfaces immediately,
  * adding a new field surfaces immediately (and an intentional
    addition is reviewed as a snapshot diff before merge).

Lists collapse to `[<shape of first element>]` — public list endpoints
return homogeneous arrays by contract. Empty lists snapshot as `[]`,
so test fixtures must seed at least one row to anchor the shape.
"""

from __future__ import annotations

from typing import Any

_MAX_DEPTH = 8


def extract_shape(obj: Any, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        return "<truncated>"
    if obj is None:
        return "None"
    if isinstance(obj, dict):
        return {k: extract_shape(obj[k], depth + 1) for k in sorted(obj)}
    if isinstance(obj, list):
        if not obj:
            return []
        return [extract_shape(obj[0], depth + 1)]
    if isinstance(obj, bool):
        # bool must come before int — bool is an int subclass in Python.
        return "bool"
    return type(obj).__name__
