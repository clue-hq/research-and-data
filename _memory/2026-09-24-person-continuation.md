# Isolated person source continuation — 2026-09-24

- Founder authorized implementing and running the saved-response continuation. New script
  `scripts/continue_person_research.py` uses the configured person Deep Agent, current draft
  skill/charter, unchanged prior delegation/context and the latest supplied response. No PoC
  final answer or comparison notes are mounted. Production catalog selection remains unchanged.
- Operations: Exa search, contents, focused deep follow-up; shared public-media resolver and
  configured native Gemini transcription. Full provider rows (including entities/extras), raw
  responses, requests, source paths, provider ledger and model/Langfuse traces are retained.
- Complete result pages and inherited account sources share an index; original inputs are
  read-only to the agent, with scratch notes allowed. Exact repeated requests reuse receipts;
  unknown outcomes are not automatically repurchased. No application DB/fleet/claim/page writes.
- Founder asked about Exa multimedia. Official API documents extras.links/imageLinks, not a
  separate multimedia flag. Added optional extras forwarding to shared search/contents client;
  defaults unchanged. Continuation requests 10 page links and 3 image links per result. This
  exposes candidate links; native media reading remains a separate operation.
- Offline checks: 36 focused tests pass (retention, pagination, isolation, request reuse,
  uncertain outcomes, media dispatch, Exa request contracts). Ruff clean. Initial test fixture
  omitted ProviderCaller.now; corrected before live execution. No provider calls yet.
- First prepared directory predates extras; preserve as preparation-only. Latest prepared
  attempt is under `.artifacts/person-exa-comparison-20260924/`; exact trial handle and live
  outcome will be appended after dispatch. Existing trials remain immutable.

- Final prepared attempt: `nick-continuation-03` (01/02 preparation-only). Initial dispatch was
  rejected by automatic approval review before execution: exact multi-provider transmission of
  retained seller/ICP/persona/account context needed explicit approval. Asked the founder for
  that approval; no workaround, provider call or model execution occurred. Live run pending.
