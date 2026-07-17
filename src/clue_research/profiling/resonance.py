"""`account.resonance.*` collectors (M8.2 part-2) — the resonance aspect of M8.1's converge loop.

The resonance layer is the account's emotional/cultural texture — employee sentiment, morale /
attrition signals, engineering-blog tone, public frustrations, procurement culture (Doc C §2). The
field-class is already registered (the tiny seed, :mod:`clue_research.profiling.fields`); this
module
is the **collector**: a thin specialisation of :class:`~clue_research.profiling.aspect_worker.
AspectProfilingWorker` that the graph dispatches for the ``account.resonance`` field-class cluster.

Two things make resonance its own issue rather than a plain account aspect:

* **Source emphasis.** Resonance is tier-4 by nature and modality-heavy — review sites, blogs,
  social. The collector consults the Source Planner over the full tier band (tier-3 reputable review
  / news first, tier-4 synthesis last). Today only the tier-4 synthesis placeholders are registered
  (``exa_deep`` / ``parallel_task``, resolver-absent until M11) and the tier-3 review/news source
  *weighting* is M3.3 work — so resonance correctly populates **empty/flagged** until those land
  (the waterfall returns ``no_resolver``, never a crash; M8.2 AC: "left empty and flagged, not
  fabricated").
* **The sensitivity firewall.** Account resonance is account-level, *not* personal — so it carries
no
  ``use_class`` / ``identity_binding`` obligation. But a resonance value must never smuggle a *named
  individual's special-category attribute* (a person's religion/health/politics); that data belongs
  to ``contact.facet.*`` and the M10 use-gate. The field-def ``validation`` **declares** this
  firewall (the seed's ``_RESONANCE_FIREWALL``); :func:`resonance_firewall_ok` **enforces** it at
  collection time (M8.2 AC6), dropping such a value from the aspect's output.
"""

from __future__ import annotations

import json
import re

from clue_core import (
    AspectContext,
    CampaignRunId,
    Claim,
    CostCents,
    EntityId,
    FieldClass,
    LLMGateway,
    PreSpendGate,
    ResearchMode,
    RunId,
    WorkerResult,
    new_campaign_run_id,
)
from clue_research.config import OverlayStore
from clue_research.db import ConnFactory, transaction
from clue_research.profiling.aspect_worker import (
    DEEP_PROFILING_PLANNER_CONFIG,
    AspectProfilingWorker,
    SynthesisGuard,
)
from clue_research.profiling.context import RunContext, params_for_run
from clue_research.profiling.fields import RESONANCE_FIELD_KEYS
from clue_research.sources import SourcePlannerConfig

# --- the sensitivity firewall (M8.2 AC6) -----------------------------------
# Special-category (Doc D "sensitive") signal terms. The firewall fires only when such a term
# co-occurs with a *named individual* reference — an account-level mention of "morale" or
# "attrition"
# is fine; "CEO Jane Doe's cancer treatment" is not (that is personal special-category data → routes
# to contact.facet.* / M10). Erring toward routing an ambiguous case away from resonance is the safe
# direction (an empty resonance field is a correct output; a smuggled personal attribute is not).
_SPECIAL_CATEGORY_TERMS: frozenset[str] = frozenset(
    {
        # health / disability
        "health",
        "illness",
        "disease",
        "diagnosis",
        "disability",
        "medical",
        "mental health",
        "depression",
        "cancer",
        "addiction",
        "pregnancy",
        # religion / belief
        "religion",
        "religious",
        "church",
        "mosque",
        "synagogue",
        "catholic",
        "muslim",
        "jewish",
        "christian",
        "hindu",
        "buddhist",
        "atheist",
        # sexual orientation
        "sexual orientation",
        "gay",
        "lesbian",
        "lgbt",
        "lgbtq",
        "transgender",
        "bisexual",
        # political opinion / union membership
        "political party",
        "democrat",
        "republican",
        "union membership",
        # racial / ethnic origin
        "ethnicity",
        "ethnic origin",
        "racial",
        "race",
    }
)

# A named-individual signal: a person title followed by a Capitalised name, or a possessive proper
# name ("Jane Doe's"). Deliberately conservative — it is a *firewall*, not a classifier.
_PERSON_TITLE_RE = re.compile(
    r"\b(?:mr|mrs|ms|dr|prof|ceo|cto|cfo|coo|vp|svp|evp|founder|chief|director|head|manager|"
    r"president)\b\.?\s+[A-Z][a-z]+",
    re.IGNORECASE,
)
_POSSESSIVE_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}'s\b")


def _names_an_individual(text: str) -> bool:
    return bool(_PERSON_TITLE_RE.search(text) or _POSSESSIVE_NAME_RE.search(text))


def _has_special_category(text_lower: str) -> bool:
    return any(term in text_lower for term in _SPECIAL_CATEGORY_TERMS)


def resonance_firewall_ok(claim: Claim) -> bool:
    """Whether a resonance claim is clear of the named-individual special-category firewall (M8.2
    AC6).

    Returns ``False`` (reject) when the claim's value (or its evidence span) both names an
    individual
    **and** carries a special-category attribute — that is personal special-category data
    masquerading
    as account resonance; it belongs to ``contact.facet.*`` / M10, not here. An account-scoped value
    (sentiment, morale, frustrations) with no named individual, or a named individual with no
    special-category attribute, passes."""
    parts: list[str] = []
    try:
        parts.append(json.dumps(claim.value_json, default=str))
    except (TypeError, ValueError):
        parts.append(str(claim.value_json))
    if claim.evidence_span:
        parts.append(claim.evidence_span)
    text = " ".join(parts)
    if not text.strip():
        return True
    return not (_names_an_individual(text) and _has_special_category(text.lower()))


# --- the resonance aspect worker (M8.2) ------------------------------------


class ResonanceAspectWorker(AspectProfilingWorker):
    """The ``account.resonance`` aspect worker (M8.2) — an :class:`AspectProfilingWorker` with the
    sensitivity firewall as its ``claim_filter`` and the full tier band as its planner scope.

    Registered into M7's ``WorkerRegistry`` under ``"account.resonance"`` (the field-class key the
    graph clusters resonance gaps into) — see ``api/composition.py`` (``build_profiling_workers``).
    Because ``account.resonance``
    is a recursion-eligible class (``config.RecursionPolicy.eligible_classes``), the graph *may* let
    this aspect spawn facet sub-workers; M8.2 does not require them (a single-level fill is
    correct),
    so it requests none — the richer per-source facet fan-out is a later optimisation."""

    def __init__(
        self,
        *,
        session_factory: ConnFactory = transaction,
        planner_config: SourcePlannerConfig = DEEP_PROFILING_PLANNER_CONFIG,
        gateway: LLMGateway | None = None,
        planner_model: str | None = None,
        pre_spend_gate: PreSpendGate | None = None,
        synthesis_guard: SynthesisGuard | None = None,
        config_store: OverlayStore | None = None,
    ) -> None:
        super().__init__(
            FieldClass.ACCOUNT_RESONANCE.value,  # "account.resonance" — the graph's cluster key
            session_factory=session_factory,
            mode=ResearchMode.ACCOUNT_PROFILING,
            # Full tier band: tier-3 reputable review/news first, tier-4 synthesis last (Doc C §2).
            # ``tier_scope=None`` already spans every tier, so the config's ``prefer_deep_sources``
            # is a no-op here unless an overlay sets a finite ``tier_scope`` to cap cost.
            tier_scope=None,
            planner_config=planner_config,
            gateway=gateway,
            planner_model=planner_model,
            pre_spend_gate=pre_spend_gate,
            synthesis_guard=synthesis_guard,
            claim_filter=resonance_firewall_ok,
            config_store=config_store,
        )


async def collect_resonance(
    *,
    account_entity_id: EntityId,
    run_id: RunId,
    tier: str,
    client_id: str | None = None,
    icp_key: str | None = None,
    icp_version: int | None = None,
    tenant_id: str | None = None,
    field_keys: tuple[str, ...] = RESONANCE_FIELD_KEYS,
    budget_envelope_cents: CostCents | None = None,
    worker: ResonanceAspectWorker | None = None,
    campaign_run_id: CampaignRunId | None = None,
) -> WorkerResult:
    """Run the resonance collector for one account and return its :class:`WorkerResult` (M8.2 seam).

    The directly-callable form of the resonance aspect (the spec's ``collect_resonance``): builds an
    :class:`~clue_core.AspectContext` over the resonance field set and invokes
    :class:`ResonanceAspectWorker`. ``profile_account`` (M8.1) drives the same worker as the
    ``account.resonance`` cluster; this entrypoint lets M8.2 be exercised on its own. Returns the
    worker result (claim refs + coverage); ``result.claim_refs`` is the ``list[claim_ref]`` the spec
    names."""
    resonance_worker = worker if worker is not None else ResonanceAspectWorker()
    ctx = AspectContext(
        entity_id=account_entity_id,
        campaign_run_id=campaign_run_id if campaign_run_id is not None else new_campaign_run_id(),
        run_id=run_id,
        tier=tier,
        aspect=resonance_worker.aspect,
        field_keys=field_keys,
        budget_envelope_cents=budget_envelope_cents,
        params=params_for_run(
            client_id=client_id, icp_key=icp_key, icp_version=icp_version, tenant_id=tenant_id
        ),
    )
    return await resonance_worker.research(ctx)


# Keep RunContext importable here too (resonance collectors read the same coordinates).
__all__ = [
    "ResonanceAspectWorker",
    "resonance_firewall_ok",
    "collect_resonance",
    "RunContext",
]
