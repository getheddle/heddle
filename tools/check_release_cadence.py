#!/usr/bin/env python3
"""Enforce the release cadence in ``docs/RELEASING.md`` ("When to release").

A release comes at least 14 days after the previous release tag, unless
its CHANGELOG section carries an ``Urgent release: <reason>`` line.

Run locally before tagging (the version comes from ``pyproject.toml``)::

    uv run python tools/check_release_cadence.py

The publish workflow runs it for the tag being released::

    python tools/check_release_cadence.py --tag vX.Y.Z

Exit code 0 when the release may go out, 1 when it may not.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIN_DAYS = 14
URGENT_MARKER = "Urgent release:"


def changelog_section(changelog: str, version: str) -> str | None:
    """Return the body of ``## [version]`` up to the next ``## [`` heading."""
    match = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        changelog,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1) if match else None


def urgent_reason(section: str) -> str | None:
    """Return the text after ``Urgent release:``, or None if absent or empty."""
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith(URGENT_MARKER):
            reason = stripped[len(URGENT_MARKER) :].strip()
            return reason or None
    return None


def previous_release(
    tags: list[tuple[str, datetime]], tag: str, now: datetime
) -> tuple[str, datetime] | None:
    """The latest tag other than ``tag`` created at or before ``now``."""
    earlier = [(name, when) for name, when in tags if name != tag and when <= now]
    return max(earlier, key=lambda item: item[1], default=None)


def check(
    tag: str,
    tags: list[tuple[str, datetime]],
    changelog: str,
    now: datetime,
) -> tuple[bool, str]:
    """Decide whether ``tag`` may be released at ``now``; return (ok, message)."""
    previous = previous_release(tags, tag, now)
    if previous is None:
        return True, f"{tag}: no previous release tag"
    prev_name, prev_when = previous
    days = (now - prev_when).total_seconds() / 86400
    if days >= MIN_DAYS:
        return True, f"{tag}: {days:.1f} days after {prev_name}"
    section = changelog_section(changelog, tag.removeprefix("v"))
    reason = urgent_reason(section) if section is not None else None
    if reason:
        return True, f"{tag}: {days:.1f} days after {prev_name}; urgent: {reason}"
    return False, (
        f"{tag}: only {days:.1f} days after {prev_name} (minimum {MIN_DAYS}). "
        f"Wait, or, if this release is urgent, add an '{URGENT_MARKER} <reason>' "
        f"line to its CHANGELOG section (docs/RELEASING.md, 'Urgent releases')."
    )


def _git_tags() -> list[tuple[str, datetime]]:
    out = subprocess.run(
        [
            "git",
            "tag",
            "--list",
            "v*",
            "--format=%(refname:short) %(creatordate:iso-strict)",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tags = []
    for line in out.splitlines():
        name, _, when = line.partition(" ")
        tags.append((name, datetime.fromisoformat(when)))
    return tags


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", help="tag being released (default: v + pyproject.toml version)")
    args = parser.parse_args(argv)

    tag = args.tag
    if tag is None:
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
        tag = "v" + pyproject["project"]["version"]

    tags = _git_tags()
    # A tag that already exists is checked as of its own creation time.
    now = dict(tags).get(tag, datetime.now(UTC))
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text()

    ok, message = check(tag, tags, changelog, now)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
