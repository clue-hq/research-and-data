"""FI-2 slice 1, Task 3 — the global-lens account detail: ``GET /frontend/v1/accounts/{id}``.

The **union** view of one account: everything the workspace knows about it, with every piece of
project-relative work attributed to the project that produced it (FI-2 §7 R2). It composes the same
untouched mechanism surfaces the list endpoint does, plus two more:

1. **identity** — the ``account_entity`` row (name/domain/aliases/registry ids/HQ), with
   ``surviving_id`` semantics: a merged loser is not a 404, it is a **redirect** — the survivor is
   served and ``redirectedFrom`` names the id the caller asked for;
2. **field species** — :func:`~clue_core.resolve_research_scope` over the *effective* registry
   (global + workspace rows) decides, per field this account actually holds claims for, whether it
   is workspace truth or per-project work. Nothing here enumerates field families: the split is a
   registry read, so a pack that later declares a relative field lands in the project sections
   automatically and a §5.2 re-ratification cannot silently drift from this endpoint;
3. **neutral facts** — the ``project_neutral`` half, served ONCE from ``current_values`` (the
   canonical merge) with its freshness state, reference time and producing source. Deliberately
   **not** lineage-filtered: a neutral fact is workspace truth in every lens, whichever project's
   run happened to pay for it (FI-2 slice-0 handoff — lineage filtering is species-conditional);
4. **project sections** — the ``project_relative`` half, partitioned by ``run_lineage.project_id``.
   A claim whose run has no lineage row, or a lineage row with a NULL project, goes to the
   **unattributed** section (``projectId: null``) rather than being dropped or guessed onto a
   project: the exemption classes are real (``run_lineage``'s module docstring lists them —
   redaction runs, pre-FI-2 rows) and hiding their claims would misreport the account. Each
   section's project ``name`` comes from ONE batched
   :func:`~clue_api.frontend_read.accounts_list.project_names` read shared with the list row;
5. **committee** — the union of every targeting project's governed committee, through
   ``ContactEligibilityResolver`` (never ``identity.contact_ids_for_account``, per the FI-1 §4.5
   ruling), each member carrying the projects that target them. Two gates, both the resolver's or
   C7's and neither re-derived here: *membership* eligibility is the resolver's (a member whose
   role/persona binding is not STRONG does not come back), and *display* eligibility is
   ``committee.committee_member_displayable`` over the workspace policy — the same gate the
   `/contacts` endpoints apply, shared so the two surfaces cannot answer differently about the same
   people;
6. **coverage** — how many fields this account actually holds, and which fields research asked for
   and could not resolve.

**Wire-shape deviations from the task plan, both for the same reason** (recorded here because
Task 5 copies the *as-built* shapes into `apps/frontend/docs/api-contracts/accounts.md`): the plan
sketches ``score: {...}|null`` and ``narrative: {...}|null``; this endpoint serves ``scores: [...]``
and ``narratives: [...]``. One project can legitimately score an account under several ICPs (D5)
and can hold one value narrative *per persona* (M12.1). Collapsing either to a single slot would
require picking a winner — the representative-run fiction FI-2 §7 exists to remove. Plural is the
honest shape; ``insights`` was already plural.

The two disciplines the list endpoint enforces hold here too, for the same reasons:

* **Never scope a claim read by ``claim.workspace_id``** — a DB CHECK forces it NULL on every
  ``public_footprint`` claim, so that predicate silently *empties* a read instead of narrowing it.
  Every claim read here scopes through the **entity** (an id already proven to belong to this
  workspace) plus ``WorkspaceScope.predicate()``, and the lineage join adds
  ``run_lineage.workspace_id`` — a real tenancy column on a real tenancy table.
* **Band-2 wire discipline** — semantic values only: enums, numbers, ISO-8601 timestamps, opaque
  ids, and ``null`` wherever the backend genuinely knows nothing. ``provider`` is the raw
  ``claim.source_key``: no source display-name surface exists anywhere in the platform
  (``SourceManifest`` carries no label, and the C7 provider chip renders the raw string too), and
  inventing a label map here would be exactly the presentation mapping Band-2 forbids.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import JsonValue
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.accounts_list import (
    SCORE_FIELD_KEYS,
    ProjectScore,
    WireModel,
    group_score_claims,
    project_names,
)
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.committee import read_governed_committee
from clue_api.frontend_read.prose import ACCOUNT_SUMMARY_FIELD, ProseRead, read_prose
from clue_core import (
    EntityId,
    EntityType,
    FreshnessState,
    Persona,
    ResearchScope,
    decode_jsonb_scalar,
    reference_time,
)
from clue_db import ConnFactory
from clue_research.claimstore import (
    FieldFilters,
    FieldRegistryScope,
    WorkspaceScope,
    claims_by_ids,
    current_values,
    # FI-2 P3's one species derivation, which now lives beside ``list_effective_fields`` in the
    # claim-store registry: the research economics (the account runtime's fresh-skip, the R5 guard,
    # the Sumble gap ladder) must answer "is this field project-relative?" exactly as this read
    # layer does, and a research-path module importing a BFF module was the wrong direction.
    field_species,
    list_effective_fields,
)
from clue_research.identity import get_account, get_contacts, surviving_id
from clue_research.membership import ProjectMembership, memberships_for_accounts

#: ``account.value_narrative`` gets its own slot in a project section: it is the FI-2 §5.2 relative
#: family that is an *argument* rather than a fact, and the frontend renders it as prose, not as a
#: field row. Imported by key rather than from ``clue_research.narrative`` so this read layer takes
#: no dependency on the narrative package's internals.
NARRATIVE_FIELD_KEY = "account.value_narrative"


class AccountNotFound(LookupError):
    """No live account with that id is visible in this workspace."""


# --- the wire vocabulary ----------------------------------------------------------------------


class NeutralFact(WireModel):
    """One ``project_neutral`` field's current truth, from the canonical merge.

    ``freshness`` is semantic, not cosmetic: the merge never drops a stale winner, it labels it, so
    the frontend can show "we know this, and it is past its TTL" instead of silently implying
    currency. (The M1.2 merge only ever assigns ``fresh``/``stale``; ``expired`` is the M9.5
    retention disposition, which never wins a merge.)
    """

    field_key: str
    value: JsonValue
    freshness: FreshnessState
    observed_at: datetime
    provider: str | None = None


class RelativeFact(WireModel):
    """One live ``project_relative`` claim, exactly as written — not merged.

    Relative claims are **not** collapsed to one winner per field: several are legitimate at once
    (one narrative per persona; one insight per aspect), and merging them would destroy precisely
    the per-project, per-persona structure this endpoint exists to expose.
    """

    field_key: str
    value: JsonValue
    observed_at: datetime
    provider: str | None = None


class AccountProjectSection(WireModel):
    """One project's work on this account — or, when ``project_id`` is ``null``, the honest
    **unattributed** bucket for claims whose run maps to no project.

    ``added_via``/``added_at`` come from ``project_account`` and are ``null`` in two legitimate
    cases: the unattributed section (no membership exists to describe), and a project that produced
    research on this account without a membership row — which should not happen, and is therefore
    reported rather than hidden.

    ``name`` is the ``project`` row's own name, from the same batched
    :func:`~clue_api.frontend_read.accounts_list.project_names` read the list row uses, so the two
    surfaces cannot name one project differently. It is ``null`` for the unattributed section (there
    is no project to name) and for a lineage-derived project id this workspace holds no ``project``
    row for — ``run_lineage.project_id`` carries no FK to ``project``, so that is reachable, and an
    unnamed section is the honest rendering of it.
    """

    project_id: str | None = None
    name: str | None = None
    added_via: str | None = None
    added_at: datetime | None = None
    scores: tuple[ProjectScore, ...] = ()
    narratives: tuple[RelativeFact, ...] = ()
    insights: tuple[RelativeFact, ...] = ()


class CommitteeMemberRow(WireModel):
    """One governed committee member, with the projects that target them."""

    contact_id: uuid.UUID
    name: str | None = None
    persona: Persona
    role_on_committee: str
    project_ids: tuple[str, ...] = ()


class UnresolvedField(WireModel):
    """A research gap plus the registry-authored explanation of what was requested."""

    field_key: str
    description: str | None = None


class AccountCoverage(WireModel):
    """How much of this account is actually researched — a confidence report, not a guarantee.

    ``researched_field_count`` counts the distinct fields holding at least one live, non-rejected
    claim for this account: the honest "how much do we hold". ``unresolved_field_keys`` are fields
    the M8D research surface *asked for* and could not answer (``null``/``unsupported`` outcomes)
    and that still hold no live claim — an empty, flagged field is a correct output, and naming it
    is more useful than a percentage that implies exhaustiveness the platform cannot prove.
    """

    researched_field_count: int
    unresolved_field_keys: tuple[str, ...] = ()
    unresolved_fields: tuple[UnresolvedField, ...] = ()


class AccountDetail(WireModel):
    """The whole account, unioned across projects."""

    id: uuid.UUID
    name: str
    domain: str | None = None
    aliases: tuple[str, ...] = ()
    registry_ids: dict[str, str] = {}
    hq_geo: dict[str, JsonValue] | None = None
    # Set when the requested id was a merged loser: the body is the survivor's, and this names what
    # the caller asked for so a bookmarked/linked id resolves visibly rather than silently.
    redirected_from: uuid.UUID | None = None
    summary: ProseRead
    neutral_facts: tuple[NeutralFact, ...] = ()
    project_sections: tuple[AccountProjectSection, ...] = ()
    committee: tuple[CommitteeMemberRow, ...] = ()
    coverage: AccountCoverage


# --- SQL --------------------------------------------------------------------------------------

# Every field this account holds a live, promotable claim for. Eligibility mirrors the merge's
# (live, field-flavoured, not rejected) so the key set and the values agree. Scoped through the
# entity — the id is already proven to be this workspace's — plus the reuse-class predicate.
_DISTINCT_FIELD_KEYS_TEMPLATE = """
    SELECT DISTINCT field_key
    FROM claim
    WHERE entity_id = :entity_id
      AND superseded_by IS NULL
      AND claim_flavor = 'field_claim'
      AND verification_status <> 'rejected'
      AND {scope_sql}
"""

# The relative half, with its project attribution. A **LEFT** join (unlike the list endpoint's
# inner join): a claim whose run has no lineage row, or whose lineage row carries no project, must
# reach the unattributed section rather than disappear. The join is qualified by workspace so a
# lineage row belonging to another tenant can never attribute this workspace's claim, and it
# dispatches on ``project_id`` alone — ``run_lineage.kind`` is advisory, first-writer-wins metadata
# over a mixed run-id space and must never decide attribution (FI-2 slice-0 handoff).
RELATIVE_CLAIMS_TEMPLATE = """
    SELECT c.field_key, c.value_json, c.observed_at, c.collected_at, c.source_key, l.project_id
    FROM (
        SELECT id, field_key, value_json, observed_at, collected_at, source_key, run_id
        FROM claim
        WHERE entity_id = :entity_id
          AND field_key IN :field_keys
          AND superseded_by IS NULL
          AND claim_flavor = 'field_claim'
          AND verification_status <> 'rejected'
          AND {scope_sql}
    ) c
    LEFT JOIN run_lineage l
        ON l.run_id = c.run_id AND l.workspace_id = :lineage_workspace_id
    ORDER BY c.collected_at, c.id
"""

# Fields the M8D research surface asked for and could not answer. The result *row* is reached
# through ``entity_research_result_subject_history (workspace_id, target_entity_id, …)``, but the
# subject filter that decides the answer is the **field row's own**: an account result carries the
# fields of every contact it discovered (``entity_research_tools._flatten_result_fields`` persists
# ``discovered_subjects``' fields under the account's result, stamping each row's own
# ``subject_type``/``target_entity_id``). Filtering on the result alone would therefore report a
# *contact's* unresolved field as the account's — and it could never clear, because answering it
# writes a contact claim this account's held-key set never sees.
_UNRESOLVED_FIELDS = text(
    """
    SELECT DISTINCT f.field_key
    FROM entity_research_result r
    JOIN entity_research_result_field f ON f.result_id = r.result_id
    WHERE r.workspace_id = :workspace_id
      AND r.target_entity_id = :entity_id
      AND f.workspace_id = :workspace_id
      AND f.subject_type = 'account'
      AND f.target_entity_id = :entity_id
      AND f.outcome IN ('null', 'unsupported')
    """
)

# --- composition helpers ----------------------------------------------------------------------


def _reference_time(observed_at: datetime | None, collected_at: datetime) -> datetime:
    """:func:`~clue_core.reference_time`'s rule, over loose columns.

    Where a whole :class:`~clue_core.Claim` is in hand, call ``core.reference_time(claim)``
    directly — it is the M9.5 DRY consolidation the merge and the freshness engine share, and this
    module does exactly that for the neutral-fact winners. The relative-claims read, though,
    projects five columns out of SQL rather than hydrating claims, so it has an
    ``(observed_at, collected_at)`` pair and no claim; this restates the same rule for that shape
    instead of hydrating a claim purely to ask it a two-field question.
    """
    return observed_at or collected_at


async def _read_distinct_field_keys(
    conn: AsyncConnection, *, entity_id: EntityId, scope: WorkspaceScope
) -> tuple[str, ...]:
    scope_sql, scope_params = scope.predicate()
    rows = await conn.execute(
        text(_DISTINCT_FIELD_KEYS_TEMPLATE.format(scope_sql=scope_sql)),
        {"entity_id": entity_id, **scope_params},
    )
    return tuple(sorted(str(key) for key in rows.scalars()))


async def _read_neutral_facts(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    field_keys: Sequence[str],
    scope: WorkspaceScope,
) -> tuple[NeutralFact, ...]:
    """The canonical merge over the neutral fields, enriched with the winning claim's source.

    ``CurrentValue.provenance`` carries the winning claim's id but neither its ``source_key`` nor
    its ``observed_at``, so the winners are re-read in one batch — the same claims, by id, under the
    same scope.
    """
    if not field_keys:
        return ()
    merged = await current_values(conn, [entity_id], field_keys, scope=scope)
    if not merged:
        return ()
    winners = await claims_by_ids(
        conn, [value.provenance.claim_id for value in merged.values()], scope=scope
    )
    facts: list[NeutralFact] = []
    for (_entity, field_key), value in merged.items():
        winner = winners.get(value.provenance.claim_id)
        facts.append(
            NeutralFact(
                field_key=field_key,
                value=value.value_json,
                freshness=value.freshness_state,
                observed_at=(
                    reference_time(winner) if winner is not None else value.provenance.collected_at
                ),
                provider=None if winner is None else winner.source_key,
            )
        )
    return tuple(sorted(facts, key=lambda fact: fact.field_key))


class _RelativeClaims:
    """The relative half, already partitioned by project (``None`` = unattributed)."""

    def __init__(self) -> None:
        self.scores: dict[str | None, tuple[ProjectScore, ...]] = {}
        self.narratives: dict[str | None, list[RelativeFact]] = defaultdict(list)
        self.insights: dict[str | None, list[RelativeFact]] = defaultdict(list)

    @property
    def projects(self) -> set[str | None]:
        return set(self.scores) | set(self.narratives) | set(self.insights)


async def _read_relative_claims(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    field_keys: Sequence[str],
    workspace_id: str,
    scope: WorkspaceScope,
) -> _RelativeClaims:
    """Read every live relative claim and route it by *species-derived* family.

    Three families, and the routing is derived from the field key's registered species rather than
    from an enumerated list of "insight" fields — which matters because the FI-1-era insight
    families (``account.recent_funding``, ``operational_pain``, ``strategic_moves``,
    ``account.resonance.*``) are all ``project_neutral`` under the ratified §5.2 table and belong in
    ``neutralFacts``. ``insights`` therefore means "a relative field that is neither a score nor the
    narrative" — today only a pack field that declares itself relative, tomorrow whatever §5.2
    ratifies next, with no code change here.
    """
    partitioned = _RelativeClaims()
    if not field_keys:
        return partitioned
    scope_sql, scope_params = scope.predicate()
    stmt = text(RELATIVE_CLAIMS_TEMPLATE.format(scope_sql=scope_sql)).bindparams(
        bindparam("field_keys", expanding=True)
    )
    rows = (
        await conn.execute(
            stmt,
            {
                "entity_id": entity_id,
                "field_keys": list(field_keys),
                "lineage_workspace_id": workspace_id,
                **scope_params,
            },
        )
    ).all()

    score_rows: list[tuple[uuid.UUID, str | None, str, Any, datetime]] = []
    for field_key, raw_value, observed_at, collected_at, source_key, project_id in rows:
        key = str(field_key)
        value = decode_jsonb_scalar(raw_value)
        project = None if project_id is None else str(project_id)
        at = _reference_time(observed_at, collected_at)
        if key in SCORE_FIELD_KEYS:
            score_rows.append((uuid.UUID(str(entity_id)), project, key, value, at))
            continue
        fact = RelativeFact(
            field_key=key,
            value=value,
            observed_at=at,
            provider=None if source_key is None else str(source_key),
        )
        target = partitioned.narratives if key == NARRATIVE_FIELD_KEY else partitioned.insights
        target[project].append(fact)

    partitioned.scores = {
        project: scores for (_entity, project), scores in group_score_claims(score_rows).items()
    }
    return partitioned


async def _read_committee(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    workspace_id: str,
    memberships: Sequence[ProjectMembership],
) -> tuple[CommitteeMemberRow, ...]:
    """Project the shared governed committee into Account-detail rows.

    Addressability is not re-derived here: the Contacts list and Contact profile consume the same
    :func:`read_governed_committee` result, so every member linked from this response is a valid
    Contact-detail subject under the same workspace policy.
    """
    union, _policy = await read_governed_committee(
        conn,
        account_id=account_id,
        workspace_id=workspace_id,
        memberships=memberships,
    )
    if not union.members:
        return ()
    contacts = await get_contacts(conn, tuple(union.members))
    return tuple(
        sorted(
            (
                CommitteeMemberRow(
                    contact_id=uuid.UUID(str(contact_id)),
                    name=contacts[contact_id].full_name if contact_id in contacts else None,
                    persona=member.persona,
                    role_on_committee=member.role_on_committee,
                    project_ids=tuple(union.project_ids[contact_id]),
                )
                for contact_id, member in union.members.items()
            ),
            key=lambda member: (member.persona.value, str(member.contact_id)),
        )
    )


async def _read_coverage(
    conn: AsyncConnection,
    *,
    entity_id: EntityId,
    workspace_id: str,
    held_field_keys: Sequence[str],
) -> AccountCoverage:
    rows = await conn.execute(
        _UNRESOLVED_FIELDS, {"workspace_id": workspace_id, "entity_id": entity_id}
    )
    held = set(held_field_keys)
    # A field research once failed on but has since been answered is not unresolved.
    unresolved = sorted({str(key) for key in rows.scalars()} - held)
    definitions = (
        {
            item.field_def.field_key: item
            for item in await list_effective_fields(
                conn,
                scope=FieldRegistryScope.for_workspace(workspace_id),
                filters=FieldFilters(active=None),
                include_retired=True,
            )
        }
        if unresolved
        else {}
    )
    return AccountCoverage(
        researched_field_count=len(held),
        unresolved_field_keys=tuple(unresolved),
        unresolved_fields=tuple(
            UnresolvedField(
                field_key=field_key,
                description=(
                    definitions[field_key].description if field_key in definitions else None
                ),
            )
            for field_key in unresolved
        ),
    )


def _sections(
    memberships: Sequence[ProjectMembership],
    relative: _RelativeClaims,
    names: dict[str, str],
) -> tuple[AccountProjectSection, ...]:
    """One section per targeting project, plus any project that produced relative work without a
    membership row, plus the unattributed bucket when (and only when) it has something in it.

    A project with a membership but no relative work still gets a section: "this project targets
    this account and has produced nothing yet" is a real, useful state, and rendering it as absence
    would be indistinguishable from the account not being targeted at all.
    """
    membership_by_project = {membership.project_id: membership for membership in memberships}
    ordered: list[str | None] = [membership.project_id for membership in memberships]
    ordered += sorted(
        project
        for project in relative.projects
        if project is not None and project not in membership_by_project
    )
    if None in relative.projects:
        # Always last: it is a residue bucket, not a peer of the real projects.
        ordered.append(None)

    sections: list[AccountProjectSection] = []
    for project in ordered:
        membership = membership_by_project.get(project) if project is not None else None
        sections.append(
            AccountProjectSection(
                project_id=project,
                name=None if project is None else names.get(project),
                added_via=None if membership is None else membership.added_via,
                added_at=None if membership is None else membership.added_at,
                scores=relative.scores.get(project, ()),
                narratives=tuple(relative.narratives.get(project, ())),
                insights=tuple(relative.insights.get(project, ())),
            )
        )
    return tuple(sections)


# --- the read model ---------------------------------------------------------------------------


async def read_account_detail(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    account_id: uuid.UUID,
) -> AccountDetail:
    """The union detail for one account, or :class:`AccountNotFound`.

    A merged loser is followed to its survivor and served with ``redirected_from`` set — matching
    ``surviving_id`` semantics, and matching what a user expects from a bookmarked id after a
    dedup. An id that is unknown, or that belongs to another workspace, is
    :class:`AccountNotFound` — the two are deliberately indistinguishable to the caller, so the
    endpoint cannot be used to probe another tenant's id space.
    """
    requested = EntityId(account_id)
    canonical = await surviving_id(conn, requested, EntityType.ACCOUNT)
    account = await get_account(conn, canonical)
    if account is None or account.workspace_id != workspace_id:
        raise AccountNotFound(str(account_id))

    scope = WorkspaceScope.for_workspace(workspace_id)
    field_keys = await _read_distinct_field_keys(conn, entity_id=canonical, scope=scope)
    fact_keys = tuple(key for key in field_keys if key != ACCOUNT_SUMMARY_FIELD)
    species = await field_species(conn, workspace_id=workspace_id, field_keys=fact_keys)
    neutral_keys = [key for key in fact_keys if species[key] is ResearchScope.PROJECT_NEUTRAL]
    relative_keys = [key for key in fact_keys if species[key] is ResearchScope.PROJECT_RELATIVE]

    memberships = (
        await memberships_for_accounts(
            conn, workspace_id=workspace_id, account_ids=[uuid.UUID(str(canonical))]
        )
    ).get(uuid.UUID(str(canonical)), ())

    neutral_facts = await _read_neutral_facts(
        conn, entity_id=canonical, field_keys=neutral_keys, scope=scope
    )
    summary = await read_prose(
        conn,
        entity_id=canonical,
        field_key=ACCOUNT_SUMMARY_FIELD,
        scope=scope,
    )
    relative = await _read_relative_claims(
        conn,
        entity_id=canonical,
        field_keys=relative_keys,
        workspace_id=workspace_id,
        scope=scope,
    )
    committee = await _read_committee(
        conn,
        account_id=canonical,
        workspace_id=workspace_id,
        memberships=memberships,
    )
    coverage = await _read_coverage(
        conn, entity_id=canonical, workspace_id=workspace_id, held_field_keys=field_keys
    )
    # One batched read over every project this response will show a section for — the membership
    # projects plus the lineage-derived ones — so section names cost one statement, not one each.
    names = await project_names(
        conn,
        workspace_id=workspace_id,
        project_ids=[membership.project_id for membership in memberships] + list(relative.projects),
    )

    return AccountDetail(
        id=uuid.UUID(str(canonical)),
        name=account.canonical_name,
        domain=account.primary_domain,
        aliases=account.aliases,
        registry_ids=account.registry_ids,
        hq_geo=account.hq_geo,
        redirected_from=None if canonical == requested else account_id,
        summary=summary,
        neutral_facts=neutral_facts,
        project_sections=_sections(memberships, relative, names),
        committee=committee,
        coverage=coverage,
    )


# --- the route --------------------------------------------------------------------------------


def register_account_detail_routes(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    """Register ``GET /accounts/{account_id}`` on the workspace-scoped `/frontend/v1` router."""

    @router.get("/accounts/{account_id}")
    async def get_account_detail(
        workspace_id: WorkspaceDep, account_id: uuid.UUID
    ) -> AccountDetail:
        async with conn_factory() as conn:
            try:
                return await read_account_detail(
                    conn,
                    workspace_id=workspace_id,
                    account_id=account_id,
                )
            except AccountNotFound as exc:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "ACCOUNT_NOT_FOUND",
                        "message": "no such account in this workspace",
                    },
                ) from exc
