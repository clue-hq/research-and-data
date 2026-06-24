"""M12 (value narrative & handoff) api-root wiring — the home M12 fills (phase-3 pre-flight PF-7).

Own module so M10 / M11 / M12 never co-edit ``api/composition.py``. M12 fills
:func:`register_narrative_wiring`:

* register the ``account.value_narrative`` field-def — MUST declare ``reuse_scope=TENANT_PRIVATE``
  (it is ``FieldClass.ACCOUNT`` whose default is ``PUBLIC_FOOTPRINT``; a client-tuned narrative
  leaking into the cross-tenant public base is the M2×M6/M8 reuse-scope hazard) and call
  ``identity.stamp_reuse`` before insert;
* inject the ``core.retrieval.ClientKnowledgeRetriever`` (the M5↔M12 seam — a stub over
  ``read_client_kb_claims`` until the pgvector retriever lands), the faithfulness judge
  (``core.verification.FaithfulnessJudge``) and ``core.compliance.UseGate`` into the positioner;
* filter committee hooks with ``is_outreach_promotable(claim, use_decision)`` — never
  ``Claim.is_promotable`` (accuracy-only); M12 reads the post-tombstone merge (no EXPIRED case);
* wire the handoff assembler + publisher (Output 4 → ``AccountHandoff``, the PF-1 additive stamps).

Until M12 lands this is a documented no-op so the seam + ownership home exist.
"""

from __future__ import annotations


def register_narrative_wiring() -> None:
    """Register the value-narrative field + inject the retriever/judge/use-gate at the api root.

    Filled by M12 (M12.1–M12.3). Placeholder until then.
    """
