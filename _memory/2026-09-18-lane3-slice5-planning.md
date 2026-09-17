# 2026-09-18 — Lane 3 slice 5 (design subsystem cost/tracing/telemetry): design + plan written

Planning only; no code. R12 hold lifted by PR #62 (design-agent-v1 merged 2026-09-17).
- Design: `docs/superpowers/specs/2026-09-18-lane3-slice5-design-subsystem-design.md` (six rulings
  requested in §6, plan follows the recommendations).
- Plan: `docs/superpowers/plans/2026-09-18-lane3-slice5-design-subsystem.md` — six tasks: (1)
  `libs/clue-spend` seam move with incident hook + optional artifacts; (2) `clue_obs.production` +
  design API root instrumentation + lumen dependency declarations; (3) `lumen_api/spend.py` scope
  and the ten operations (image, four ingestion models, ad-DNA, style-group, Brandfetch, Adyntel);
  (4) `ModelCallCollector` + injected `TurnCallbacks` at the invoke config + brief agent to ledger
  + `usage_capture.py` deleted; (5) `design-leg.turn` trace, receipts on the design turn, judge
  role, `NOT_COVERED`; (6) memory + owed live proofs.
- Verified facts driving the shape (three scouts, 2026-09-17/18): the design trio already runs on
  the governed gateway inside the fleet worker (`lumen_agent/llm.py`), so cost + role exist per
  call but no `agent_model_call` row and no Langfuse handler; `create_deep_agent` takes no
  callbacks — only the invoke config does; the design run's response is the terminal run row's
  `result_json`; the design API root has no OTel/Sentry/Langfuse; five raw httpx OpenRouter clients
  + image provider discard `usage`; lumen pyprojects declare no clue-obs/clue-gateway dependency.
- Next: founder rulings on §6, then SDD (Opus implementers, Fable reviews) — not started.
