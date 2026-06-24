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

from clue_research.claimstore.claims import (
    claims_by_ids,
    claims_for,
    entities_with_field_claim,
    insert_claim,
    record_verification,
    supersede_claim,
)
from clue_research.claimstore.merge import (
    DEFAULT_MERGE_POLICY,
    FreshnessMode,
    MergePolicy,
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
    FieldRedefinitionError,
    ReuseScopeError,
    UnknownFieldError,
    ValueSchemaError,
    check_claim_writable,
    get_corroboration_config,
    get_field,
    list_fields,
    register_field,
    validate_value,
)
from clue_research.claimstore.tenancy import ALL_TENANTS, PUBLIC_ONLY, TenantScope
from clue_research.core import (
    canonical_json,
)  # re-export: relocated to core (the equality contract)

__all__ = [
    # write contract (M1.1)
    "insert_claim",
    "supersede_claim",
    "claims_for",
    "claims_by_ids",
    "entities_with_field_claim",
    # verification verdict write (M9.2 — in-place on the trigger-allowlisted columns)
    "record_verification",
    # merge / current truth (M1.2)
    "current_value",
    "current_values",
    "provenance_index",
    "merge_claims",
    "MergePolicy",
    "FreshnessMode",
    "DEFAULT_MERGE_POLICY",
    "canonical_json",
    # tenant scoping (M2.5)
    "TenantScope",
    "PUBLIC_ONLY",
    "ALL_TENANTS",
    # field registry (M1.3)
    "register_field",
    "get_field",
    "list_fields",
    "validate_value",
    "check_claim_writable",
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
]
