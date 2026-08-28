# 2026-08-27 — demo-night setup (two accounts, editors, fallback deck)

Demo ~6h out. Founder ruled: no deploy, no Wave C; demo assurance only. Two impersonation
accounts, fallback deck persisted, ngrok chosen for sharing, founder drives manually in browser.

## State at close of this session's setup pass

- **Apollo account (READY):** `ws_apollo_cleanroom_20260827`, kit `brand_kit_ing_5ba6e6b32bb042b8beda253bc4f991c2` v1
  approved; lane: 4 harvested creatives, ad-DNA card v2, 8 pre-generated grounds. Verified live via
  `GET /brand-ad-assets/{kit}` (note: response nests the card as `card.card.prose`).
- **OpenAI account (HALF-READY):** `ws_openai_demo_20260827`, kit `brand_kit_ing_6872d390a5b14caeb4b1cb6d73afa8c3` v1
  approved (ingested from openai.com, ~60s clean). Ad onboarding job `ingest_1218bc1997ea4ae087b5adff8e62feea`
  **FAILED: Adyntel HTTP 402 "Insufficient tokens"** — vendor credits exhausted; founder must top up, then
  re-POST /brand-ad-assets/onboard (command in the checklist). Job/task reconciliation (R3-B fix) surfaced the
  failure loudly — worked as designed.
- **Editors (browser surface):** two instances of `subsystems/clue-design/apps/editor`:
  Apollo on :3001 (original dir), OpenAI on :3210 (untracked copy `apps/editor-openai-demo/`,
  node_modules symlinked, run `./node_modules/.bin/next dev` directly to skip `../../scripts` predev).
  Both verified in-browser: correct kit per workspace, no "Canvas editing is disabled" banner.
- **Fallback deck:** `~/Desktop/clue-demo-fallback/` — final ads (accepted Apollo fidelity-3, kit-only 97%,
  Shopify co-brand, Ramp), 4 harvested Apollo refs, 8 grounds, prose card verbatim, `DEMO-CHECKLIST.md`
  (full env-var audit of live API PID + break-glass steps).
- **ngrok:** installed via brew; NOT configured — needs founder authtoken (`ngrok config add-authtoken`).

## Traps learned (logged to gstack learnings too)

1. **Two `next dev` servers from one editor dir cross-contaminate `NEXT_PUBLIC_*`** through the shared
   `.next` cache — the "Apollo" editor showed the OpenAI kit. Fix: per-instance directory copies.
2. **Editor ports must be in `LUMEN_API_CORS_ORIGINS`** (repo `.env:152`): 3000/3001/3210/3033 only.
   3002 silently unusable.
3. **OpenRouter key over its stated limit** (usage $172.62 / limit $150) yet still answering; probed live.
   Founder warned to add credits before demo.
4. All lane/kit API routes require `X-Workspace-Id` (401 `workspace.header_required` otherwise).

## Open at handover

- Founder: Adyntel top-up → re-run OpenAI onboarding; ngrok authtoken; OpenRouter credit check.
- Dry run (founder-driven, via editors) not yet performed.
- Post-demo cleanup: delete `apps/editor-openai-demo/`, revisit shared `clue` DB foreign-stamp, Wave C decisions.

## ADDENDUM — platform-frontend pivot (same evening)

The founder's "two demo accounts" meant CLERK ACCOUNTS ON THE PLATFORM FRONTEND (apps/frontend,
port 3033), not design-editor workspaces — clarified after the editor-harness setup above was built.
The editor instances (3001/3210) are now unused for the demo; kill freely; `apps/editor-openai-demo/`
is disposable.

Stack now running (recipe in ~/Desktop/clue-demo-fallback/DEMO-CHECKLIST.md): design API 8060,
platform API 8052 (CLUE_SELF_SERVE_PROVISIONING_ENABLED=1), platform fleet worker (drives Stage-0
recon on the fleet — the [slice3×stage0] event-loop concern did not bite), frontend 3033.
`.env` additions: LUMEN_API_ORIGIN=http://127.0.0.1:8060; CLUE_SCRAPE_BACKEND=scrapling +
CLUE_STAGE0_PAGE_FETCHER=scrapling (founder standing ruling — Firecrawl rate-limited a recon lane).

Accounts (Clerk test mode, password `CluehqDemo2026!!`, OTP 424242 — sign-up needs 15+ char pw):
- apollo+clerk_test@example.com → ws_8163898e0d0e4420b578bdbc57d7f3e4, kit brand_kit_ing_10c2b0ea… v1 approved
- openai+clerk_test@example.com → ws_2cada1e4ebaf40baad43a886a10ed03e, kit brand_kit_ing_526203fe… v1 approved

Ad lanes: OpenAI honest-empty (48 considered, all not_static:video; PDL→11130470 verified).
Apollo: Adyntel returned ZERO ads on the new account (both pages; the zero-ads fallback FIRED
correctly — first live positive firing). FOUNDER-APPROVED MIGRATION executed: this morning's
clean-room harvest (4 creatives + card v1/v2 + 8 pregen + 12 design_asset rows + 12 artifact rows +
12 blobs) copied from ws_apollo_cleanroom_20260827 into the real workspace; card re-pinned to the
workspace's own kit (FK requires same-workspace kit); blobs copied to the new ws prefix and
record_json opaque_refs re-pointed. Provenance columns untouched. All 12 assets verified 200.

Known cosmetics: profile chip shows fixture name "Aakash Shrivastava"; OpenAI kit extracted teal
#0F766E as brand color (pipeline-honest, from openai.com).

## FINAL STATE — both demo flows PROVEN on the platform frontend (evening close-out)

Dry runs completed end-to-end through the real chat surface on grok-4.6 (fast loop default-on,
reviewer quarantined, verified per-run):
- **Apollo** (prj_551d8a2f76155cef806fedcf9af0e729 / thr_434f107fb8d25c6b8eb050b90a847970):
  run_e4519c16b4a64b80a0f356e4369b67b3, completed_with_warnings, fidelity 1→2, W4 auto-attach
  FIRED (asset_ad_bb118ff45670be14 + reference-brief.md), real sunburst wordmark placed. Known
  blemish: support line collides with CTA pill (fixable live in chat — a demo moment).
- **Stripe** (prj_7fc6e4cee61955ac8c7ad1b6ff7db8f2 / thr_b211adbf0dc95d9a820f7d87192d5492):
  run_2be9b88e8a1a403280c67a4a278aa4ea, **ACCEPTED**, 812s/46 calls — ribbon gradient + real
  wordmark + white pill; the fully-live account (no migration anywhere).
Both previews in ~/Desktop/clue-demo-fallback/5-platform-demo-ads/.

Demo-night code fixes (committed locally, NOT pushed): c7fbe961c (head-of-abm v40 on grok;
v39/terra retired; all four pins move together) + 42b139055 (gateway
openrouter_chat_completions_fallback — platform-scoped; design keeps Responses). Full model map:
user-memory `grok-model-config-map`. Platform processes restarted on the committed code after the
runs finished.

Söhne (Stripe): bound post-hoc at founder request (dev-ok ruling) — woff2 fetched from
b.stripecdn.com via real browser (site blocks curl), custodied as asset_ing_2228fee8f2931671
(+artifact+blob), kit v1 sohne-var faces updated in place (dev-data edit, provenance note in
record_json). TTF conversion at /tmp/SohneVar.ttf if the editor path needs it later. The accepted
Stripe ad predates the binding (painted Inter); post-binding renders/edits pick up real Söhne.

Founder instruction shifts recorded in user-memory: no-subagent-delegation (do work directly),
ask-before-interpreting-product-terms, scrapling-is-default-scraper.

Open at close: old broken Apollo test project (prj_19a43a55…, terra-era failures) — founder not
yet ruled on deletion; ngrok authtoken still founder-owned; OpenRouter credit top-up still
recommended; editor-openai-demo/ + editors 3001/3210 disposable.

### Söhne addendum: the accepted Stripe artifact now shapes with the real face
Kit face REBOUND to the TTF (asset_ing_e3ac358a2cb252f5, woff2→TTF via fontTools — the editor
canvas requires TTF/OTF; server skia reads it too). POST /documents/doc_c451f16c…/export
(format png) re-rendered and applied the recomputed text geometry (headline reflowed 2 lines→1,
proving the new metrics; doc at current_version 93). Re-render saved to the fallback deck
(stripe-chat-generated-REAL-SOHNE.png). Any open editor tab needs ⌘⇧R to pick the face up.

### Cursor ABM ad chain — asset-placement law confirmed (2026-08-29)
The account-personalized Cursor ad (thr_0f100eea…, doc_75111d69…) surfaced the W-B5 class from the
OTHER side: a design_asset row hand-inserted at the DB (with artifact+blob) is **viewable in the
library but NOT scene-placeable** — `place` returns `op.asset_missing`; the engine's placement
registry only knows assets that entered through a real ingestion/upload/generation path. The
product-correct route is `POST /assets` (multipart), which did register placement-valid
(asset_8e515b482cdd, the founder's official Cursor lockup file). Law: **every asset source needs
BOTH channels (view + place) — DB-seeded assets have neither guarantee; always enter through the
API.** Also: Cursor's own published light-lockup SVG ships a baked #F0EFEA background rect
(fetch_logo cannot strip it, by design — it never redraws logos); founder now supplies official
lockup files for co-brand work. fetch_logo tool contract now demands full lockups for
account-personalized ads (commit on this branch). Failed turns run_2a6dcf50 (plate/leading),
run_222f29d4 (op.asset_missing on the hand-seeded asset), run_617dff06 (same, cancelled-by-wait).
