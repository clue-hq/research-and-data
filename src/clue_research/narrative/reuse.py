"""The narrative reuse policy — stamp ``account.value_narrative`` TENANT_PRIVATE (M12.1).

``stamp_reuse`` classifies a claim's reuse scope from a versioned :class:`ReusePolicy` using a
namespace-prefix heuristic (it does **not** consult ``FieldDef.reuse_scope`` — that thread-through
is the ENG-165 follow-up). The default policy's private prefixes are ``contact.`` /
``account.resonance.`` / ``account.scoring.`` — none of which match ``account.value_narrative``
(it is plain ``account.*``, public by the heuristic). So, exactly as ``stage0`` does for
``client.*`` claims (:data:`clue_research.stage0.reuse.CLIENT_KNOWLEDGE_REUSE_POLICY`), we
*extend* the shared default with the value-narrative prefix rather than replacing it — so any
future tightening of the shared default auto-inherits, and the value narrative still classifies
private.

This keeps the one stamping seam (``identity.stamp_reuse``) authoritative — the positioner never
sets ``reuse_scope`` / ``tenant_id`` by hand — and makes "a client-tuned narrative is never
written public" a property of the data model, not the positioner's discipline (substrate §2; the
``FieldDef`` declaration + ``check_claim_writable`` are the backstop).
"""

from __future__ import annotations

from clue_research.identity import DEFAULT_REUSE_POLICY, ReusePolicy
from clue_research.narrative.fields import VALUE_NARRATIVE

# Extend (never replace) the shared M2 default with the value-narrative prefix, mirroring stage0.
NARRATIVE_REUSE_POLICY: ReusePolicy = DEFAULT_REUSE_POLICY.model_copy(
    update={
        "tenant_private_prefixes": (
            *DEFAULT_REUSE_POLICY.tenant_private_prefixes,
            VALUE_NARRATIVE,
        )
    }
)
