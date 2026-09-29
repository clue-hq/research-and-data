# 2026-09-29 — Contacts "Look up" email → AI Ark, on by default

Founder rulings: enable the lookup by default; connect it to the AI Ark path research uses.
- Before: `CLUE_FRONTEND_CONTACT_EMAIL_LOOKUP_ENABLED=false` → every click 503 "email enrichment
  is not configured"; even enabled it ran the old Exa Websets + Sumble providers.
- Now: default `true` (settings, `.env.example`, dubai `.env`); the service composes one
  `AiArkEmailProvider` (`frontend_read/contact_email_lookup.py`): AI Ark
  `/v1/people/export/single` by the contact's LinkedIn URL (same call as research), raw body +
  money rows drained to `provider_call_ledger` stamped to the workspace; synchronous → terminal
  state at start (never polled). Usable verdicts (`verified_smtp`, `catch_all_valid`) write a
  `core.work_email` claim `{address, status, checked_at}` under the new source manifest
  `ai_ark_people` (tier 1, strong binding, contact scope); other verdicts → NOT_FOUND;
  ProviderHalted → UNAVAILABLE; AiArkResponseError → FAILED. Exa/Sumble provider classes stay
  (uncomposed). The service accepts any non-empty provider set.
- Pre-existing test-env gap fixed: the lookup DB tests never loaded the Client-KB pack, so
  `seed_source_manifests` refused `client.competitor`/`client.buyer_profile` (live DBs have it).
- Known: AI Ark pricing is not configured (ledger cost $0) — the fix-list item still stands.
  AI Ark pacing inside the API process is the client's in-process lock (research workers use a
  DB advisory lock); a 429 is retried by the caller's backoff.
Owed: one live click on a contact (spends 1 AI Ark credit) — founder's.
