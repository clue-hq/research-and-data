"""The SSE **read side** — replay planning over the ``run_event`` outbox (PB-B4 slice 3; D7; D8).

This module is now a **re-export**, deliberately, and the redirection is the design: since Part II
D8 there is exactly one :func:`~clue_core.plan_replay` and one :class:`~clue_core.ReplayPlan`, in
``clue_core.run_event``. Importing them from ``clue_projections`` keeps every pre-D8 call site
resolving and keeps this package's public read surface intact, while a re-export (rather than a
second implementation) makes it impossible for the projections' replay semantics to drift from the
design leg's — the drift the D7 parity tests could only *detect*.

**Why the planner is not defined here.** It has two consumers on opposite sides of a mutual import
ban: the ``clue_api`` project-run SSE endpoint (via this package) and the design run stream (via
``clue_execution``). ``clue_projections`` may not import ``clue_execution`` (rule P1) and
``clue_execution`` may not import ``clue_projections`` (rule E1), so ``clue_core`` — which both may
import — is the only home where "one replay semantics" is structural.

**Why projections stays a pure read.** The planner takes an injected
:class:`~clue_core.RunEventReader`; the concrete, DB-backed reader
(``clue_execution.run_events.DbRunEventReader``) is built at the ``clue_api`` composition root and
passed in — exactly the dependency inversion the projections import contract prescribes. The
outbox's *emitter* is not reachable from here at all (a write in ``clue_projections`` would break
the MVCC-only read discipline), and D8 removed this package's last ``clue_research`` import on the
event path.
"""

from __future__ import annotations

from clue_core.run_event import ReplayPlan, plan_replay

__all__ = ["ReplayPlan", "plan_replay"]
