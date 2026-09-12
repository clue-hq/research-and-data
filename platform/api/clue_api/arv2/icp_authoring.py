"""Authoring an ICP: the agent writes the document, the platform owns what the document *is*.

``icp_confirmation`` mints the *confirmed* version of a document a human said yes to. This module
is the step before that one: the Head of ABM, having read the brand's knowledge files, drafts an
ICP and stores it as a **proposed** version — either a new brand-level profile, or a project-local
variant with its own key and a ``derived_from`` naming the brand profile it adapts (founder
rulings 2026-09-10: a variant is a full document, not a patch).

The split of authority is the whole point. The model authors *content* — the hard gates, the
exclusions, the persona map, the qualifier fields, the prose. The platform authors *identity*:

* **status** is always ``proposed``. Writing a file confirms nothing; the human's yes is the ICP
  confirmation gate, and only that gate mints a ``confirmed`` version.
* **scope** is the caller's, never the front matter's — ``brand`` writes an unscoped row, and
  ``project`` writes a row owned by the presenting turn's project.
* **lineage** is resolved from a brand document that exists, or it is absent. A ``derived_from``
  the model typed is dropped; a ``derived_from_icp_key`` that names nothing is refused.
* **authorship** is the turn and the human on it, stamped into the front matter.

``produced_by_turn_id`` stays NULL on the row for the reason ``confirm_icp_document`` gives: the
turn's ``agent_turn`` row does not exist yet while the turn is running, so the FK could not be
satisfied. The front matter's ``authored_by`` carries the same fact durably.

Everything is written inside **one scope's** version chain: the next version, the row it
supersedes and the rows it retires are all read and written with
``project_id IS NOT DISTINCT FROM``, so a project's variant and the brand's document at the same
path are two histories that never interleave — exactly what the scoped unique index allows. A
``confirmed`` row is never retired: it is some project's pinned ICP, and a new proposal stands
beside it until a human moves the pin.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.icp_confirmation import (
    ICP_ARTIFACT_MEDIA_TYPE,
    ICP_KIND,
    current_icp_document,
)
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.onboarding_documents import KnowledgeDocument, render_markdown
from clue_db import ConnFactory, transaction
from clue_storage import StorageBackend, artifact_key, content_address, record_artifact

__all__ = [
    "ICP_AUTHORING_SOURCE_KEY",
    "ICP_KEY_PATTERN",
    "AuthoredIcp",
    "DbIcpAuthoringService",
    "IcpAuthoringRefused",
    "IcpAuthoringRequest",
    "IcpAuthoringService",
    "author_icp_document",
    "authored_document_id",
]

#: An ICP key is a path segment and a file name, so it is lowercase kebab-case and nothing else.
#: Anything looser would let one ICP have several spellings — and the key is how a human, a gate,
#: a pin and a launch all name the same document.
ICP_KEY_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
#: A key also has to stay a readable file name; the column is unbounded, the contract is not.
ICP_KEY_MAX_LENGTH = 60
#: What the authored version's artifact row records as its origin.
ICP_AUTHORING_SOURCE_KEY = "arv2-icp-authoring"
#: Every ICP document lives in the ``audience`` folder, under the name the whole lane reads by.
ICP_FOLDER = "audience"

_AUTHORING_NAMESPACE = "arv2-icp-authoring"
_KEY_RE = re.compile(ICP_KEY_PATTERN)

#: A document is servable — it owns its key — while its bytes exist and it has not been superseded.
#: Restated here rather than imported for the reason ``icp_confirmation`` restates it:
#: ``clue_api.arv2`` may not import ``clue_api`` modules outside the lane (Global Constraint 7).
_SERVABLE_STATUSES: tuple[str, ...] = ("ready", "proposed", "confirmed")
#: What a new version retires. ``confirmed`` is deliberately absent — a human's yes is some
#: project's pinned ICP, and a proposal must never retire it (the rule re-synthesis already holds).
_RETIRABLE_STATUSES: tuple[str, ...] = ("ready", "proposed")

#: Where each scope's documents materialize in the agent's workspace. Both prefixes are restated
#: here for the Global Constraint 7 reason above; they are
#: ``brand_knowledge_context.INPUT_PREFIX`` and ``project_context_files.PROJECT_INPUT_PREFIX``.
_BRAND_INPUT_PREFIX = "inputs/brand/knowledge/"
_PROJECT_INPUT_PREFIX = "inputs/project/"

#: Front-matter keys the platform owns. A model that typed any of them is not believed: a draft
#: cannot confirm itself, scope itself, or claim a lineage. They are removed, then re-stamped
#: from the request and the rows this module resolved.
_PLATFORM_OWNED_KEYS: tuple[str, ...] = (
    "confirmed_by",
    "confirmed_at",
    "confirmed_for_project_id",
    "product_selection_version",
    "user_edit",
    "derived_from",
    "project_id",
    "brand_id",
    "status",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IcpAuthoringRefused(Exception):
    """This document cannot be stored, and the agent is told exactly why.

    Every refusal is something the author can fix in its next turn — a key that is not a key, front
    matter that is not an ICP's, a key another scope already owns, a lineage that names nothing.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class IcpAuthoringRequest:
    """One authoring act. Scope, tenancy and authorship are ambient; the document is the model's."""

    workspace_id: str
    brand_id: str
    #: The presenting turn's project. It is the *scope* for ``scope="project"`` and, either way,
    #: the coordinate the brand was derived from — so a brand-level write is still tenant-anchored.
    project_id: str
    turn_id: UUID
    user_id: str
    icp_key: str
    document_text: str
    scope: Literal["brand", "project"]
    derived_from_icp_key: str | None


@dataclass(frozen=True, slots=True)
class AuthoredIcp:
    """The version this act stored, named precisely enough for the agent to open and present it."""

    document_id: UUID
    icp_key: str
    version: int
    path: str
    #: Where the document is readable in the agent's workspace — the brand's knowledge prefix for a
    #: brand profile, the project's for a variant.
    workspace_path: str
    status: str
    replayed: bool


def authored_document_id(*, turn_id: UUID, scope: str, icp_key: str) -> UUID:
    """The one id this turn's authoring of this key in this scope will ever have.

    Derived rather than minted so a retried tool call finds its own row instead of publishing a
    second version of the same draft. The turn is in the key because a *later* turn authoring the
    same key is a genuinely new version, which is exactly what the version chain is for.
    """

    return uuid5(NAMESPACE_URL, f"{_AUTHORING_NAMESPACE}:{turn_id}:{scope}:{icp_key}")


def _path_for(icp_key: str) -> str:
    return f"{ICP_FOLDER}/icp-{icp_key}.md"


def _workspace_path(path: str, *, project_scoped: bool) -> str:
    if not project_scoped:
        return _BRAND_INPUT_PREFIX + path
    # ``project_context_files.project_workspace_path``: one leading ``project/`` segment is the
    # folder name, not a directory under the prefix. An ICP is in ``audience/``, so nothing is
    # stripped here — the rule is restated so the two surfaces name one document identically.
    return _PROJECT_INPUT_PREFIX + path.removeprefix("project/")


def _validate_key(icp_key: str) -> None:
    if _KEY_RE.fullmatch(icp_key) is None or len(icp_key) > ICP_KEY_MAX_LENGTH:
        raise IcpAuthoringRefused(
            "icp_key_invalid",
            "icp_key must be lowercase kebab-case (letters, digits and single hyphens), at most "
            f"{ICP_KEY_MAX_LENGTH} characters",
        )


def _validate_front(front: Mapping[str, Any], *, icp_key: str) -> None:
    """The machine contract of an ``icp-definition``: the fields every reader of one depends on.

    Deliberately a floor, not a schema. The gates' shape, the persona map and the qualifier fields
    are read by the surfaces that use them; what is refused here is a document that could not be
    an ICP at all — the wrong kind, another key, no products to sell, no gates to qualify on.
    """

    kind = front.get("kind")
    if kind != ICP_KIND:
        raise IcpAuthoringRefused(
            "icp_front_matter_invalid",
            f"front matter must declare kind: {ICP_KIND} (found {kind!r})",
        )
    declared = front.get("icp_key")
    if declared != icp_key:
        raise IcpAuthoringRefused(
            "icp_front_matter_invalid",
            f"front matter icp_key must be {icp_key!r} (found {declared!r})",
        )
    products = front.get("product_ids")
    if (
        not isinstance(products, list)
        or not products
        or not all(isinstance(item, str) and item for item in products)
    ):
        raise IcpAuthoringRefused(
            "icp_front_matter_invalid",
            "front matter must declare product_ids: a non-empty list of product ids this ICP buys",
        )
    gates = front.get("hard_gates")
    if not isinstance(gates, list) or not gates:
        raise IcpAuthoringRefused(
            "icp_front_matter_invalid",
            "front matter must declare hard_gates: a non-empty list of gates an account must pass",
        )


async def _stored(conn: AsyncConnection, *, document_id: UUID, icp_key: str) -> AuthoredIcp | None:
    """The row this act already wrote, or ``None``. Read before anything is rendered or stored.

    The status is the row's own rather than a repeated ``"proposed"``: by the time a call is
    replayed a later version may have superseded this one, and reporting what is at rest is the
    honest answer.
    """

    row = (
        (
            await conn.execute(
                text(
                    "SELECT version, path, status, project_id FROM brand_knowledge_document "
                    "WHERE document_id = :document_id"
                ),
                {"document_id": document_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    path = str(row["path"])
    return AuthoredIcp(
        document_id=document_id,
        icp_key=icp_key,
        version=int(row["version"]),
        path=path,
        workspace_path=_workspace_path(path, project_scoped=row["project_id"] is not None),
        status=str(row["status"]),
        replayed=True,
    )


async def _refuse_cross_scope(
    conn: AsyncConnection, request: IcpAuthoringRequest, *, path: str
) -> None:
    """A key belongs to one scope. Writing into the other one is refused, not silently allowed.

    A project variant exists to be *different* from the brand's profile, so it takes its own key:
    ``gi`` stays the brand's and ``gi-dac`` is the project's. Without this the two would coexist at
    one path in two scopes, the project would read its own row wherever it looked, and the brand's
    profile would quietly stop being what that project researched against.

    Only servable rows own a key — a superseded document is history, and its name is free again.
    Another *project's* variant is invisible here on purpose: it is not this project's to collide
    with, and the scoped unique index already keeps the two rows apart.
    """

    rows = (
        (
            await conn.execute(
                text(
                    "SELECT project_id FROM brand_knowledge_document "
                    "WHERE workspace_id = :workspace_id AND brand_id = :brand_id "
                    "  AND path = :path AND status = ANY(:statuses)"
                ),
                {
                    "workspace_id": request.workspace_id,
                    "brand_id": request.brand_id,
                    "path": path,
                    "statuses": list(_SERVABLE_STATUSES),
                },
            )
        )
        .mappings()
        .all()
    )
    scopes = {row["project_id"] for row in rows}
    if request.scope == "project" and None in scopes:
        raise IcpAuthoringRefused(
            "icp_key_taken_by_brand",
            f"the brand already has an ICP named {request.icp_key!r}; a project variant needs its "
            "own key, with derived_from naming the brand profile it adapts",
        )
    if request.scope == "brand" and any(scope is not None for scope in scopes):
        raise IcpAuthoringRefused(
            "icp_key_taken_by_project",
            f"a project already owns an ICP named {request.icp_key!r}; a brand profile needs a "
            "key no project has taken",
        )


async def _derived_from(
    conn: AsyncConnection, storage: StorageBackend, request: IcpAuthoringRequest
) -> UUID | None:
    """The brand document this variant adapts, or nothing at all.

    Read with no project scope, so only the *brand's* profiles can be named: a lineage pointing at
    another project's private variant would be a link this project may not follow, and pointing at
    its own would make the chain circular rather than explanatory.
    """

    if request.derived_from_icp_key is None:
        return None
    subject = await current_icp_document(
        conn,
        storage,
        workspace_id=request.workspace_id,
        brand_id=request.brand_id,
        icp_key=request.derived_from_icp_key,
        project_id=None,
    )
    if subject is None:
        raise IcpAuthoringRefused(
            "derived_from_not_found",
            f"this brand has no readable ICP document named {request.derived_from_icp_key!r} to "
            "derive from",
        )
    return subject.document_id


def _authored_front_matter(
    front: dict[str, Any],
    *,
    request: IcpAuthoringRequest,
    scope_project_id: str | None,
    derived_from: UUID | None,
    authored_at: datetime,
) -> dict[str, Any]:
    """The model's front matter with the platform's facts stamped over it."""

    stamped = {key: value for key, value in front.items() if key not in _PLATFORM_OWNED_KEYS}
    stamped["status"] = "proposed"
    stamped["brand_id"] = request.brand_id
    if scope_project_id is not None:
        stamped["project_id"] = scope_project_id
    if derived_from is not None:
        stamped["derived_from"] = str(derived_from)
    stamped["authored_by"] = {"turn_id": str(request.turn_id), "user_id": request.user_id}
    stamped["authored_at"] = authored_at.isoformat()
    return stamped


async def author_icp_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    request: IcpAuthoringRequest,
    *,
    now: Callable[[], datetime] = _utcnow,
) -> AuthoredIcp:
    """Store one authored ICP as the next ``proposed`` version of its path, inside its own scope.

    **Replay.** The document id is derived from ``(turn, scope, key)``, so a retried call finds its
    own row and returns it *before* anything is rendered or stored — no orphan artifact per
    attempt. ``authored_at`` is the one non-deterministic value in the bytes, and the
    short-circuit above is what keeps it from making a replay a different document.

    Raises :class:`IcpAuthoringRefused` — never a partial write — for every refusable condition.
    """

    _validate_key(request.icp_key)
    try:
        front, body = parse_front_matter(request.document_text, preserve_body=True)
    except ValueError as exc:
        raise IcpAuthoringRefused("icp_front_matter_invalid", str(exc)) from exc
    _validate_front(front, icp_key=request.icp_key)

    document_id = authored_document_id(
        turn_id=request.turn_id, scope=request.scope, icp_key=request.icp_key
    )
    replayed = await _stored(conn, document_id=document_id, icp_key=request.icp_key)
    if replayed is not None:
        return replayed

    path = _path_for(request.icp_key)
    scope_project_id = request.project_id if request.scope == "project" else None
    await _refuse_cross_scope(conn, request, path=path)
    derived_from = await _derived_from(conn, storage, request)

    rendered = render_markdown(
        KnowledgeDocument(
            kind=ICP_KIND,
            folder=ICP_FOLDER,
            path=path,
            front_matter=_authored_front_matter(
                front,
                request=request,
                scope_project_id=scope_project_id,
                derived_from=derived_from,
                authored_at=now(),
            ),
            body=body,
            cost=None,
        )
    ).encode("utf-8")
    sha = content_address(rendered)
    key = artifact_key(request.workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=request.workspace_id,
        content_sha256=sha,
        media_type=ICP_ARTIFACT_MEDIA_TYPE,
        size_bytes=len(rendered),
        source_key=ICP_AUTHORING_SOURCE_KEY,
    )
    await storage.put(key, rendered, media_type=ICP_ARTIFACT_MEDIA_TYPE)

    scope_params = {
        "workspace_id": request.workspace_id,
        "brand_id": request.brand_id,
        "path": path,
        "project_id": scope_project_id,
    }
    # One read answers both halves of the version chain, the way ``onboarding_synthesis`` reads it:
    # the next version over every row in this scope, and the highest-version *servable* row this
    # one follows. They must agree, or a reader walking ``supersedes_document_id`` backwards would
    # step off a row that was never retired.
    lineage = (
        (
            await conn.execute(
                text(
                    "SELECT"
                    "  (SELECT COALESCE(MAX(version), 0) + 1"
                    "     FROM brand_knowledge_document"
                    "    WHERE workspace_id = :workspace_id AND brand_id = :brand_id"
                    "      AND path = :path"
                    "      AND project_id IS NOT DISTINCT FROM :project_id"
                    "  ) AS next_version,"
                    "  (SELECT document_id"
                    "     FROM brand_knowledge_document"
                    "    WHERE workspace_id = :workspace_id AND brand_id = :brand_id"
                    "      AND path = :path"
                    "      AND project_id IS NOT DISTINCT FROM :project_id"
                    "      AND status = ANY(:statuses)"
                    "    ORDER BY version DESC LIMIT 1"
                    "  ) AS supersedes_document_id"
                ),
                {**scope_params, "statuses": list(_SERVABLE_STATUSES)},
            )
        )
        .mappings()
        .one()
    )
    version = int(lineage["next_version"])
    supersedes = lineage["supersedes_document_id"]
    try:
        await conn.execute(
            text(
                "INSERT INTO brand_knowledge_document ("
                "  document_id, workspace_id, brand_id, project_id, derived_from_document_id, "
                "  folder, path, kind, version, status, artifact_key, artifact_sha256, "
                "  produced_by_step_id, produced_by_turn_id, supersedes_document_id"
                ") VALUES ("
                "  :document_id, :workspace_id, :brand_id, :project_id, :derived_from, "
                "  :folder, :path, :kind, :version, 'proposed', :artifact_key, :artifact_sha256, "
                "  NULL, NULL, :supersedes"
                ") ON CONFLICT (document_id) DO NOTHING"
            ),
            {
                **scope_params,
                "document_id": document_id,
                "derived_from": derived_from,
                "folder": ICP_FOLDER,
                "kind": ICP_KIND,
                "version": version,
                "artifact_key": key,
                "artifact_sha256": sha,
                "supersedes": supersedes,
            },
        )
    except IntegrityError as exc:
        if "brand_knowledge_document_scope_path_version" in str(exc.orig):
            # Another writer took this version number between the read and the insert. The agent's
            # draft is not lost and nothing partial is at rest — it re-reads the path and retries.
            raise IcpAuthoringRefused(
                "icp_document_version_race",
                "another writer published a version of this path; re-read the document and retry",
            ) from exc
        raise
    await conn.execute(
        text(
            "UPDATE brand_knowledge_document SET status = 'superseded', updated_at = now() "
            "WHERE workspace_id = :workspace_id AND brand_id = :brand_id AND path = :path "
            "  AND project_id IS NOT DISTINCT FROM :project_id "
            "  AND document_id <> :document_id AND status = ANY(:statuses)"
        ),
        {**scope_params, "document_id": document_id, "statuses": list(_RETIRABLE_STATUSES)},
    )
    # Read the row back rather than trusting the version just computed: the stored one is what
    # every later reader, gate and pin will cite.
    stored = await _stored(conn, document_id=document_id, icp_key=request.icp_key)
    if stored is None:  # pragma: no cover - the INSERT above either landed or raised
        raise IcpAuthoringRefused(
            "icp_document_version_race", "the authored ICP document did not persist"
        )
    return AuthoredIcp(
        document_id=stored.document_id,
        icp_key=stored.icp_key,
        version=stored.version,
        path=stored.path,
        workspace_path=stored.workspace_path,
        status=stored.status,
        replayed=False,
    )


# =================================================================================================
# the service seam + its production implementation
# =================================================================================================


class IcpAuthoringService(Protocol):
    """What the toolbelt tool calls. One transaction per call is the implementation's business."""

    async def author(self, request: IcpAuthoringRequest) -> AuthoredIcp: ...


class DbIcpAuthoringService:
    """The production service: one transaction per authored document, artifact row and blob."""

    def __init__(
        self,
        storage: StorageBackend,
        *,
        conn_factory: ConnFactory = transaction,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory
        self._now = now

    async def author(self, request: IcpAuthoringRequest) -> AuthoredIcp:
        async with self._conn_factory() as conn:
            return await author_icp_document(conn, self._storage, request, now=self._now)
