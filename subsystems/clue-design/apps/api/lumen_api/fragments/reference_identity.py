"""Exact fetch identity plus a separately preserved in-resource URL fragment.

Only HTTP(S) and relative references have fragment aliases here. Other schemes, including
asset://, still require an exact explicit custody entry. No query or URL spelling is normalized.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from urllib.parse import urlsplit


class ReferenceConflict(ValueError):
    """Aliases of one fetch identity name different held content; choosing would guess."""


def _resource_key(reference: str) -> str:
    if not reference or reference.startswith("#"):
        return reference
    try:
        scheme = urlsplit(reference).scheme.lower()
    except ValueError:
        return reference  # Malformed spellings gain no aliases.
    if scheme not in ("", "http", "https"):
        return reference
    return reference.partition("#")[0]


class ReferenceIndex[T](Mapping[str, T]):
    """One immutable map view with O(1) alias lookup and one content check per alias group.

    The optional identity callback returns held bytes/digests, never a fresh hash of a video.
    Copy only the mapping; payload objects are neither copied nor modified.
    """

    def __init__(self, values: Mapping[str, T], *, identity: Callable[[T], object] | None = None):
        self._values = dict(values)
        self._identity = identity or (lambda value: value)
        self._groups: dict[str, list[str]] = {}
        self._consistent: dict[str, bool] = {}
        for key in self._values:
            self._groups.setdefault(_resource_key(key), []).append(key)
        self._fallbacks = {resource: min(keys) for resource, keys in self._groups.items()}

    def __getitem__(self, key: str) -> T:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def lookup_key(self, reference: str) -> str | None:
        resource = _resource_key(reference)
        keys = self._groups.get(resource)
        if not keys:
            return None
        if resource not in self._consistent:
            first = self._identity(self._values[keys[0]])
            self._consistent[resource] = all(
                self._identity(self._values[key]) == first for key in keys[1:]
            )
        if not self._consistent[resource]:
            raise ReferenceConflict(f"conflicting captured content for {reference}")
        if reference in self._values:
            return reference
        if resource in self._values:
            return resource
        return self._fallbacks[resource]


def indexed_references[T](values: Mapping[str, T]) -> ReferenceIndex[T]:
    """Reuse a pass's index instead of rebuilding it for each HTML/CSS reference."""
    return values if isinstance(values, ReferenceIndex) else ReferenceIndex(values)


def lookup_reference_key[T](reference: str, values: Mapping[str, T]) -> str | None:
    return indexed_references(values).lookup_key(reference)
