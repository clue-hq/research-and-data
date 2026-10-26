"""Remove the agent-workspace layout from before F3, once every chat has moved (spec WS-22).

Before F3 every worker wrote chats straight under the workspace root:
``<root>/<workspace>/library/...`` and ``<root>/<workspace>/projects/<project>/{library,attachments,
pinned-*,threads/<thread>}``. Since F3 each worker writes only inside its own area
(``<root>/workers/area-<n>/``) or, with snapshots switched off, ``<root>/local/``. A chat from
before F3 takes its files from its old folder on its first turn and the old folder is deleted then;
this script removes whatever is left of the old layout once it has not been touched for a while.

Dry run by default: it lists each old workspace folder, whether it is old enough to remove, and
its size. ``--apply`` removes the old-enough ones. It never touches ``workers/`` or ``local/``,
so it also keeps ``workers/local.lock``, the lock every snapshots-off worker holds on ``local/``
(deleting it under a live one would let a snapshots-on worker remove that worker's files).

Usage::

    uv run python scripts/remove_legacy_agent_workspaces.py --root /srv/clue/workspaces
    uv run python scripts/remove_legacy_agent_workspaces.py --root /srv/clue/workspaces --apply
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import time
from pathlib import Path

#: The folders F3 owns under the root; everything else at the top level is the old layout.
_KEEP = frozenset({"workers", "local"})


def _newest_mtime(folder: Path) -> float:
    newest = folder.lstat().st_mtime
    for directory, dirs, files in os.walk(folder):
        for name in (*dirs, *files):
            newest = max(newest, os.lstat(os.path.join(directory, name)).st_mtime)
    return newest


def _size(folder: Path) -> int:
    total = 0
    for directory, _, files in os.walk(folder):
        for name in files:
            metadata = os.lstat(os.path.join(directory, name))
            if stat.S_ISREG(metadata.st_mode):
                total += metadata.st_size
    return total


def _remove(folder: Path) -> None:
    for directory, _, _ in os.walk(folder):
        os.chmod(directory, 0o700)
    shutil.rmtree(folder)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", required=True, help="CLUE_AGENT_WORKSPACE_ROOT")
    parser.add_argument("--older-than-hours", type=float, default=48.0)
    parser.add_argument("--apply", action="store_true", help="remove; without it, only list")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path()
    if not args.root or root == Path("/") or not root.is_dir():
        print(f"refused: {args.root!r} is not a workspace root", file=sys.stderr)
        return 2
    cutoff = time.time() - args.older_than_hours * 3600
    mode = "apply" if args.apply else "dry run"
    print(
        f"{mode}: old agent-workspace layout under {root} untouched for {args.older_than_hours:g} h"
    )
    removed = kept = 0
    for entry in sorted(root.iterdir()):
        if entry.name in _KEEP or entry.name.startswith(".") or entry.is_symlink():
            continue
        if not entry.is_dir():
            continue
        old_enough = _newest_mtime(entry) < cutoff
        size = _size(entry)
        verdict = "remove" if old_enough else "keep (used recently)"
        print(f"  {entry.name}: {size} bytes — {verdict}")
        if old_enough and args.apply:
            _remove(entry)
            removed += 1
        elif not old_enough:
            kept += 1
    print(f"{mode}: {removed} removed, {kept} kept")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
