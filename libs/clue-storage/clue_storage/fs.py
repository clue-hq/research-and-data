"""Filesystem :class:`~clue_storage.protocol.StorageBackend` — the default/dev backend (B2.1).

Blobs live at ``root/<key>`` (the key's ``{scope}/{sha256}`` shape becomes one directory level).
Writes are atomic (tmp file + ``os.replace``) so a crashed ``put`` can never leave a torn blob a
reader mistakes for the content its hash names. ``presign`` returns a ``file://`` URI — a
documented placeholder until the frontend-serving phase consumes presigning (PB-B2 scope note).

File I/O here is small, local, and rare (one snapshot per paid fetch), so the async methods wrap
plain blocking calls rather than a thread pool — the same stance the repo takes elsewhere for
local-disk work; the S3 impl is where real network latency lives (and it is truly async).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath

from clue_storage.protocol import ArtifactNotFound, StorageError


class FsStorage:
    """Store blobs under ``root`` on the local filesystem."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        """Resolve ``key`` under the root, refusing traversal outside it (a key is data, and a
        crafted ``../`` key must not escape the store)."""
        pure = PurePosixPath(key)
        if pure.is_absolute() or ".." in pure.parts:
            raise StorageError(f"invalid storage key {key!r}")
        return self._root.joinpath(*pure.parts)

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic: write a sibling tmp file, then replace — a reader never sees a torn blob.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".put-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, path)
        except OSError as exc:
            raise StorageError(f"could not store {key!r}: {exc}") from exc
        finally:
            if os.path.exists(tmp):  # replace failed — don't leave the tmp behind
                os.unlink(tmp)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactNotFound(f"no artifact stored under {key!r}") from exc
        except OSError as exc:
            raise StorageError(f"could not read {key!r}: {exc}") from exc

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)  # idempotent — DSAR erasure is safe to retry

    async def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        # ``file://`` placeholder (no expiry semantics on a local path); the frontend-serving
        # phase swaps in a real signed URL. Raises if the key is absent, matching S3 semantics
        # closely enough for the contract suite.
        path = self._path(key)
        if not path.is_file():
            raise ArtifactNotFound(f"no artifact stored under {key!r}")
        return path.resolve().as_uri()
