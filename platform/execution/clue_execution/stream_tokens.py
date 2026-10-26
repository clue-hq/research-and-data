"""Single-use SSE ``stream_token`` store (PB-B4 slice 3; subject-bound since Part II D7).

The SSE endpoints (``GET …/events``) are opened with a one-shot token a consumer mints first. The
token authorises *opening* a stream exactly once: :func:`consume_stream_token` stamps ``used_at``
atomically (``… WHERE used_at IS NULL AND expires_at > now() RETURNING``), so a second presentation
finds no live row and is refused. A reconnect re-mints (the ``Last-Event-ID`` cursor carries replay
state across connects independently of the token, so single-use never breaks gapless reconnect —
the client just mints a fresh token per connect).

**Subject-bound.** A token used to be bound to a *project run*; it is now bound to a **stream
subject** — ``(subject_kind, subject_id)`` — so a design leg's stream is covered by the one auth
model rather than a second token species. The three legal shapes are pinned by the
``stream_token_subject_coherent`` CHECK: workspace-wide (all three subject columns NULL), a
project-run subject (``subject_id = run_id::text``), or any other kind (``run_id IS NULL``). The
project-run surface is unchanged for its callers — pass ``run_id=`` exactly as before.

**Why this module lives in ``clue_execution`` (the D7 Round-B relocation).** It was born in
``clue_api`` because minting/consuming are *writes* and the read-only ``clue_projections`` package
could not own them. That reasoning still holds — but D7 gives the token store a second caller, the
design API (``lumen_api``), which by Rule 5 may not import ``clue_api`` at all. Rather than mint a
second design-specific token species (the exact duplication D7 exists to unpick), the DAL moved
here, beside :mod:`clue_execution.run_events` — the other half of the same one-transport,
one-auth-model seam, and a package both composition roots may import. ``clue_api.stream_tokens``
re-exports it, so every pre-D7 import path still resolves.

Tenant-scoped: a token is consumable only in the ``workspace_id`` it was minted for. The design
stream has no workspace to assert (its consumer cannot send a header — see
:func:`consume_subject_stream_token`), so it derives the tenant *from* the token row instead.

**The turn scope (FI Lane D D3, relocated here at the frontend×design integration merge).** The
chat turn stream's token pair (:func:`mint_turn_stream_token` / :func:`consume_turn_stream_token`)
was born in ``clue_api.stream_tokens`` on the frontend-integration line while D7 was relocating the
DAL here on the design line; the merge keeps ONE owner by moving the pair here unchanged. Its scope
rides the ``turn_id`` column (migration ``98a5ddafa21b``), not the D7 subject pair — the subject
vocabulary CHECK (``stream_token_subject_kind_known``) does not yet know an agent-turn kind.
Unifying the two scope vocabularies is recorded follow-up work; until then the ``turn_id IS NULL``
guard in the subject consume keeps the species disjoint.

**Retention (Part II D8, ruling R-D8-4).** Both consume statements above require
``used_at IS NULL AND expires_at > now()``, so a row that is *used* or *expired* is provably
unreadable by every code path in the repository — deleting it changes no observable behaviour, only
the table's size. Until D8 nothing deleted them and rows accumulated at the editor's reconnect rate
forever (a design stream mints one token per connect, and its TTL is 60s).
:func:`sweep_stream_tokens` is that deletion, run on a cadence by the fleet worker. It is **on by
default** precisely because it is unobservable: there is no state to lose and no consumer to
surprise.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId

#: Mirrors ``run_event.subject_kind``'s taxonomy (D7). A token's subject and the stream's subject
#: are the same vocabulary by construction — that is what makes "one auth model" true.
PROJECT_RUN_SUBJECT_KIND = "project_run"
#: A chat thread's live stream of turn lifecycle frames (CRM trial 1, F2): any turn in the thread,
#: so an open chat follows turns it did not start.
AGENT_THREAD_SUBJECT_KIND = "agent_thread"

_MINT_SQL = text(
    """
    INSERT INTO stream_token (workspace_id, subject_kind, subject_id, run_id, expires_at)
    VALUES (
        :workspace_id, :subject_kind, :subject_id, :run_id,
        now() + make_interval(secs => :ttl_s)
    )
    RETURNING token
    """
)

# Single-use consume: stamp used_at atomically only for a live, unused, unexpired, same-tenant,
# same-SUBJECT row. A second use (used_at already set), an expired token, a cross-tenant token, or a
# token minted for a DIFFERENT subject returns no row (subject-bound: a subject-scoped token opens
# only the stream it was minted for; a NULL-subject token is workspace-wide by design).
# ``turn_id IS NULL``: a turn-scoped token (FI Lane D D3 — its scope rides the ``turn_id`` column,
# not the subject pair; see the module docstring) is shaped like a workspace-wide row on the
# subject columns, and without this predicate it would open any subject stream in its tenant.
_CONSUME_SQL = text(
    """
    UPDATE stream_token
    SET used_at = now()
    WHERE token = :token
      AND workspace_id = :workspace_id
      AND used_at IS NULL
      AND expires_at > now()
      AND turn_id IS NULL
      AND (
        subject_kind IS NULL
        OR (subject_kind = :subject_kind AND subject_id = :subject_id)
      )
    RETURNING token
    """
)

# The workspace-deriving variant (D7). Same single-use CAS, same subject binding — but the tenant is
# an OUTPUT, not a predicate, so a caller who cannot name its workspace (the design editor's stream:
# no header, and D7 removed the ``?workspace_id=`` carrier) still gets a fail-closed answer. The
# subject IS required here: without it a stolen token would open any stream in its tenant, and a
# NULL-subject (workspace-wide) token deliberately does NOT match — a token that names no subject
# cannot be used to derive authority over a specific one.
_CONSUME_FOR_SUBJECT_SQL = text(
    """
    UPDATE stream_token
    SET used_at = now()
    WHERE token = :token
      AND used_at IS NULL
      AND expires_at > now()
      AND subject_kind = :subject_kind
      AND subject_id = :subject_id
    RETURNING workspace_id
    """
)


#: The FI Lane D D3 turn-stream pair. Same table, same single-use semantics, a **different scope
#: column** (migration ``98a5ddafa21b`` adds ``turn_id`` plus a CHECK that at most one of
#: ``run_id``/``turn_id`` is set). A turn row carries NULL subject columns, which the D7 coherence
#: CHECK reads as the workspace-wide shape — the ``turn_id IS NULL`` guard in ``_CONSUME_SQL`` is
#: what keeps the two scope vocabularies from leaking into each other. Folding the turn scope into
#: the subject taxonomy proper (``subject_kind = 'agent_turn'``) needs a vocabulary-CHECK migration
#: and is deliberately post-merge follow-up work, not done here.
_MINT_TURN_SQL = text(
    """
    INSERT INTO stream_token (workspace_id, turn_id, expires_at)
    VALUES (:workspace_id, :turn_id, now() + make_interval(secs => :ttl_s))
    RETURNING token
    """
)

_CONSUME_TURN_SQL = text(
    """
    UPDATE stream_token
    SET used_at = now()
    WHERE token = :token
      AND workspace_id = :workspace_id
      AND used_at IS NULL
      AND expires_at > now()
      AND turn_id = :turn_id
    RETURNING token
    """
)


#: Grace applied to BOTH halves of the sweep predicate before a row is considered dead. Nothing
#: correctness-critical rides on it — a used or expired row is already unreadable — but a small
#: window keeps the sweep away from rows a request is mid-flight on, and keeps the deletion honest
#: under modest clock skew between the app's ``now()`` and the row's stamps (both are the DB's own
#: clock today, so the real margin is the transaction, not the machine).
DEFAULT_SWEEP_GRACE_S = 3600.0

# Deletes exactly the rows :func:`consume_stream_token` / :func:`consume_subject_stream_token`
# can never return: ``expires_at`` in the past, or ``used_at`` already stamped. Written as two
# range predicates rather than ``used_at IS NOT NULL`` so the planner can BitmapOr the two indexes
# the D8 migration adds (``stream_token_expires_at`` and the partial ``stream_token_used_at``)
# instead of sequentially scanning the table.
_SWEEP_SQL = text(
    """
    DELETE FROM stream_token
    WHERE expires_at < now() - make_interval(secs => :grace_s)
       OR used_at    < now() - make_interval(secs => :grace_s)
    """
)


def _subject(
    run_id: ProjectRunId | None, subject_kind: str | None, subject_id: str | None
) -> tuple[str | None, str | None]:
    """Resolve the two ways of naming a stream subject into the pair the table stores.

    ``run_id=`` is the pre-D7 project-run form and is translated here, so no call site has to know
    the subject columns exist. Naming a subject *both* ways is refused rather than reconciled: the
    two could disagree, and a token silently bound to the subject the caller did not mean is an
    authorisation bug, not a formatting one."""
    if run_id is not None and (subject_kind is not None or subject_id is not None):
        raise ValueError("name the stream subject with run_id OR subject_kind/subject_id, not both")
    if run_id is not None:
        return PROJECT_RUN_SUBJECT_KIND, str(run_id)
    if (subject_kind is None) != (subject_id is None):
        raise ValueError("subject_kind and subject_id must be given together")
    return subject_kind, subject_id


async def mint_stream_token(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    run_id: ProjectRunId | None = None,
    subject_kind: str | None = None,
    subject_id: str | None = None,
    ttl_s: float,
) -> UUID:
    """Mint a single-use stream token for ``workspace_id``, optionally bound to one stream subject
    (``run_id=`` for a project run, ``subject_kind=``/``subject_id=`` for any other kind, neither
    for a workspace-wide token), expiring ``ttl_s`` seconds from now. Returns the opaque token the
    consumer presents to open a stream."""
    kind, sid = _subject(run_id, subject_kind, subject_id)
    token = (
        await conn.execute(
            _MINT_SQL,
            {
                "workspace_id": workspace_id,
                "subject_kind": kind,
                "subject_id": sid,
                "run_id": run_id,
                "ttl_s": ttl_s,
            },
        )
    ).scalar_one()
    return UUID(str(token))


async def consume_stream_token(
    conn: AsyncConnection,
    *,
    token: UUID,
    workspace_id: str,
    run_id: ProjectRunId | None = None,
    subject_kind: str | None = None,
    subject_id: str | None = None,
) -> bool:
    """Atomically consume ``token`` for ``workspace_id`` on the named subject's stream: ``True`` iff
    live (unused, unexpired, this tenant's, and minted for this subject — or minted
    subject-unscoped) — stamping ``used_at`` so a second use is refused. ``False`` for a used /
    expired / cross-tenant / wrong-subject / unknown token (indistinguishable — no existence
    leak)."""
    kind, sid = _subject(run_id, subject_kind, subject_id)
    row = (
        await conn.execute(
            _CONSUME_SQL,
            {
                "token": token,
                "workspace_id": workspace_id,
                "subject_kind": kind,
                "subject_id": sid,
            },
        )
    ).one_or_none()
    return row is not None


async def mint_turn_stream_token(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    turn_id: UUID,
    ttl_s: float,
) -> UUID:
    """Mint a single-use token that opens **one turn's** stream, once, within ``ttl_s``.

    Lane B contract §5.5 in one function: an already-authenticated request mints a short-lived,
    single-use, principal-scoped, workspace-scoped, turn-scoped token; no bearer credential ever
    travels in a URL, and the token's expiry or replay cannot extend anybody's domain authority —
    it authorises *opening a stream*, and the stream serves only rows of the workspace and turn the
    token names.
    """

    token = (
        await conn.execute(
            _MINT_TURN_SQL,
            {"workspace_id": workspace_id, "turn_id": turn_id, "ttl_s": ttl_s},
        )
    ).scalar_one()
    return UUID(str(token))


async def consume_turn_stream_token(
    conn: AsyncConnection, *, token: UUID, workspace_id: str, turn_id: UUID
) -> bool:
    """Atomically consume a turn-stream token: ``True`` iff live, this tenant's, and this turn's.

    ``False`` — indistinguishably — for a used, expired, cross-tenant, wrong-turn, run-scoped, or
    unknown token, so a probe learns nothing about which of those it was. Reconnect re-mints; the
    ``Last-Event-ID`` cursor carries replay state independently, so single-use never costs a
    gapless reconnect.
    """

    row = (
        await conn.execute(
            _CONSUME_TURN_SQL,
            {"token": token, "workspace_id": workspace_id, "turn_id": turn_id},
        )
    ).one_or_none()
    return row is not None


async def consume_subject_stream_token(
    conn: AsyncConnection,
    *,
    token: UUID,
    subject_kind: str,
    subject_id: str,
) -> str | None:
    """Consume ``token`` for one subject's stream and return the workspace it was minted for.

    The same single-use CAS as :func:`consume_stream_token`, with the tenant as the RESULT rather
    than a predicate — for the consumer that cannot state its workspace. The browser's streaming
    client is exactly that consumer: D7 removed the design stream's ``?workspace_id=`` carrier
    (a query parameter is a claim, not a credential), so the token *is* the tenant statement and
    the workspace is read off the row the mint route wrote under a header-authenticated request.

    ``None`` for a used / expired / wrong-subject / unknown token — the four are indistinguishable
    on purpose, and a workspace-wide (NULL-subject) token does not match at all.
    """
    row = (
        await conn.execute(
            _CONSUME_FOR_SUBJECT_SQL,
            {"token": token, "subject_kind": subject_kind, "subject_id": subject_id},
        )
    ).one_or_none()
    return None if row is None else str(row[0])


async def sweep_stream_tokens(
    conn: AsyncConnection, *, grace_s: float = DEFAULT_SWEEP_GRACE_S
) -> int:
    """Delete every spent token — used or expired, older than ``grace_s`` — and return how many.

    **Semantically free.** A row this removes cannot be consumed by any code path: both consume
    statements in this module require ``used_at IS NULL AND expires_at > now()``, so the deletion is
    unobservable at the API surface. An already-consumed token is refused *identically* whether its
    row is still present (``used_at`` set) or has been swept (no row at all) — the consume returns
    ``False``/``None`` either way, which is the same answer it deliberately gives for an unknown
    token (no existence leak).

    Idempotent and cheap: re-running it immediately deletes nothing. Tenant-unscoped on purpose —
    it is a substrate reclaim, not a tenant read, and a per-workspace sweep would leave every
    workspace nobody happens to name growing forever.
    """
    return int((await conn.execute(_SWEEP_SQL, {"grace_s": grace_s})).rowcount)
