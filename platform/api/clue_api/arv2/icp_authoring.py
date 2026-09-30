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
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.icp_confirmation import (
    ICP_ARTIFACT_MEDIA_TYPE,
    ICP_KIND,
    current_icp_document,
    current_project_icp_pin,
)
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.onboarding_documents import KnowledgeDocument, render_markdown
from clue_db import ConnFactory, transaction
from clue_storage import StorageBackend, artifact_key, content_address, record_artifact

if TYPE_CHECKING:  # the refresher's module imports this package's neighbours; type only
    from clue_api.project_library_refresh import ProjectLibraryRefresher

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
    "comma_split_rows",
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

#: Where each scope's documents are readable in the agent's workspace — in the mounted brand and
#: project libraries. Both prefixes are restated here for the Global Constraint 7 reason above;
#: they are ``brand_knowledge_context.INPUT_PREFIX`` and
#: ``project_context_files.PROJECT_INPUT_PREFIX``.
_BRAND_INPUT_PREFIX = "brand/knowledge/"
_PROJECT_INPUT_PREFIX = "project/"

#: Front-matter keys the platform owns. A model that typed any of them is not believed: a draft
#: cannot confirm itself, scope itself, or claim a lineage. They are removed, then re-stamped
#: from the request and the rows this module resolved.
_PLATFORM_OWNED_KEYS: tuple[str, ...] = (
    "confirmed_by",
    "confirmation_mode",
    "confirmation_turn_ref",
    "confirmed_at",
    "confirmed_for_project_id",
    "product_selection_version",
    "user_edit",
    "derived_from",
    "project_id",
    "brand_id",
    "status",
)


#: The fields a ``hard_gates`` or ``qualifier_fields`` row is written with. Any of them may be
#: empty; a key with no value that is *not* one of them is the comma-split signature below.
ICP_ROW_FIELDS: frozenset[str] = frozenset(
    {"key", "rule", "test", "criterion", "field_key", "description", "display", "titles"}
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def comma_split_rows(front: Mapping[str, Any]) -> tuple[str, ...]:
    """Name every gate or qualifier row whose text an unquoted comma cut apart.

    Written inline — ``- {key: k, rule: a, b, test: t}`` — a comma inside a value ends it: YAML
    keeps ``a`` as the rule and turns ``b`` into a key of its own with no value. The document
    still parses, and the rest of the sentence is gone. So a value-less key that is not one of
    :data:`ICP_ROW_FIELDS` is text that was lost, never a field; one line per damaged row, naming
    the row by its ``key`` (a gate) or ``field_key`` (a qualifier field) and the fragments.
    """

    damaged: list[str] = []
    for list_name, name_field in (("hard_gates", "key"), ("qualifier_fields", "field_key")):
        rows = front.get(list_name)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            stray = [
                str(field)
                for field, value in row.items()
                if value is None and field not in ICP_ROW_FIELDS
            ]
            if stray:
                name = row.get(name_field) or f"#{index + 1}"
                damaged.append(f"{list_name} {name!r}: {', '.join(repr(s) for s in stray)}")
    return tuple(damaged)


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
    #: brand profile, the project's for a variant, and the version-qualified file name when the
    #: project's pin already owns the plain name of this path (see :func:`_receipt_name`).
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


def _version_qualified(path: str, version: int) -> str:
    """``audience/icp-gi.md`` at v3 → ``audience/icp-gi.v3.md``.

    ``brand_knowledge_context.version_qualified_path``, restated for the Global Constraint 7 reason
    the two prefixes above are restated. The materializer gives the *pinned* version of a path the
    plain name and every other version this one, so a receipt that ignored the rule would name the
    file the pin owns rather than the file this act just wrote.
    """

    stem, dot, suffix = path.rpartition(".")
    return f"{stem}.v{version}.{suffix}" if dot else f"{path}.v{version}"


async def _receipt_name(
    conn: AsyncConnection,
    request: IcpAuthoringRequest,
    *,
    document_id: UUID,
    path: str,
    version: int,
    row_project_id: str | None,
) -> str:
    """The name this version really materializes under — plain, or version-qualified by the pin.

    A document owns the plain name of its path unless *another* version of that same path, in that
    same scope, is the project's pin: the pin keeps the natural name and everything else is offered
    beside it under :func:`_version_qualified` (``brand_knowledge_context.workspace_paths``). An
    authored row is always born ``proposed``, so it is never the pin itself — which means the very
    first authoring over a pinned path lands at the qualified name, and a receipt promising the
    plain one would send the agent to re-read the *pinned* (older) profile as its own new draft.
    """

    pin = await current_project_icp_pin(
        conn, workspace_id=request.workspace_id, project_id=request.project_id
    )
    if (
        pin is not None
        and pin.document_id != document_id
        and pin.path == path
        and pin.project_id == row_project_id
    ):
        return _version_qualified(path, version)
    return path


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
    an ICP at all — the wrong kind, another key, no products to sell, no gates to qualify on — and
    one whose gate or qualifier rows lost text to a comma (:func:`comma_split_rows`), because the
    agents that read the document would otherwise act on half a rule.
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
    damaged = comma_split_rows(front)
    if damaged:
        raise IcpAuthoringRefused(
            "icp_front_matter_invalid",
            "a comma inside an unquoted value split these rows, and the text after it became "
            f"keys with no value ({'; '.join(damaged)}). Write each hard_gates and "
            "qualifier_fields row in block YAML, one field per line, with every value in double "
            'quotes (rule: "…, …").',
        )


async def _stored(
    conn: AsyncConnection, request: IcpAuthoringRequest, *, document_id: UUID
) -> AuthoredIcp | None:
    """The row this act already wrote, or ``None``. Read before anything is rendered or stored.

    The status is the row's own rather than a repeated ``"proposed"``: by the time a call is
    replayed a later version may have superseded this one, and reporting what is at rest is the
    honest answer. ``workspace_path`` is resolved the same way, against the pin as it stands now.
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
    version = int(row["version"])
    row_project_id = None if row["project_id"] is None else str(row["project_id"])
    name = await _receipt_name(
        conn,
        request,
        document_id=document_id,
        path=path,
        version=version,
        row_project_id=row_project_id,
    )
    return AuthoredIcp(
        document_id=document_id,
        icp_key=request.icp_key,
        version=version,
        path=path,
        workspace_path=_workspace_path(name, project_scoped=row_project_id is not None),
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

    **The rule is this writer's, not the schema's.** The synthesis writer does not apply it:
    ``onboarding_synthesis_wiring._register_documents`` writes the brand's ICPs unscoped with no
    cross-scope check, so a full re-onboarding can mint a brand-level ``audience/icp-foo.md`` after
    a project has already taken ``foo`` for a variant, and the invariant this function asserts is
    then false at rest. That state is survivable rather than corrupting: the two rows occupy two
    different workspace paths, and ``icp_confirmation.current_icp_document``'s scoped lookup orders
    project-local first, so the project keeps reading its own row wherever it looks. Enforcing the
    rule on the synthesis path too would mean refusing a brand's own re-onboarding because of one
    project's private key, which is the worse trade.
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
    replayed = await _stored(conn, request, document_id=document_id)
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
    # The blob goes out last, after every refusable condition has passed and the row is in this
    # transaction. ``record_artifact`` stays above the INSERT because the document's FK-less
    # ``artifact_key`` is only meaningful once the artifact row exists, and both roll back
    # together; the blob does not, so writing it before a refusal (a version race, an integrity
    # failure) would leave bytes in object storage that nothing references and nothing reaps —
    # and this is the one write path an agent can retry in a loop.
    await storage.put(key, rendered, media_type=ICP_ARTIFACT_MEDIA_TYPE)
    # Read the row back rather than trusting the version just computed: the stored one is what
    # every later reader, gate and pin will cite.
    stored = await _stored(conn, request, document_id=document_id)
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
        library: ProjectLibraryRefresher | None = None,
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory
        self._now = now
        self._library = library

    async def author(self, request: IcpAuthoringRequest) -> AuthoredIcp:
        async with self._conn_factory() as conn:
            authored = await author_icp_document(conn, self._storage, request, now=self._now)
        # After the commit, never inside it: the library's compile takes this project's row lock.
        # Best-effort by contract — an authored document that landed must not report failure
        # because its rendering could not be written. A brand-scoped write is refreshed too: the
        # project's library serves the pinned document whatever scope authored it.
        if self._library is not None:
            await self._library.refresh(
                workspace_id=request.workspace_id, project_id=request.project_id
            )
        return authored
