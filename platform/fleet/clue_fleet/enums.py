"""Fleet-plane lifecycle enums — table-column taxonomies internal to ``clue_fleet`` (PB-B1).

Deliberately **package-local**, not in ``core.enums`` (the treaty §3.3 preference, mirroring the
``durable/enums.py`` precedent): these are internal lifecycle states of the fleet tables that no
other package references — research code never learns the queue exists (Rule F1).

Each enum is mirrored by a Postgres ``ENUM`` created in the PB-B1 migration; the parity test in
``tests/fleet/`` asserts the Python members and the DB labels stay in lock-step (the same
``StrEnum`` discipline as ``core.enums`` / ``durable/enums.py``).
"""

from __future__ import annotations

from enum import StrEnum


class FleetTaskKind(StrEnum):
    """What a ``fleet_task`` row asks a worker to do (PB-B1).

    * ``DRIVE_RUN`` — drive one project run forward until it can't advance (terminal, paused, or
      stalled). Claimed by any :class:`~clue_fleet.worker.ProjectRunWorker`; guarded by the
      per-run driver lease.
    * ``ACCOUNT_JOB`` — one per-account deep-research job inside a run's ``deep`` phase (the
      REQ-10 tier-priority queue unit). Drained only by the run's current driver (the lease keeps
      drivers exclusive), ordered by ``priority`` (tier rank) under the concurrency window.
    * ``EXECUTE_GRAPH`` — one durable recipe execution in the shared top-level leased worker.
    * ``ENTITY_RESEARCH_JOB`` — one M8D account or contact research subject. Both types use this
      same mechanical kind; exact subject authority lives in the immutable job envelope.
    * ``AGENT_TURN`` — one human-submitted platform-deepagent conversation turn (FI Lane D D2).
      ``work_id`` is the *thread*, not the turn, which is what makes the driver lease a per-thread
      single-flight fence; the turn itself is named by the payload and by the
      ``agent-turn:<turn_id>`` dedup key. The queue never carries a session token — only internal
      ids and durable turn refs (`FI-lane-B-authenticated-principal-contract.md` §7).
    * ``STAGE0_RECON`` — one detached drive of the existing two-lane onboarding recon. The web
      process only captures input and enqueues this reference-only task.
    * ``OFFICIAL_SITE_CRAWL`` — one C6 durable official-site lifecycle, keyed to a recon but using
      its own work lease so shadow acquisition may continue beside the legacy background lane.
    * ``DESIGN_JOB`` — one unit of design-subsystem work (PD Part II D5). Agent turns, web turns,
      and brand-kit ingestion all use this same mechanical kind, exactly as the two research
      subject types share ``ENTITY_RESEARCH_JOB``; which shape it is lives in the immutable
      by-value envelope the worker executes from, not in the queue taxonomy.
    * ``ONBOARDING_RUN`` — one ARV2 onboarding run (Track O, O3): the fast recon lane, the catalog
      synchronization, and the background per-product research all drive from this single job, so
      the whole run has exactly one lease and one place to resume from.
    * ``ARV2_ACCOUNT_RESEARCH`` — one ARV2 account research job (Track R, R2): the agent loop
      for a single account, so one account has exactly one lease and the rest of the run keeps
      going when that account fails.
    * ``ARV2_DISCOVERY`` — one ARV2 discovery run (Track R, R4): Websets long list, Answer
      verification, candidate accounts.
    * ``ARV2_DISPLAY_PAGE`` — one ARV2 display page (spec 2026-09-12): the account overview at
      settle, a contact page on the first open of its account, and any page a read found stale.

    New members are appended, never inserted: the DB enum is grown with ``ALTER TYPE … ADD VALUE``
    (which appends), and the parity test compares the two **in order**. Member order here mirrors
    migration application order on the merged tree (the frontend lane chain applies before the
    design Part-II chain, so ``agent_turn`` precedes ``design_job``).
    """

    DRIVE_RUN = "drive_run"
    ACCOUNT_JOB = "account_job"
    EXECUTE_GRAPH = "execute_graph"
    ENTITY_RESEARCH_JOB = "entity_research_job"
    AGENT_TURN = "agent_turn"
    STAGE0_RECON = "stage0_recon"
    OFFICIAL_SITE_CRAWL = "official_site_crawl"
    DESIGN_JOB = "design_job"
    # ARV2 onboarding (Track O, O3): one job per onboarding run — fast recon, catalog sync,
    # background per-product research. Appended, never inserted (see the class docstring).
    ONBOARDING_RUN = "onboarding_run"
    # ARV2 R2: one job per account for the account research agent. Appended, never inserted.
    ARV2_ACCOUNT_RESEARCH = "arv2_account_research"
    # ARV2 R4: one job per discovery run — the long list, the verification, the candidates.
    # Appended, never inserted.
    ARV2_DISCOVERY = "arv2_discovery"
    # ARV2 display (spec 2026-09-12): one task per (subject, page) — the fleet writes the page's
    # missing and stale sections so no HTTP request ever waits on a model. Appended, never inserted.
    ARV2_DISPLAY_PAGE = "arv2_display_page"
    # Product management (spec 2026-10-15 §6): one task per pending product page — a person's
    # add or merge in Brand context is written in the background. Appended, never inserted.
    PRODUCT_PAGE_WRITE = "product_page_write"
    # CRM integration Phase 2: one task per proposal — sends its covered writes to the CRM in order
    # and reads each one back. Appended, never inserted.
    CRM_WRITE = "crm_write"


class FleetTaskStatus(StrEnum):
    """Lifecycle of one ``fleet_task`` row (PB-B1).

    ``QUEUED`` → ``CLAIMED`` (a worker owns it; ``claimed_by``/``claimed_at`` stamped) →
    ``DONE`` | ``FAILED``. A ``CLAIMED`` row whose claim has gone stale (its holder was killed)
    is re-owned by the next claimant — the same recovery shape as the M7.4 idempotency ledger; a
    ``FAILED`` row is retried only by an explicit requeue (a fresh drive re-entering the work),
    never silently. A graceful stop hands a claimed task back to ``QUEUED``.
    """

    QUEUED = "queued"
    CLAIMED = "claimed"
    DONE = "done"
    FAILED = "failed"
