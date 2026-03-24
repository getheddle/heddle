"""Lightweight session registry for MCP session tools.

File-based session markers in ``~/.loom/sessions/``.  Compatible with
``baft.sessions`` — both read/write the same marker files.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_SESSION_DIR = Path("~/.loom/sessions").expanduser()
_STALE_THRESHOLD = 1800  # 30 minutes


def get_active_sessions() -> list[dict[str, Any]]:
    """Return active session dicts (non-stale markers)."""
    if not _SESSION_DIR.exists():
        return []

    now = time.time()
    active: list[dict[str, Any]] = []
    for marker in _SESSION_DIR.glob("*.json"):
        try:
            data = json.loads(marker.read_text())
            if now - data.get("last_active", 0) <= _STALE_THRESHOLD:
                active.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    return active


def register_session(session_id: str, **kwargs: Any) -> None:
    """Write or update a session marker."""
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    marker = {"session_id": session_id, "last_active": time.time(), **kwargs}
    (_SESSION_DIR / f"{session_id}.json").write_text(json.dumps(marker))


def unregister_session(session_id: str) -> None:
    """Remove a session marker."""
    (_SESSION_DIR / f"{session_id}.json").unlink(missing_ok=True)
