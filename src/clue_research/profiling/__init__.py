"""`clue_research.profiling` — Deep Profiling (modes M2/M3/M4) (M8).

Package scaffolded by M0.1 (ENG-101); scope and the modular-boundary rules live
in this package's ``README.md``. Implemented by M8.

Shipped so far:

* the **tiny seed** (M8.2 part-1 / M8.5): the ``account.resonance.*`` and ``contact.facet.*``
  field-classes as ``field_definition`` rows (:mod:`clue_research.profiling.fields`), registered via
  ``load_deep_profiling_pack``;
* **Track A — the account axis** (M8.1 + M8.2 part-2): the mode-M2 account-profiling aspect worker
  (:class:`~clue_research.profiling.aspect_worker.AspectProfilingWorker`), the
  ``account.resonance.*``
  collector (:class:`~clue_research.profiling.resonance.ResonanceAspectWorker`), the target-lock
  validator (:mod:`clue_research.profiling.target_lock`), and the account-level converge entrypoint
  :func:`~clue_research.profiling.account.profile_account`;
* **M8.3 Committee Discovery** (:mod:`clue_research.profiling.committee`):
  ``discover_committee`` / ``CommitteeAspectWorker`` + the ``contact.role_on_committee`` /
  ``contact.persona`` field pack (``load_committee_pack``);
* **M8.4 Contact Profiling** (:mod:`clue_research.profiling.contact`): ``profile_contact`` /
  ``ContactProfileAspectWorker`` filling the seeded ``contact.facet.*`` class with born-correct
  ``identity_binding`` + ``use_class`` tags.
"""

from __future__ import annotations

from clue_research.profiling.account import (
    AccountProfileResult,
    account_axis_workers,
    aspect_key_for,
    default_account_worker_builder,
    profile_account,
)
from clue_research.profiling.aspect_worker import (
    DEEP_PROFILING_PLANNER_CONFIG,
    AspectCoverage,
    AspectProfilingWorker,
    ProfilingFieldDisposition,
    SynthesisGuard,
)
from clue_research.profiling.committee import (
    COMMITTEE_FIELD_KEYS,
    COMMITTEE_PACK,
    CommitteeAspectWorker,
    CommitteeConfig,
    CommitteeResult,
    CommitteeSource,
    discover_committee,
    load_committee_pack,
)
from clue_research.profiling.contact import (
    BindingClassifier,
    ContactProfileAspectWorker,
    ContactProfileConfig,
    ContactProfileResult,
    UseClassTagger,
    compute_contact_gap_fields,
    profile_contact,
)
from clue_research.profiling.context import RunContext, params_for_run
from clue_research.profiling.fields import (
    DEEP_PROFILING_PACK,
    FACET_FIELD_KEYS,
    FACET_PACK,
    RESONANCE_FIELD_KEYS,
    RESONANCE_PACK,
    load_deep_profiling_pack,
)
from clue_research.profiling.resonance import (
    ResonanceAspectWorker,
    collect_resonance,
    resonance_firewall_ok,
)
from clue_research.profiling.target_lock import (
    binds_to_entity,
    build_target_lock,
    is_lockable,
    requires_binding_check,
)

__all__ = [
    # tiny seed (M8.2 part-1 / M8.5)
    "DEEP_PROFILING_PACK",
    "RESONANCE_PACK",
    "FACET_PACK",
    "RESONANCE_FIELD_KEYS",
    "FACET_FIELD_KEYS",
    "load_deep_profiling_pack",
    # M8.1 — account profiling
    "profile_account",
    "AccountProfileResult",
    "AspectProfilingWorker",
    "SynthesisGuard",
    "AspectCoverage",
    "ProfilingFieldDisposition",
    "aspect_key_for",
    "default_account_worker_builder",
    "account_axis_workers",
    "DEEP_PROFILING_PLANNER_CONFIG",
    # M8.1 — target-lock
    "build_target_lock",
    "is_lockable",
    "binds_to_entity",
    "requires_binding_check",
    # M8.2 — resonance collectors
    "ResonanceAspectWorker",
    "collect_resonance",
    "resonance_firewall_ok",
    # shared per-run context
    "RunContext",
    "params_for_run",
    # M8.3 committee discovery
    "discover_committee",
    "CommitteeAspectWorker",
    "CommitteeResult",
    "CommitteeConfig",
    "CommitteeSource",
    "COMMITTEE_PACK",
    "COMMITTEE_FIELD_KEYS",
    "load_committee_pack",
    # M8.4 contact profiling
    "profile_contact",
    "ContactProfileAspectWorker",
    "ContactProfileResult",
    "ContactProfileConfig",
    "compute_contact_gap_fields",
    "BindingClassifier",
    "UseClassTagger",
]
