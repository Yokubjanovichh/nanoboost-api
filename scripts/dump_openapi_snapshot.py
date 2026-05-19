"""Write the current OpenAPI schema to docs/openapi-snapshot.json.

Deterministic output: `sort_keys=True`, two-space indent, trailing
newline. The CI guard in `.github/workflows/ci.yml` diffs the
committed snapshot against a fresh render — any endpoint or schema
change that isn't reflected in the snapshot fails the build.

Run after any change that touches routes, schemas, or response_model:

    python -m scripts.dump_openapi_snapshot
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make sure the app config is happy before import.
import os

os.environ.setdefault("JWT_SECRET_KEY", "snapshot-only-dummy-jwt-secret-key-32+chars")

from app.main import app  # noqa: E402

SNAPSHOT = Path(__file__).resolve().parent.parent / "docs" / "openapi-snapshot.json"


def render() -> str:
    schema = app.openapi()
    return json.dumps(schema, sort_keys=True, indent=2) + "\n"


def main() -> int:
    rendered = render()
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {SNAPSHOT.relative_to(Path.cwd())} ({len(rendered):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
