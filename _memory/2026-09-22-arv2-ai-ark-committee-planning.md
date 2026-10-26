# ARV2 AI Ark committee discovery — planning session, 2026-09-22

## Scope and decisions

- Documentation/planning only. Founder approved account research, agent-reasoned buying roles,
  company-scoped SMART people search, agent selection, profile reuse and person-depth handoff.
- Follow-up answers include work emails **and phones**, and continuing discovery with a
  recorded gap after account Exa research fails its retry.
- No change to R4 company discovery, general web search, media or outreach.

## Workspace

- Started on `research-streaming` at `df5b29143`; pulled `origin/research-streaming` successfully
  to `8df27dd25` (PR #75), then created `codex/ai-ark-committee-discovery-spec`.
- Initial pull failed because shared Git metadata was outside the sandbox write root; the
  authorized escalated fast-forward pull succeeded. No merge conflict or history rewrite.
- Preserve pre-existing untracked `.context/attachments/V4drO2/`; it is not part of the docs commit.

## Findings verified against current code

- Client has name-scoped people search only; no role-search or phone operation. Person lookup
  repurchases a named search and requires a job-bound LinkedIn URL.
- Selection requires a web confirming URL; ordered candidates live in runtime memory and are
  deliberately excluded from finalization JSON to avoid ungoverned personal-data copies.
- Persona is dynamically chosen by ICP key; proposed pinning closes retry/child-context drift.
- Contact lookup can resolve another employer; proposed explicit conflict handling.
- Raw artifacts/ledger exist but internal tool success caching does not. Preserve unknown-spend
  behavior; exactly-once external billing cannot be promised.
- `core.direct_phone` exists; the inspected accounts feature has no direct-phone display slot.
- Historical canary phone input and current docs disagree; live contract proof remains owed.

## Documents

- `docs/superpowers/specs/archive/2026-09-22-arv2-ai-ark-committee-discovery-design.md`: reviewed-base
  findings, approved flow, proposed contracts, identity, provenance, pins, replay, erasure,
  failure/spend behavior, version rollout and acceptance matrix.
- `docs/superpowers/plans/2026-09-22-arv2-ai-ark-committee-discovery.md`: nine-step dependency
  sequence with file impacts, checks and separate live release gate.
- Master plan gets a planning-only pointer; historical rules are not silently marked shipped.

## Verification and follow-up

- Current official AI Ark people, company, email and phone docs read; no paid provider call.
- Engineering defaults are draft recommendations, not additional founder rulings.
- No runtime code, settings, schema or frontend implementation changed. No runtime tests claimed.
- Before implementation: review design §10.3, settle storage/erasure contracts, refresh upstream,
  then execute the plan. Live role-search quality and phone contract proof remain open.
- First combined document patch failed its README context match; no partial changes were
  applied. Reapplied with a narrow README insertion.

## Closing state

- Design has 18 offline/isolated-DB acceptance cases and separate two-account live acceptance;
  implementation plan has nine sequenced steps, file ownership and verification exits.
- Documentation validation passed: all relative links in the two new documents resolve, both
  JSON examples parse, Markdown fences balance and no trailing whitespace was found.
- `git diff --check` passed for the tracked documentation amendments. Final staged diff is
  checked before the local docs checkpoint; no push or runtime implementation.
