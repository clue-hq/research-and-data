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


class DesignLegStateError(DesignStoreError):
    """A leg transition was attempted from the wrong state (PD-part3 §2.1).

    The leg state machine is engine-owned: close only from an open state, reopen only
    from ``closed``. A transition that finds the row elsewhere raises instead of silently
    no-oping — a mis-sequenced exit or double-close is a caller bug worth hearing about.
    """

    def __init__(self, leg_id: str, expected: str, action: str) -> None:
        super().__init__(f"design leg {leg_id}: cannot {action} (leg is not {expected})")
        self.leg_id = leg_id
        self.expected = expected
        self.action = action


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


class DesignRunFencedError(DesignStoreError):
    """A terminal write was refused: the run's lease generation is not the writer's (it moved
    past it, or the writer never claimed the run under it — the fence is equality since
    2026-10-16, when lease generations stopped repeating).

    Raised by the D5 terminal-write guard (``set_run_result`` under an ``expected_generation``)
    and, since D7, by the run's stream writer (``lumen_api.run_stream.fenced_emit``, which is what
    ``complete_run_and_emit`` and the progress sink go through). It names the ONE hazard the fleet
    switch introduces: the design turn body is synchronous and is executed under
    ``asyncio.to_thread``, so a worker that loses its lease can only stop *cooperatively* — it
    returns immediately, but the thread it abandoned keeps running and may still try to write a
    terminal result minutes later. That zombie must never overwrite the takeover worker's run.

    The refusal is loud (a typed error the handler logs) but not fatal to the caller: a fenced-out
    writer has by definition already been replaced, so the correct behaviour is to drop the write
    and stop, never to retry.

    This is the *design row's* fence. The authoritative platform fence remains the ``work_lease``
    row, and the `[B1×integration]` hard-fence-token residual still stands.
    """

    def __init__(
        self, run_id: str, expected_generation: int, current_generation: int | None
    ) -> None:
        super().__init__(
            f"design run {run_id} write refused: writer holds lease generation "
            f"{expected_generation}, row is at {current_generation}"
        )
        self.run_id = run_id
        self.expected_generation = expected_generation
        self.current_generation = current_generation


class DesignJobFencedError(DesignStoreError):
    """An ingestion-job write was refused: the job's lease generation moved past the writer's.

    The ingestion twin of :class:`DesignRunFencedError` (D5 Round C), and it exists for the same
    reason: the ingestion pipeline is a long synchronous function executed under
    ``asyncio.to_thread``, so a worker that loses its lease can only stop cooperatively. The
    abandoned thread keeps capturing/normalizing and may try to stamp progress or a terminal
    result long after a takeover worker re-claimed and re-ran the job.

    Kept a SEPARATE type rather than folded into ``DesignRunFencedError`` because the two name
    different rows with different identifiers (``run_id`` vs ``job_id``) and their handlers log
    different things; a caller that catches one must not silently swallow the other.
    """

    def __init__(
        self, job_id: str, expected_generation: int, current_generation: int | None
    ) -> None:
        super().__init__(
            f"design ingestion job {job_id} write refused: writer holds lease generation "
            f"{expected_generation}, row is at {current_generation}"
        )
        self.job_id = job_id
        self.expected_generation = expected_generation
        self.current_generation = current_generation


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


class DesignFragmentActivationError(DesignStoreError):
    """A dormant cloned section was asked to wake up, and it has nothing to be judged on.

    Founder ruling D-F8 (2026-08-28): a section the source site hides is preserved rather than
    dropped, is never released by the kit approval cascade, and is *activated only by a human* —
    with the standing condition that **activation requires a usable preview**. A dormant row with
    no ``preview_digest`` is therefore not activatable: approving a section nobody can see is not
    a human decision about a clone, it is a click on a name.

    Kept separate from the ``ValueError`` a bad status string gets, because the two are different
    conversations: one is a caller typo, this is a human being told "go and get a preview first",
    and a surface that renders them the same way would render the second one uselessly.
    """

    def __init__(self, fragment_id: str, reason: str, message: str) -> None:
        super().__init__(message)
        self.fragment_id = fragment_id
        self.reason = reason


class DesignFragmentPreviewError(DesignStoreError):
    """A preview was offered to a fragment that already has one (F3.2, ruling P-7).

    The mirror of :class:`DesignFragmentActivationError`, and deliberately its sibling rather
    than a ``ValueError``: both are refusals a HUMAN reads on the way to a decision about a
    cloned section, and both carry a ``reason`` code the surface renders rather than a sentence
    it has to parse.

    A preview is attached once. The row's ``preview_digest`` is part of the artifact's identity
    bytes, so replacing it would rewrite the picture somebody's activation or release decision was
    made against, while leaving the id — the content address of what was actually minted —
    unchanged. Re-picturing a section is minting a new one.
    """

    def __init__(self, fragment_id: str, reason: str, message: str) -> None:
        super().__init__(message)
        self.fragment_id = fragment_id
        self.reason = reason
