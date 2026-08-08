"""Design-substrate DAL error taxonomy (Part II slice D2.1).

Typed, provider-free errors the design API maps to HTTP responses. The DAL raises these — it
never leaks SQLAlchemy/driver exceptions as its contract (an ``IntegrityError`` escaping a DAL
call is a bug in the caller's inputs surfacing structurally, per the tenancy laws; the DAL only
*translates* the cases callers are meant to handle).
"""

from __future__ import annotations


class DesignStoreError(Exception):
    """Base class for design-substrate persistence errors."""


class DesignNotFoundError(DesignStoreError):
    """The referenced row does not exist *in the caller's workspace*.

    Deliberately indistinguishable from "exists in another workspace" — the fail-closed
    scoping rule (the toolbelt's ``run_not_found`` precedent): a cross-tenant id resolves to
    the same refusal a truly-absent id gets, so existence never leaks across workspaces.
    """

    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"{kind} not found: {key}")
        self.kind = kind
        self.key = key


class DesignVersionConflictError(DesignStoreError):
    """A compare-and-set write lost: the row's current version is not the expected base.

    Raised by the document write paths (web docs today; scene docs gain the same CAS in D2.2 —
    the lost-update gap the SQLite port closes). Callers reload and retry or surface a 409.
    """

    def __init__(self, kind: str, key: str, expected_version: int, current_version: int) -> None:
        super().__init__(
            f"{kind} version conflict: {key} expected version {expected_version}, "
            f"is at {current_version}"
        )
        self.kind = kind
        self.key = key
        self.expected_version = expected_version
        self.current_version = current_version


class DesignArtifactConflictError(DesignStoreError):
    """A content-addressed id was re-used with different stored content.

    The custom-component registry is immutable and content-addressed (``ccart_<sha256>``,
    ``webpub_<package digest>``): an exact retry is idempotent, but the same id carrying
    *different* metadata is a hard conflict rather than an overwrite — the row cannot be updated
    at all (the D1e no-UPDATE triggers), so surfacing the collision is the only honest outcome.
    """

    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"{kind} {key} already exists with different content")
        self.kind = kind
        self.key = key


class DesignSourceVersionConflictError(DesignStoreError):
    """A component source write lost its compare-and-set race on ``source_version``.

    Distinct from :class:`DesignVersionConflictError` (documents): this is the custom-component
    source lineage's CAS, whose key is the component slug rather than a document id.
    """

    def __init__(self, slug: str, expected_version: int, current_version: int) -> None:
        super().__init__(
            f"custom component {slug} expected source version {expected_version}, "
            f"current version is {current_version}"
        )
        self.slug = slug
        self.expected_version = expected_version
        self.current_version = current_version
