"""Canonicalization — choosing the surviving record's fields when two are confirmed the same (M2.2).

When resolution confirms two records are one entity, *canonicalization* decides the surviving
record: the best ``canonical_name`` / ``primary_domain`` / ``hq_geo`` and the union of ``aliases`` /
``registry_ids`` (substrate §2). These are **pure functions** — M2.2 computes the plan; **M2.3's
auto-merge path performs the actual write** (via ``entities.update_account`` + ``mark_merged``),
because the write commits identity and belongs on the merge-decision seam.

Keeping these pure and separate means the canonicalization rule (prefer the longer name, keep the
survivor's strong key unless it is missing, union the rest) is swappable and testable without a DB.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_research.core import AccountEntity


class CanonicalPlan(BaseModel):
    """Fields to set on the survivor to absorb the loser (input to ``entities.update_account``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_name: str | None = None  # set only if the loser's name is preferred
    primary_domain: str | None = None  # set only if the survivor lacked one and the loser had it
    add_aliases: tuple[str, ...] = ()
    add_registry_ids: dict[str, str] = {}
    hq_geo: dict[str, JsonValue] | None = None  # set only if the survivor lacked one


def _prefer_name(survivor_name: str, loser_name: str) -> str | None:
    """Prefer the more informative name (more tokens, then longer). Returns the loser's name only
    when it is strictly preferred (so the caller writes it), else ``None`` (keep the survivor's)."""
    s_tokens, l_tokens = survivor_name.split(), loser_name.split()
    if (len(l_tokens), len(loser_name)) > (len(s_tokens), len(survivor_name)):
        return loser_name
    return None


def plan_merge(survivor: AccountEntity, loser: AccountEntity) -> CanonicalPlan:
    """Compute the canonicalization plan to fold ``loser`` into ``survivor`` (account entities).

    The survivor keeps its identity and strong keys; it only *gains* what the loser adds: the
    loser's name/aliases become aliases (so future lookups still hit), the loser's
    ``primary_domain`` / ``hq_geo`` fill a gap if the survivor lacked one, and ``registry_ids``
    union (survivor wins on a key collision — its id is authoritative). A better name is adopted.
    """
    add_aliases = (loser.canonical_name, *loser.aliases)
    return CanonicalPlan(
        canonical_name=_prefer_name(survivor.canonical_name, loser.canonical_name),
        primary_domain=(
            loser.primary_domain
            if survivor.primary_domain is None and loser.primary_domain is not None
            else None
        ),
        add_aliases=add_aliases,
        add_registry_ids=dict(loser.registry_ids),
        hq_geo=(loser.hq_geo if survivor.hq_geo is None else None),
    )
