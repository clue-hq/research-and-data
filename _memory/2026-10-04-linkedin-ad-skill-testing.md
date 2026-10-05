# 2026-10-04 — LinkedIn scene-ad testing (nashville lane, branch design/linkedin-ad-skill-testing)

Branch cut from origin/research-streaming at 135ca509a (PR #98 merge). Lane stack: nashville
(3060/8061/8062/8063), DB clue_nashville at 4a94970221e9, test DB clue_nashville_sdd.

## Runs observed (Conduit AI workspace, project "Conduit AI hotel operators", account Atrium Hospitality)
- Run 1 (director + author): delegated even a logo fetch to lumen-dsl-author; stopped by the user.
- Run 2 (solo, LUMEN_AGENT_SCENE_SOLO=1): ~11 min, 47 model calls (target 20), 5.58M input tokens,
  $3.55 metered, self-accepted in round 2. Skill pick consistent: scene-brief-copy + catalog ->
  account-adaptation, account-identity-composition, problem-solution. Kit tokens used throughout.
- Copy was verbose: a 30-word support line that condenses the Head of ABM brief's
  "what the ad must say" paragraph. Root: manual-tools v16 open_design_leg tells the Head of ABM
  to put "what they must say" in the brief. Verbosity work is the NEXT discussion (founder).

## Commits (local, unpushed)
- fa0ce77a6 never-signed-in visit -> plain /sign-in (not the expired card).
- 5a0a5904a LUMEN_AGENT_SCENE_SOLO=1 in both .env.example (code default still False: solo also
  needs bundle=candidate, whose code default is legacy).
- 5c728d4e0 AVIF -> PNG at CoreClient.ingest_asset (Cloudflare cdn-cgi/image/f=auto served Atrium's
  logo as AVIF; stored octet-stream; placement failed op.asset_incompatible).
- d69669eb2 image cost read from the Images API usage block (BYOK: cost=0, real charge in
  cost_details.upstream_inference_cost; generation id only in x-generation-id header); BYOK fee
  added in the shared reader; drain_safely retries and restores rows.
- 8a6e30fd6 request_clarification tool text no longer points at clarify-design-brief (absent
  from the scene view).
- 812c1e2bb Langfuse env default 'default'; prod check requires CLUE_LANGFUSE_ENVIRONMENT=production.
- 2447c3afa stopped design turns record their model-call receipts (were dropped).

## Data fixes on clue_nashville (dev data)
- Atrium's 17 research jobs + 4 runs set to completed by hand (originals in session scratchpad CSVs;
  failure codes kept in failure_message).
- Backfilled run_266a9fe3's 75 design receipts ($3.811838) onto turn 8a06bb75 via the new path.

## Open / owed
- Shared Postgres :55040 hits max_connections (~100) with nashville+trenton+addis+dubai stacks up;
  "too many clients" broke spend drains. Founder decision: fewer lane workers or raise the limit.
- Lane .env now CLUE_LANGFUSE_ENVIRONMENT=default — needs a stack restart to apply.
- Stale test: test_scene_solo_runtime::test_the_account_reads_are_registered_only_when_the_platform_injected_them
  (fefcdb6ce added web_search as a 4th read; test not updated). Pre-existing.
- agent_model_call.requested_model is 'unknown' for every design call.
- manual-tools v16 open_design_leg still says opening a leg runs no design turn (stale since
  derived first turns shipped).
- Kit gap: Conduit kit has no light (inverse) wordmark.
- 126 font faces missing from this lane's font library.
- Frontend build gate (design-system:build/lint/build) not run for fa0ce77a6 (dev server shares .next).

## 2026-10-05 — imagery investigation (no product change)
- Run 4 (`run_bfcb80e9…`) gave a good round 1 (8-word headline, 13-word support, pre-generated
  pastel ground) then failed on a hung LLM call (1,045 s despite a 60 s timeout; network flaky).
  Leg `0c45a5cd…` is open_awaiting_user. Timeout overrun not yet investigated.
- Export 401 the founder hit was a lapsed Clerk session (every BFF call 401 for one window), not a
  disabled feature; the editor does not refresh-and-retry on 401 (offered, not done).
- Findings + trial plan written: `docs/superpowers/plans/2026-10-05-brand-imagery-findings-and-trials.md`
  (library descriptions too long and unstructured; scene agent never told to search; pick-a-look
  call redundant and silently failing; style groups are single ads; pre-generation produces 12
  near-identical grounds; yellow bokeh came from the og-image reference, the hotel desk was the
  agent's own invention).
- Founder direction: no pre-generated assets by default; the agent generates at runtime with full
  context; image prompts must not add detail no reference shows. Trials T1–T6 not started; §5
  prompt wording awaits founder review before it goes into any skill.

(Ported to design/harness-alignment 2026-10-19: the branch's 'Verbosity rulings applied' section is left out here because that work — Head of ABM v71, 525bdd2ab — was not ported.)
