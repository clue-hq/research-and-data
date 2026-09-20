"""``clue_memory`` — the scoped-memory substrate (Doc M; subsystem two), behind its two seams.

NOTHING outside this package may import it (Rule S1 + the agents contract — machine-enforced):
writers/readers bind to the ``clue_core.memory`` seam contracts and are handed the
implementations at the composition root. In-package, ``_store`` is the private storage layer;
the modules here are the enforcement:

- ``write``    — the write seam (kill-switch, subject binding, species/body rules, born trust,
                 reconciliation, caps).
- ``assembly`` — the read seam (deterministic gate → rank → assemble → label → journal).
- ``reconcile``— pre-checks + the pure decision core + the LLM judge (the one model call site).
- ``lifecycle``— the one ranking, eviction/backfill, cycle-relative freshness.
- ``switch``   — the workspace kill-switch (+ audit).
- ``compliance``— DSAR verbs (erase, objection lock).
- ``evals``    — the reconciliation golden set (fixtures + runner, offline).
"""

from clue_memory.assembly import Assembly, get_memory, list_project_memories
from clue_memory.compliance import erase_subject, lock_memory
from clue_memory.lifecycle import (
    ENGINE_ACTOR,
    backfill_slot,
    enforce_store_cap,
    losing_comparison,
    rank_key,
    record_kickoff,
    retire,
)
from clue_memory.model import ERASED, Memory, new_memory_id
from clue_memory.reconcile import (
    Disposition,
    LLMReconcileJudge,
    ReconcileJudgeError,
    decide,
    has_deterministic_match,
    normalize_body,
)
from clue_memory.switch import is_memory_enabled, set_memory_enabled, switch_audit
from clue_memory.write import WriteSeam

__all__ = [
    "Assembly",
    "WriteSeam",
    "get_memory",
    "list_project_memories",
    "Memory",
    "new_memory_id",
    "ERASED",
    "ENGINE_ACTOR",
    "Disposition",
    "decide",
    "has_deterministic_match",
    "normalize_body",
    "LLMReconcileJudge",
    "ReconcileJudgeError",
    "rank_key",
    "losing_comparison",
    "enforce_store_cap",
    "backfill_slot",
    "record_kickoff",
    "retire",
    "is_memory_enabled",
    "set_memory_enabled",
    "switch_audit",
    "erase_subject",
    "lock_memory",
]
