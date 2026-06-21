"""Cross-tenant reuse policy for client-knowledge claims (M5.1).

Reverse-profiling writes claims about the **client themselves** — value prop, differentiators,
proof points, pricing posture, ideal-customer evidence — under the ``client.*`` namespace. These are
**client-knowledge / ICP-derived** data: per the project's tenant-isolation rule (CLAUDE.md backlog
``[M2×M6/M8]`` and substrate §2) any claim derived from client-knowledge must be classified
``tenant_private`` so a client-tuned fact never leaks into the cross-tenant *public* base.

**The authoritative declaration is on the field** (ENG-165): every ``client.*`` field declares
``reuse_scope=TENANT_PRIVATE`` (see :mod:`clue_research.stage0.fields`), and the claim-write
boundary (``claimstore.check_claim_writable``) is fail-closed — it refuses to write a client claim
stamped ``public_footprint`` and refuses an undeclared ``<pack>.*`` field outright. The backstop.

This policy is the **stamping** side of the same fact: the M4 waterfall and direct
``identity.stamp_reuse`` calls classify a claim's scope from a :class:`ReusePolicy` via the
namespace-prefix heuristic, and they are *not yet field-aware* (threading ``FieldDef.reuse_scope``
into the waterfall's stamp is a tracked follow-up). M2's default
:data:`~clue_research.identity.DEFAULT_REUSE_POLICY` has no ``client.`` prefix, so a default stamp
would mark a client claim ``public_footprint`` — which the write boundary would then *reject*
(mismatch with the field's declared ``tenant_private``). Rather than mutate the shared M2 default (a
change every branch would inherit), M5 layers a stage0-local policy that adds the ``client.`` prefix
— *policy is data* (conventions §2) — so every client claim M5.1 writes (directly, or through the
waterfall via its ``reuse_policy`` argument) is stamped ``tenant_private``, *matching* the field
declaration. ``stamp_reuse`` still fails loud if the tenant id is ever omitted.
"""

from __future__ import annotations

from clue_research.identity import DEFAULT_REUSE_POLICY, ReusePolicy

# The ``client.*`` namespace carries client-knowledge / ICP-derived claims (M5.1). They are always
# tenant-private. We extend — never replace — the M2 default prefixes so any future tightening
# of the shared default is inherited automatically.
CLIENT_FIELD_PREFIX = "client."

CLIENT_KNOWLEDGE_REUSE_POLICY = ReusePolicy(
    version=DEFAULT_REUSE_POLICY.version,
    enabled=DEFAULT_REUSE_POLICY.enabled,
    tenant_private_prefixes=(
        *DEFAULT_REUSE_POLICY.tenant_private_prefixes,
        CLIENT_FIELD_PREFIX,
    ),
    tenant_private_methods=DEFAULT_REUSE_POLICY.tenant_private_methods,
)

# The ``icp.*`` namespace carries ICP-synthesis feedback (M5.2 — the suggested-vs-confirmed confirm
# diff, persisted claim-native; see :mod:`clue_research.stage0.icp_fields`). Like ``client.*`` it is
# client-tuned and therefore always tenant-private; the field declaration is authoritative and this
# policy makes the stamping path agree with it (same rationale as above).
ICP_FIELD_PREFIX = "icp."

ICP_REUSE_POLICY = ReusePolicy(
    version=DEFAULT_REUSE_POLICY.version,
    enabled=DEFAULT_REUSE_POLICY.enabled,
    tenant_private_prefixes=(
        *DEFAULT_REUSE_POLICY.tenant_private_prefixes,
        ICP_FIELD_PREFIX,
    ),
    tenant_private_methods=DEFAULT_REUSE_POLICY.tenant_private_methods,
)

# The ``import.*`` namespace carries the import-batch grouping marker (M5.3). A client's imported
# list is tenant-private (the same reasoning as ``client.*`` / ``icp.*``): the field declaration is
# authoritative and this policy makes the stamping path agree with it. CRM-pulled tier-1 claims
# (``crm_import``) and ``account.scoring.*`` back-scores are already tenant-private via M2's default
# (extraction-method / prefix), so the import scenario writes them under :data:`IMPORT_REUSE_POLICY`
# unchanged from the default's tenant-private set.
IMPORT_FIELD_PREFIX = "import."

# The import scenario's per-row resolution provenance is a *discovery*-flavored claim
# (``discovery.provenance``, ``matched_channel='import'``) on a cross-tenant-shared account entity.
# *Which* accounts a client imported is client-tuned, competitively-sensitive signal, so this policy
# also privatizes the ``discovery.`` namespace — but only when written under the import scenario (a
# Scenario-A discovery run uses its own policy, where public-footprint provenance is correct). The
# import provenance is therefore stamped tenant-private here, while remaining shape-identical to a
# discovered account's provenance.
DISCOVERY_FIELD_PREFIX = "discovery."

IMPORT_REUSE_POLICY = ReusePolicy(
    version=DEFAULT_REUSE_POLICY.version,
    enabled=DEFAULT_REUSE_POLICY.enabled,
    tenant_private_prefixes=(
        *DEFAULT_REUSE_POLICY.tenant_private_prefixes,
        IMPORT_FIELD_PREFIX,
        DISCOVERY_FIELD_PREFIX,
    ),
    tenant_private_methods=DEFAULT_REUSE_POLICY.tenant_private_methods,
)
