"""Regenerate ``docs/tfex_official_sources.md`` from the source register.

Generated rather than hand-maintained so the document cannot drift away from the register
the code actually consults (`CLAUDE_TFEX.md` section 2).

Usage::

    uv run python scripts/render_official_sources.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tfex.provenance import OfficialSourceRegistry

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
DOC_PATH = REPO_ROOT / "docs" / "tfex_official_sources.md"
STATE_PATH = BACKEND_ROOT / "data" / "tfex" / "official_sources.json"


def main() -> int:
    registry = (
        OfficialSourceRegistry.load(STATE_PATH)
        if STATE_PATH.is_file()
        else OfficialSourceRegistry()
    )
    registry.save(STATE_PATH)

    DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOC_PATH.write_text(
        registry.render_markdown(generated_at=datetime.now(UTC)),
        encoding="utf-8",
    )

    unverified = registry.unverified()
    print(f"wrote {DOC_PATH}")
    print(f"wrote {STATE_PATH}")
    print(f"{len(registry)} sources, {len(unverified)} not yet verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
