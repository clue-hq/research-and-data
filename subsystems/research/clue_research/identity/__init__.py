"""`clue_research.identity` — Identity Resolution (M2).

The **front door** of the subsystem (substrate §2): the only component allowed to turn a free-text
name into a resolved ``entity_id``. Everything else keys on the ids this package returns and never
re-implements matching (conventions §2). The standard entity-resolution discipline —
*deduplicate → record-link → canonicalize* — lands here as a first-class service.

The public seam (M2.1 — the entity store):

* **entity store** — :func:`insert_account_entity`, :func:`insert_contact_entity`,
  :func:`get_account`, :func:`get_contact`, :func:`get_entity`, :func:`resolve_alias` (exact
  strong-key / normalized-alias lookup), :func:`surviving_id` (the ``merged_into`` chain resolver),
  and the canonicalization/lifecycle writers :func:`update_account`, :func:`set_status`,
  :func:`mark_merged`.
* **normalizers** — the deterministic folding rules (:func:`registrable_domain`,
  :func:`normalize_name`, :func:`name_key`, :func:`canonical_registry_id`) shared with M2.2's
  deterministic stage.

Implements M2 (docs/specs/M02-identity-resolution.md). Persistence follows the claim store's seam
style: callers pass an ``AsyncConnection``; no business SQL lives in ``db/``.
"""

from __future__ import annotations

from clue_research.identity.canonicalize import CanonicalPlan, plan_merge
from clue_research.identity.embedding import (
    DEFAULT_EMBEDDER,
    DEFAULT_MODEL_VERSION,
    EMBEDDING_DIM,
    Embedder,
    HashingEmbedder,
    embed_account,
    vector_literal,
)
from clue_research.identity.entities import (
    CrossWorkspaceMergeError,
    MergeCycleError,
    UnknownEntityTypeError,
    canonical_member_ids,
    contact_ids_for_account,
    get_account,
    get_accounts,
    get_contact,
    get_contacts,
    get_entity,
    insert_account_entity,
    insert_contact_entity,
    mark_merged,
    resolve_alias,
    set_status,
    surviving_id,
    surviving_ids,
    update_account,
)
from clue_research.identity.normalize import (
    NORMALIZER_VERSION,
    canonical_registry_id,
    fold_unicode,
    name_key,
    normalize_name,
    registrable_domain,
    strip_legal_suffix,
)
from clue_research.identity.policy import (
    DEFAULT_DISPOSITION_POLICY,
    DEFAULT_RESOLUTION_POLICY,
    DEFAULT_REUSE_POLICY,
    DispositionPolicy,
    ResolutionPolicy,
    ReusePolicy,
    ScorerWeights,
    assert_fuzzy_cannot_auto_merge,
    max_fuzzy_score,
)
from clue_research.identity.resolve import (
    Candidate,
    Observation,
    ResolutionMethod,
    ResolutionResult,
    resolve,
    resolve_many,
)
from clue_research.identity.reuse import (
    classify_reuse_scope,
    dsar_private_claims,
    stamp_reuse,
)
from clue_research.identity.review import (
    Disposition,
    DispositionKind,
    DispositionOutcome,
    MergeConflictError,
    ReviewDecision,
    ReviewResolution,
    ReviewStatus,
    ReviewTask,
    ReviewTaskUnscopedError,
    auto_merge,
    current_value_resolved,
    disposition,
    enqueue_review_task,
    get_dispositions,
    get_review_decision,
    get_task,
    list_open_tasks,
    merged_member_ids,
    record_disposition,
    resolve_create_new_entity,
    resolve_merge_into,
    resolve_not_a_match,
    split_merge,
)

__all__ = [
    # entity store (M2.1)
    "insert_account_entity",
    "insert_contact_entity",
    "update_account",
    "set_status",
    "mark_merged",
    "get_account",
    "get_accounts",
    "get_contact",
    "get_contacts",
    "canonical_member_ids",
    "contact_ids_for_account",
    "get_entity",
    "resolve_alias",
    "surviving_id",
    "surviving_ids",
    "MergeCycleError",
    "UnknownEntityTypeError",
    "CrossWorkspaceMergeError",
    # normalizers (M2.1, shared with M2.2)
    "registrable_domain",
    "normalize_name",
    "strip_legal_suffix",
    "name_key",
    "canonical_registry_id",
    "fold_unicode",
    "NORMALIZER_VERSION",
    # resolution engine (M2.2)
    "resolve",
    "resolve_many",
    "Observation",
    "Candidate",
    "ResolutionResult",
    "ResolutionMethod",
    "ResolutionPolicy",
    "ScorerWeights",
    "DEFAULT_RESOLUTION_POLICY",
    # auto-merge + review queue (M2.3)
    "disposition",
    "Disposition",
    "DispositionOutcome",
    "DispositionKind",
    "DispositionPolicy",
    "DEFAULT_DISPOSITION_POLICY",
    "assert_fuzzy_cannot_auto_merge",
    "max_fuzzy_score",
    "auto_merge",
    "enqueue_review_task",
    "get_task",
    "get_review_decision",
    "list_open_tasks",
    "resolve_merge_into",
    "resolve_create_new_entity",
    "resolve_not_a_match",
    "split_merge",
    "record_disposition",
    "get_dispositions",
    "merged_member_ids",
    "current_value_resolved",
    "ReviewTask",
    "ReviewDecision",
    "ReviewStatus",
    "ReviewResolution",
    "ReviewTaskUnscopedError",
    "MergeConflictError",
    # reuse-scope privacy classification + isolation (M2.5; cross-tenant amortization retired
    # [B3×research] 2026-07-23 — accounts are workspace-local)
    "classify_reuse_scope",
    "stamp_reuse",
    "dsar_private_claims",
    "ReusePolicy",
    "DEFAULT_REUSE_POLICY",
    # embedding (M2.2)
    "Embedder",
    "HashingEmbedder",
    "DEFAULT_EMBEDDER",
    "DEFAULT_MODEL_VERSION",
    "EMBEDDING_DIM",
    "embed_account",
    "vector_literal",
    # canonicalization (M2.2; M2.3 applies the write)
    "CanonicalPlan",
    "plan_merge",
]
