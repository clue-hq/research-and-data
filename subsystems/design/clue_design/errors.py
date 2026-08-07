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
