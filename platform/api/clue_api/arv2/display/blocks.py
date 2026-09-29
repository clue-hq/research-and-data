"""A4 MACHINERY — a written section at rest: stored, superseded, and told when it went stale.

A display block is a *generated* thing that survives the run that generated it, so the two hard
questions are how it is replaced and how anyone knows it needs replacing.

**Replacement is a supersession, never an update.** :func:`insert_block` retires the section's live
row and writes a new one in the same transaction; the ``display_block_live`` partial unique index
makes "one live block per (workspace, subject, page, section)" a database fact, so two racing
writers cannot both leave a live row behind, and the retired body stays readable for anyone asking
what the page said last week.

**Staleness is recipe-scoped and evidence-shaped** (master plan §7). A section is stale when the
research moved underneath it — a newer claim on one of *its own* allowed keys, a cited claim that
has been superseded, a cited claim whose ``outreach_safe`` flag was flipped — or when the words
that produced it changed: a new instruction version, a new recipe version. It is deliberately not
a timestamp: a page that nothing has touched is not stale merely because it is old, and a page one
new fact contradicts is stale the moment that fact lands.

The claim scan runs over **every** subject id the page draws from — the subject plus its expansion
(a contact's account, an account's committee) — because a section that mixes account and contact
keys goes stale when *either* side moves.

Nothing here calls a model. :func:`compose_display_block` is the last step before the wire: stored
bodies, in recipe order, with the recipe's own layout flags.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.gather import SectionInput
from clue_api.arv2.display.prompts import PROMPT_VERSION
from clue_api.arv2.display.recipes import PAGE_SUBJECT_KIND, RECIPE_VERSION, SectionRecipe
from clue_api.arv2.display.runner import SectionDraft
from clue_core import decode_jsonb

#: The reasons a section can be stale, in the order :func:`stale_sections` reports them.
STALE_REASONS: tuple[str, ...] = (
    "new_claims",
    "superseded_citation",
    "flag_changed",
    "prompt_version",
    "recipe_version",
)


def prompt_version_of(recipe: SectionRecipe) -> str:
    """The version stamped on a block: the shared prompt plus *this* section's instructions.

    Both halves matter — rewriting the system prompt invalidates every section, rewriting one
    section's instructions invalidates only that section.
    """
    return f"{PROMPT_VERSION}+{recipe.instruction_version}"


@dataclass(frozen=True)
class LiveBlock:
    """One live ``display_block`` row, as every reader of a stored page sees it."""

    display_block_id: str
    section_key: str
    body_json: dict[str, Any]
    cited_claim_ids: tuple[str, ...]
    model: str
    prompt_version: str
    recipe_version: int
    generated_at: datetime


@dataclass(frozen=True)
class Staleness:
    """One stale section and every reason it is stale.

    ``reasons`` follows :data:`STALE_REASONS` order, and is never empty.
    """

    section_key: str
    reasons: tuple[str, ...]


# -- the body ------------------------------------------------------------------------------------


def block_body(draft: SectionDraft, section: SectionInput) -> dict[str, Any]:
    """Decision 9: the draft as the ``body_json`` column holds it.

    ``cited_flags`` is the point of the shape: it records what each cited claim's ``outreach_safe``
    was *when the section was written*, which is the only way a later read can tell that a claim's
    appropriateness has since been revoked. A cited id the section's own input does not hold is
    not recorded — there is no flag to remember — and the staleness check skips it in turn.
    """
    flags_by_id = {claim.claim_id: claim.outreach_safe for claim in section.claims}
    cost = draft.cost
    call: dict[str, Any] | None = None
    if cost is not None:
        call = {
            "ledger_row_id": cost.ledger_row_id,
            "raw_ref": cost.raw_ref,
            "raw_refs": list(draft.raw_refs),
        }
    return {
        "intro": list(draft.intro),
        "items": list(draft.items),
        "checks": dict(draft.checks),
        "cited_flags": {
            claim_id: flags_by_id[claim_id]
            for claim_id in draft.cited_claim_ids
            if claim_id in flags_by_id
        },
        "cost_usd": str(cost.cost_usd) if cost is not None and cost.cost_usd is not None else None,
        "call": call,
    }


# -- persistence ---------------------------------------------------------------------------------


_LIVE_SQL = text(
    """
    SELECT display_block_id, section_key, body_json, cited_claim_ids, model, prompt_version,
           recipe_version, generated_at
    FROM display_block
    WHERE workspace_id = :workspace_id
      AND subject_kind = :subject_kind
      AND subject_id = :subject_id
      AND page = :page
      AND superseded_at IS NULL AND context_id IS NULL
    """
)

_SUPERSEDE_ONE_SQL = text(
    """
    UPDATE display_block SET superseded_at = :now
    WHERE workspace_id = :workspace_id
      AND subject_kind = :subject_kind
      AND subject_id = :subject_id
      AND page = :page
      AND section_key = :section_key
      AND superseded_at IS NULL AND context_id IS NULL
    """
)

_SUPERSEDE_MANY_SQL = text(
    """
    UPDATE display_block SET superseded_at = :now
    WHERE workspace_id = :workspace_id
      AND subject_kind = :subject_kind
      AND subject_id = :subject_id
      AND page = :page
      AND section_key = ANY(CAST(:section_keys AS text[]))
      AND superseded_at IS NULL AND context_id IS NULL
    """
)

_INSERT_SQL = text(
    """
    INSERT INTO display_block
        (workspace_id, subject_kind, subject_id, page, section_key, body_json, cited_claim_ids,
         model, prompt_version, recipe_version, generated_at)
    VALUES
        (:workspace_id, :subject_kind, :subject_id, :page, :section_key,
         CAST(:body AS jsonb), CAST(:cited_claim_ids AS uuid[]),
         :model, :prompt_version, :recipe_version, :now)
    RETURNING display_block_id
    """
)


async def live_blocks(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_kind: str,
    subject_id: str,
    page: str,
) -> dict[str, LiveBlock]:
    """Every live block of one subject's page, keyed by section key."""
    rows = (
        await conn.execute(
            _LIVE_SQL,
            {
                "workspace_id": workspace_id,
                "subject_kind": subject_kind,
                "subject_id": uuid.UUID(subject_id),
                "page": page,
            },
        )
    ).mappings()
    return {
        row["section_key"]: LiveBlock(
            display_block_id=str(row["display_block_id"]),
            section_key=row["section_key"],
            body_json=decode_jsonb(row["body_json"]) or {},
            cited_claim_ids=tuple(str(claim_id) for claim_id in row["cited_claim_ids"]),
            model=row["model"],
            prompt_version=row["prompt_version"],
            recipe_version=row["recipe_version"],
            generated_at=row["generated_at"],
        )
        for row in rows
    }


async def insert_block(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_kind: str,
    subject_id: str,
    page: str,
    recipe: SectionRecipe,
    draft: SectionDraft,
    section: SectionInput,
    now: datetime,
) -> str:
    """Store ``draft`` as this section's live block, retiring whatever was live before it.

    Both statements run in the caller's transaction, so the live index can never see two rows: the
    retirement and the replacement land together or not at all.
    """
    scope = {
        "workspace_id": workspace_id,
        "subject_kind": subject_kind,
        "subject_id": uuid.UUID(subject_id),
        "page": page,
    }
    await conn.execute(_SUPERSEDE_ONE_SQL, {**scope, "section_key": recipe.section_key, "now": now})
    row = await conn.execute(
        _INSERT_SQL,
        {
            **scope,
            "section_key": recipe.section_key,
            "body": json.dumps(block_body(draft, section)),
            "cited_claim_ids": [uuid.UUID(claim_id) for claim_id in draft.cited_claim_ids],
            "model": draft.model,
            "prompt_version": prompt_version_of(recipe),
            "recipe_version": RECIPE_VERSION,
            "now": now,
        },
    )
    return str(row.scalar_one())


async def supersede_blocks(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_kind: str,
    subject_id: str,
    page: str,
    section_keys: Sequence[str],
    now: datetime,
) -> int:
    """Retire the live blocks of ``section_keys``; returns how many rows were actually retired."""
    keys = list(section_keys)
    if not keys:
        return 0
    result = await conn.execute(
        _SUPERSEDE_MANY_SQL,
        {
            "workspace_id": workspace_id,
            "subject_kind": subject_kind,
            "subject_id": uuid.UUID(subject_id),
            "page": page,
            "section_keys": keys,
            "now": now,
        },
    )
    return result.rowcount


# -- staleness -----------------------------------------------------------------------------------


_NEW_CLAIMS_SQL = text(
    """
    SELECT EXISTS (
        SELECT 1 FROM claim
        WHERE entity_id = ANY(CAST(:entity_ids AS uuid[]))
          AND field_key = ANY(CAST(:field_keys AS text[]))
          AND workspace_id = :workspace_id
          AND superseded_by IS NULL
          AND collected_at > :generated_at
    )
    """
)

_CITED_STATE_SQL = text(
    """
    SELECT id, (superseded_by IS NOT NULL) AS superseded, outreach_safe
    FROM claim
    WHERE id = ANY(CAST(:claim_ids AS uuid[])) AND workspace_id = :workspace_id
    """
)


async def _cited_state(
    conn: AsyncConnection, *, workspace_id: str, claim_ids: Sequence[str]
) -> dict[str, tuple[bool, bool]]:
    """``claim_id -> (superseded, outreach_safe)`` for every cited claim, in one query."""
    if not claim_ids:
        return {}
    rows = (
        await conn.execute(
            _CITED_STATE_SQL,
            {
                "claim_ids": [uuid.UUID(claim_id) for claim_id in claim_ids],
                "workspace_id": workspace_id,
            },
        )
    ).mappings()
    return {str(row["id"]): (row["superseded"], row["outreach_safe"]) for row in rows}


async def stale_sections(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_ids: Sequence[str],
    recipes: Sequence[SectionRecipe],
    blocks: Mapping[str, LiveBlock],
) -> list[Staleness]:
    """Every section whose live block no longer matches the research or the recipe behind it.

    Only sections that *have* a live block are examined: a section nobody has written is not
    stale, it is unwritten, and the caller already knows the difference. The result is in recipe
    order, and a section with no reason is absent rather than present-and-empty.

    A recipe with ``shared_from`` owns no block, so it is never examined here: it is stale exactly
    when its owner is, and its owner's page is where that is scanned and repaired.
    """
    written = [
        recipe for recipe in recipes if recipe.shared_from is None and recipe.section_key in blocks
    ]
    if not written:
        return []

    entity_ids = [uuid.UUID(subject_id) for subject_id in subject_ids]
    cited_everywhere = list(
        dict.fromkeys(
            claim_id
            for recipe in written
            for claim_id in blocks[recipe.section_key].cited_claim_ids
        )
    )
    state = await _cited_state(conn, workspace_id=workspace_id, claim_ids=cited_everywhere)

    stale: list[Staleness] = []
    for recipe in written:
        block = blocks[recipe.section_key]
        reasons: list[str] = []

        if entity_ids and recipe.allowed_field_keys:
            found = await conn.execute(
                _NEW_CLAIMS_SQL,
                {
                    "entity_ids": entity_ids,
                    "field_keys": list(recipe.allowed_field_keys),
                    "workspace_id": workspace_id,
                    "generated_at": block.generated_at,
                },
            )
            if found.scalar_one():
                reasons.append("new_claims")

        cited = block.cited_claim_ids
        if any(claim_id in state and state[claim_id][0] for claim_id in cited):
            reasons.append("superseded_citation")

        recorded = block.body_json.get("cited_flags")
        flags = recorded if isinstance(recorded, dict) else {}
        if any(
            claim_id in state and claim_id in flags and state[claim_id][1] != flags[claim_id]
            for claim_id in cited
        ):
            reasons.append("flag_changed")

        if block.prompt_version != prompt_version_of(recipe):
            reasons.append("prompt_version")
        if block.recipe_version != RECIPE_VERSION:
            reasons.append("recipe_version")

        if reasons:
            stale.append(Staleness(section_key=recipe.section_key, reasons=tuple(reasons)))
    return stale


# -- composition ---------------------------------------------------------------------------------


def _stored_list(block: LiveBlock | None, key: str) -> list[Any]:
    if block is None:
        return []
    stored = block.body_json.get(key)
    return list(stored) if isinstance(stored, list) else []


async def shared_blocks(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    page: str,
    recipes: Sequence[SectionRecipe],
    subject_id: str,
    member_ids: Sequence[str],
) -> dict[str, list[LiveBlock]]:
    """For every recipe of ``page`` with ``shared_from``, the owner's live blocks, in the order
    the sharer renders them: the same subject when the owner page is about the sharer's subject
    kind, else one per committee member (committee order). A member with no owner block
    contributes nothing."""
    out: dict[str, list[LiveBlock]] = {}
    for recipe in recipes:
        if recipe.shared_from is None:
            continue
        owner_page, owner_key = recipe.shared_from
        owner_kind = PAGE_SUBJECT_KIND[owner_page]
        subjects = [subject_id] if owner_kind == PAGE_SUBJECT_KIND[page] else list(member_ids)
        found: list[LiveBlock] = []
        for owner_subject in subjects:
            blocks = await live_blocks(
                conn,
                workspace_id=workspace_id,
                subject_kind=owner_kind,
                subject_id=owner_subject,
                page=owner_page,
            )
            block = blocks.get(owner_key)
            if block is not None:
                found.append(block)
        out[recipe.section_key] = found
    return out


def compose_display_block(
    page: str,
    recipes: Sequence[SectionRecipe],
    blocks: Mapping[str, LiveBlock],
    shared: Mapping[str, Sequence[LiveBlock]] = {},  # noqa: B006 — read-only default
) -> dict[str, Any]:
    """The stored page, in recipe order, in the shape the frontend receives.

    Items pass through exactly as they were stored — they were already wire-shaped when the runner
    materialised them, and re-shaping them here would be a second place for the contract to drift.
    A section with no block is ``empty``, and so is a block that said nothing; the page grammar is
    fixed either way, so every section is served whether or not it has words in it.

    A recipe with ``shared_from`` has no block of its own: its items are the concatenated items of
    the owner blocks ``shared`` carries for it, rendered under *this* page's ``h1``, ``restricted``
    and ``defaultOpen``. An intro is only carried through when exactly one owner block answers for
    the section — several people's prose run together is not an introduction to anything.
    """
    sections: list[dict[str, Any]] = []
    for recipe in recipes:
        if recipe.shared_from is not None:
            owners = list(shared.get(recipe.section_key, ()))
            items = [item for owner in owners for item in _stored_list(owner, "items")]
            intro = _stored_list(owners[0], "intro") if len(owners) == 1 else []
        else:
            block = blocks.get(recipe.section_key)
            items = _stored_list(block, "items")
            intro = _stored_list(block, "intro")
        section: dict[str, Any] = {
            "key": recipe.section_key,
            "h1": recipe.h1,
            "empty": not items and not intro,
            "items": items,
        }
        if recipe.narrative:
            section["intro"] = intro
        section["restricted"] = recipe.restricted
        section["defaultOpen"] = recipe.default_open
        sections.append(section)
    return {"page": page, "sections": sections}


def cited_claim_ids(
    recipes: Sequence[SectionRecipe],
    blocks: Mapping[str, LiveBlock],
    shared: Mapping[str, Sequence[LiveBlock]] = {},  # noqa: B006 — read-only default
) -> tuple[str, ...]:
    """Every claim the composed page cites, in recipe order, deduped.

    A shared section contributes every owner block's citations: the page shows those words, so it
    must offer their evidence, and the evidence drawer is keyed on the ids this returns.
    """

    def _of(recipe: SectionRecipe) -> tuple[str, ...]:
        if recipe.shared_from is not None:
            return tuple(
                claim_id
                for owner in shared.get(recipe.section_key, ())
                for claim_id in owner.cited_claim_ids
            )
        block = blocks.get(recipe.section_key)
        return block.cited_claim_ids if block is not None else ()

    return tuple(dict.fromkeys(claim_id for recipe in recipes for claim_id in _of(recipe)))


def insight_summary(display_block: Mapping[str, Any], committee_size: int) -> list[str]:
    """The page's two-line header count: shown insights, and the people they are about.

    Restricted sections are excluded on purpose — a watch-out is context the marketer must not use,
    so counting it as an insight would overstate what the page actually offers.
    """
    sections = display_block.get("sections")
    rows = sections if isinstance(sections, list) else []
    insights = sum(
        len(section.get("items", []))
        for section in rows
        if isinstance(section, Mapping) and not section.get("restricted", False)
    )
    return [f"{insights} insights", f"{committee_size} people"]
