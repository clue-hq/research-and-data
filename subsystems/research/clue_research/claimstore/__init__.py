"""`clue_research.claimstore` — Claim Store & Merge Policy (M1).

The spine of the subsystem: the append-only typed-claim-with-provenance substrate every other
component reads from and writes to (substrate §0/§1). This package is the *only* shared substrate;
components communicate by reading/writing typed claims here, never by importing each other, and
workers return claim-id references, not blobs (conventions §2).

The public seam (the contract callers depend on; the Postgres implementation stays hidden):

* **write** — :func:`insert_claim`, :func:`supersede_claim` (M1.1). The only sanctioned write path.
* **raw read** — :func:`claims_for` (M1.1): append-only history for audit / time-travel.
* **merge read** — :func:`current_value`, :func:`current_values`, :func:`provenance_index` (M1.2):
  the deterministic "current truth" the rest of the platform reads.
* **field registry** — :func:`register_field`, :func:`get_field`, :func:`list_fields`,
  :func:`validate_value`, :func:`load_core_pack` (M1.3): the field set as data, not code.

Implements M1 (docs/specs/M01-claim-store-and-merge-policy.md). Imports only ``core`` and ``db``
from within ``clue_research`` (it is not a worker; conventions §2 / import-linter).
"""

from __future__ import annotations

from clue_core import (
    canonical_json,
)  # re-export: relocated to core (the equality contract)
from clue_research.claimstore.claims import (
    claims_by_ids,
    claims_for,
    claims_for_entities,
    claims_for_runs,
    entities_with_field_claim,
    insert_claim,
    record_verification,
    supersede_claim,
    supersede_claims,
)
from clue_research.claimstore.derivations import (
    DerivationDependencyResolution,
    DerivationDependencyResolver,
    DerivationDependencyState,
    DerivationSetRef,
    DerivationStore,
    DerivationValidationError,
    affected_derivations,
    derivation_supports,
    derivation_supports_batch,
    support_set_sha256,
)
from clue_research.claimstore.entailment_identity import (
    ENTAILMENT_JUDGMENT_NAMESPACE,
    SOURCE_CLIENT_INTERVIEW_JUDGED,
    FaithfulnessLookupPlan,
    FaithfulnessSubjectIdentityError,
    entailment_judgment_id,
    faithfulness_lookup_plan,
    faithfulness_redaction_subject_ids,
)
from clue_research.claimstore.faithfulness_attribution import (
    METRIC_FAITHFULNESS_SUBJECT_IDENTITY_ERRORS,
    FaithfulnessAttribution,
    read_faithfulness_attributions,
    redact_faithfulness_rationale,
)
from clue_research.claimstore.merge import (
    DEFAULT_MERGE_POLICY,
    FreshnessMode,
    MergePolicy,
    active_merge_policy,
    current_value,
    current_values,
    merge_claims,
    provenance_index,
)
from clue_research.claimstore.packs import (
    CORE_PACK,
    SeedField,
    load_core_pack,
    load_pack,
)
from clue_research.claimstore.registry import (
    CorroborationConfig,
    FieldFilters,
    FieldRedefinitionError,
    FieldRegistryOrigin,
    FieldRegistryScope,
    ProductScopeError,
    ResearchFieldInputError,
    ResearchFieldKeyTaken,
    ResearchScopeError,
    ResolvedFieldDefinition,
    ReuseScopeError,
    UnknownFieldError,
    ValueSchemaError,
    WorkspaceDynamicClientKbErasedError,
    WorkspaceFieldDefinitionError,
    WorkspaceFieldRetiredError,
    assert_workspace_dynamic_client_kb_active,
    check_claim_writable,
    field_species,
    get_corroboration_config,
    get_effective_field,
    get_field,
    get_workspace_field,
    list_effective_fields,
    list_fields,
    list_research_fields,
    register_field,
    register_workspace_field,
    register_workspace_research_field,
    retire_workspace_field,
    update_workspace_research_field,
    validate_effective_value,
    validate_value,
    validate_value_against_schema,
    validate_workspace_field_schema,
    workspace_dynamic_client_kb_is_erased,
)
from clue_research.claimstore.research_view_queries import (
    ResolvedCurrentClaim,
    current_field_claims_resolved_for_product,
    current_values_resolved_for_product,
    live_derived_claims_for_research_view,
)
from clue_research.claimstore.research_view_routes import (
    ResearchRouteContext,
    ResearchRouteProductMode,
    ResearchRoutePurpose,
    ResearchViewFieldRoute,
    ResearchViewRouteRedefinitionError,
    list_research_view_routes,
    register_research_view_route,
)
from clue_research.claimstore.run_lineage import (
    RUN_LINEAGE_KINDS,
    project_run_ids,
    project_supersedable,
    record_run_lineage,
    runs_for_project_run,
)
from clue_research.claimstore.tenancy import ALL_WORKSPACES, PUBLIC_ONLY, WorkspaceScope

__all__ = [
    # write contract (M1.1)
    "insert_claim",
    "supersede_claim",
    "supersede_claims",
    "claims_for",
    "claims_for_entities",
    "claims_by_ids",
    "claims_for_runs",
    "entities_with_field_claim",
    # verification verdict write (M9.2 — in-place on the trigger-allowlisted columns)
    "record_verification",
    # C7.2 immutable claim-support substrate
    "DerivationStore",
    "DerivationSetRef",
    "DerivationValidationError",
    "DerivationDependencyResolver",
    "DerivationDependencyResolution",
    "DerivationDependencyState",
    "support_set_sha256",
    "derivation_supports",
    "derivation_supports_batch",
    "affected_derivations",
    # merge / current truth (M1.2)
    "current_value",
    "current_values",
    "provenance_index",
    "merge_claims",
    "MergePolicy",
    "FreshnessMode",
    "DEFAULT_MERGE_POLICY",
    "active_merge_policy",
    "canonical_json",
    # entailment-question identity (PC-C8 §6c-b) — one definition three packages agree on
    "ENTAILMENT_JUDGMENT_NAMESPACE",
    "SOURCE_CLIENT_INTERVIEW_JUDGED",
    "FaithfulnessLookupPlan",
    "FaithfulnessSubjectIdentityError",
    "entailment_judgment_id",
    "faithfulness_lookup_plan",
    "faithfulness_redaction_subject_ids",
    "FaithfulnessAttribution",
    "read_faithfulness_attributions",
    "redact_faithfulness_rationale",
    "METRIC_FAITHFULNESS_SUBJECT_IDENTITY_ERRORS",
    # tenant scoping (M2.5)
    "WorkspaceScope",
    "PUBLIC_ONLY",
    "ALL_WORKSPACES",
    # field registry (M1.3)
    "register_field",
    "register_workspace_field",
    "get_field",
    "get_workspace_field",
    "get_effective_field",
    "list_fields",
    "field_species",
    "list_effective_fields",
    "validate_value",
    "validate_effective_value",
    "validate_value_against_schema",
    "validate_workspace_field_schema",
    "check_claim_writable",
    "retire_workspace_field",
    "FieldRegistryOrigin",
    "FieldRegistryScope",
    "ResearchFieldInputError",
    "ResearchFieldKeyTaken",
    "list_research_fields",
    "register_workspace_research_field",
    "update_workspace_research_field",
    "FieldFilters",
    "ResolvedFieldDefinition",
    # corroboration config reader (M9.2)
    "get_corroboration_config",
    "CorroborationConfig",
    "load_pack",
    "load_core_pack",
    "CORE_PACK",
    "SeedField",
    "UnknownFieldError",
    "ValueSchemaError",
    "FieldRedefinitionError",
    "ReuseScopeError",
    "ProductScopeError",
    "ResearchScopeError",
    "WorkspaceFieldDefinitionError",
    "WorkspaceDynamicClientKbErasedError",
    "WorkspaceFieldRetiredError",
    "assert_workspace_dynamic_client_kb_active",
    "workspace_dynamic_client_kb_is_erased",
    # C7 registered semantic field placement
    "ResearchViewFieldRoute",
    "ResearchViewRouteRedefinitionError",
    "ResearchRoutePurpose",
    "ResearchRouteContext",
    "ResearchRouteProductMode",
    "register_research_view_route",
    "list_research_view_routes",
    "ResolvedCurrentClaim",
    "current_field_claims_resolved_for_product",
    "current_values_resolved_for_product",
    "live_derived_claims_for_research_view",
    # FI-2 P2 run→project lineage
    "RUN_LINEAGE_KINDS",
    "record_run_lineage",
    "project_run_ids",
    "runs_for_project_run",
    "project_supersedable",
]
