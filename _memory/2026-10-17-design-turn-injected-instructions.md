# 2026-10-17 — what the scene agent receives on a follow-up turn (investigation, no code changed)

Branch `feat/scene-delete-key`. Triggered by the Conduit revamp run `run_a250cece3ac756958db08e81899af7b1`
("Make the whole ad feel more premium") keeping the layout and producing an off-brand image.

## Inventory (solo path)
- System prompt, rebuilt every turn: `build_scene_solo_prompt` (~12k chars) + frame payload
  (`lumen_agent/frame.py`: brand card, published-ad styles "advisory", backgrounds "advisory",
  type ramp, LIVE scene digest, asset index, 4 pinned knowledge files ≤24k chars each) +
  deepagents `BASE_AGENT_PROMPT` + middleware (skills list, filesystem docs, todo, `/.deepagent/AGENTS.md`,
  scoped preferences when present).
- User message (`main.py` `_execute_agent_turn_job` → `render_leg_turn_prompt` → `editor_agent_prompt`):
  [empty-page steering note] [DELEGATION BRIEF, first turn of a leg] [SESSION SO FAR, fresh thread]
  [DOCUMENT CHANGED drift note] + the user's text + "Editor context JSON" (ids, targets,
  `scene_summary` with no text/geometry, diagnostics, `editor_instruction`, standing instructions).
- Workspace files rewritten each turn (`workspace.py::scaffold_workspace`): brief.md (message +
  editor context again + "Caller-selected native-copy review" legibility block), state.json
  (`turn_request` = message again), brand_card.json, brand_colors.json, source_assets.json,
  ad-assets.md, references.md.

## Findings
- Four stacked "keep it" rules: `editor_instruction` (main.py:12547, commit 831a8bbb9 2026-07-04,
  written for chipped editor edits), solo prompt step 1 "For a seeded edit … preserve successful
  unrelated content", shared-surface contract #4 "smallest coherent change … unforgivable failure,
  worse than making no change at all" (prompts.py:56-62), and the follow-up routine sending a revamp
  back to the full routine, which still contains the seeded-edit preserve line.
- Contradiction: `editor_instruction` with targets says "do not touch any other node —
  byte-identical"; the shared-surface contract #1 says selected nodes are "the SUBJECT, never a fence".
- Brand: Conduit's brand_card has `imagery_rules: []`, tone clear/professional. The pastel-bokeh look
  is stated ONLY in ad-assets / frame section, labelled "context, not a rule … nothing here overrides
  … what the person actually asked for" → "premium" overrode it.
- Third follow-up had `target_node_ids=["atmosphere"]` (image selected) → strict fence; fine there.

Open: founder to choose fixes; nothing edited.

## Step 1 of the harness alignment — rule ledger (2026-10-17, DONE)
- Working dir `docs/design-harness-alignment/` (untracked; to be committed on the alignment branch): PROGRESS.md
  checklist (57 sources, all ticked), `ledger/*.jsonl` (636 rows), `issues.py` → `issues.json` (11 conflict groups),
  `render_ledger.py` → `rule-ledger.html` (artifact https://claude.ai/artifact/2EagVdjnAmnGkGgzNhU5Ce), `sources/`
  (captured first-call system prompt 68,335 chars + 21 tool schemas). Document tree page:
  https://claude.ai/artifact/Q8KsrqMZfAQT8EYJUDRGhm.
- Headline conflicts: I1 nine keep-it-small rules, no revamp permission/intent; I2 selection fence vs subject;
  I3 brand look advisory + below the request (binding only in account skills); I4 circular self-review;
  I5 follow-up routine vs repair-design/review.md/components (apply_structured_edit missing); I6 five ask policies;
  I7 six reading policies; I8 broken refs (clarify-design-brief, memory edit_file denied, search_assets→use_brand_asset
  refused, print-bleed-marks, foundations/typography-and-composition/images/placement, logo-and-assets, generate_brand_kit);
  I9 trio/test-probe/eval leftovers; I10 specific contradictions (scrim, type ratios, root structure, font floor,
  "Book a Demo", Inter, identity, ending); I11 duplicates (direction ×5, logo prep ×5, new imagery ×6, CTA ×5+,
  message ×3).
- Next: Step 2 founder rulings topic by topic (I1/I3/I4 first). Branch for edits not yet created (proposed
  `design/harness-alignment` off research-streaming).

## Step 4 progress (branch `design/harness-alignment`, local only, not pushed)
- Steps 2–3 complete; all rulings in `docs/design-harness-alignment/RULINGS.md` (standing rules: playbooks
  frozen; shared files changed only via `views/scene/` overlays; text sizes are a protected outcome).
- Done and tagged: T1 `harness-alignment-I1` (b5f0ca3c1, kinds of request, editor_instruction removed),
  T2 `harness-alignment-I5` (6123e35df, targeted-edit path, one edit-tool rule), T3 `harness-alignment-I4`
  (b7672d119, review order: request first, plan last), T4 `harness-alignment-I6` (0d1b9a5a4,
  clarify-design-brief scene copy, cap 6, typed clarification schema, brand-kit scene copies).
- Verification per topic: named test files + re-capture of the first-call system prompt
  (`docs/design-harness-alignment/capture.py`) diffed against the previous topic.
- Known pre-existing failures (also fail at `harness-alignment-baseline`): test_scene_solo_runtime
  `test_the_account_reads_are_registered_only_when_the_platform_injected_them[True]` (web_search),
  test_deepagent_harness `test_tool_surfaces_are_exactly_the_ledger` and test_fast_loop
  `test_flag_on_author_toolset_includes_render` (search_assets).
- Also done and tagged (2026-10-17/18): T5 `harness-alignment-I7` (45ae0f8d9, one reading rule, ls/read_file
  and skills-section text via harness options), T6 `harness-alignment-I9` (bdcc8e668, leftovers out, minimum text
  size generated from the active review profile, TodoListMiddleware removed), T7 `harness-alignment-I8`
  (bc2fe5286, every reference leads somewhere; print-bleed-marks delivered), T8 `harness-alignment-I10`
  (74c2fb089, guides agree with scene rules; brief label "YOUR ASSIGNMENT FROM THE HEAD OF ABM" for ad legs),
  T9 `harness-alignment-I11` (c7f73a855, one home per repeated rule; no brief.md / scene_summary for solo),
  T10 `harness-alignment-S1-S2-S4` (52418eb67, operating note folded into the prompt with where-to-get-
  evidence lines, MemoryMiddleware + scene AGENTS.md gone, six pointer skills out of the manifest; first
  system prompt 63.4k -> 56.8k chars).
- T11 tool parameter schemas done 2026-10-18 (tag `harness-alignment-T11`): typed input schemas in
  `lumen_agent/models/scene_tool_inputs.py`, apply_structured_edit takes an object (9 kinds), finalize_run
  = status/stop_reason/summary, validate_binding_set not offered; all rulings in RULINGS.md. Also fixed a
  T9 test regression in test_scene_logo_guidance.py. Evidence counts recounted by unique run id (28 turns).
- Remaining: owed DB-backed tests on a throwaway migrated DB (listed in RULINGS.md); optional offline
  probe of the new edit schema (~12 edit requests, model writes calls, engine validates; <$1); then Step 5
  live runs (Conduit/garnerhealth/Clue). Deferred: port format-skill facts into placement.md.

## Step 5, first live runs (2026-10-18, after T11; model gpt-6.1-sol)
- Lane switched to Sol: cherry-picked trenton's 5461c1fd6 (cd6da0562, examples only) + `.env` LUMEN_AGENT_MODEL /
  _REVIEWER = openai:openai/gpt-6.1-sol (backup `.env.bak-2026-10-18-before-sol`); stack down/up so every process runs
  T1–T11 (the old stack predated T1). No Clue workspace in this DB (needs onboarding + extraction) → Stripe used.
- Same request in each project chat: "Create a LinkedIn square ad (1080×1080) for this campaign."
  Conduit run_4856de3d… 202 s / 21 calls / $0.45 / accepted round 2; Garner run_ab6d68a6… 332 s / 31 / $0.59 / round 2;
  Stripe run_8f932b33… 217 s / 12 / $0.32 / round 1. Head of ABM ~2 min each before the leg.
- Worked: 2 batched read steps; self-check judged the request and caught real defects (Conduit image fit, Garner logo);
  small targeted repairs; all text passes legible-feed-v1; on-brand; T11 structured edits succeeded first try (2/2);
  stop_reason short ("request met") 3/3; record_gap used for real product gaps.
- Problems: all three CTAs start "Explore …"; Conduit body is 4 lines of client boilerplate because the Head of ABM brief
  said "Client phrasing to use as the offer"; Stripe CTA arrow far from its text (review missed it); Sol sends all 28
  asset params; Garner spent 6 steps revising creative-direction.json; Garner over the 240 s / 20-call target.
- Engine/data findings: LUMB0805 typography-role warnings appear after any post-compile edit (Conduit, Garner);
  Garner kit SVG wordmark renders ~64×20 ink in a 222×64 frame and its reversed logo has no preview;
  direction-contract.md still writes `validate_creative_direction()` with brackets.
- Tracer: scratchpad `trace_design_run.py <run_id>` reads messages from checkpoint_writes (channel 'messages'),
  not checkpoint snapshots; Sol returns no reasoning text.

## Copy work (2026-10-18, UNCOMMITTED until trials — founder rule)
- Founder rulings: one-to-one → design agent owns the angle; campaign → Head of ABM gives intent
  (segment/persona, stage, offer + CTA destination, agreed key message), design agent picks the angle unless
  chosen; Head of ABM gets a short angle menu; playbooks unchanged; word budgets per format; text sizes protected.
- Written (working tree only): placement.md "How much copy each placement carries" table (feed 1080² ≤8/≤15/≤25…);
  scene-brief-copy: read the format budget, "Choose the angle before the playbook" (persona, proof, purpose),
  line rules (examples only on concrete/proof, founder-trimmed), CTA positive pattern (stock-phrase examples dropped);
  review.md word-count check; solo prompt step 1 "the playbook for the angle you choose".
- Head of ABM: prompt v19 (brief carries no copy, angle menu for variants), manual v18 (re-minted; tools chapter
  carries the new open_design_leg text), profile v72 (= v71 grants), registry/composer/manual-build pins → v72,
  open_design_leg description ("what they must say" removed; stale "NEXT message starts generation" fixed).
  Tests updated: test_catalog, test_agent_registry_wiring (manifest hash b42451e1…), s4e, comprehensive contract.
- Research note: docs/design-harness-alignment/research/2026-10-18-b2b-ad-copy.md (uncommitted).
- Next: restart stack (prompts.py + platform code), trials: same 3 campaign ads + 1–2 one-to-one (Conduit/Atrium).

### Copy trials (2026-10-18, gpt-6.1-sol, dushanbe stack)
- Round 1 (3 campaign + 3 one-to-one, $3.51): briefs no longer dictate copy; all ads within budget (16–23 words vs
  21–48 before); 4 different playbooks (was always problem-solution). Open: "Explore…" CTAs on campaign ads, logo
  pairs mismatched (Stripe×Tencent, Conduit×Atrium), playbook read in the same batch as the persona, one unclear headline.
- Then written (still uncommitted, founder-approved wording): account-identity-composition logo-pair order
  (horizontal → stacked → symbols, else closest pair at equal size; fabricated symbol+typed-name lockup forbidden by
  ruling); scene-brief-copy "read persona and proof in one batch, wait, then the playbook next step"; "headline must
  make sense on its own; wit welcome when still easy to get".
- Round 2 one-to-one ($2.09; Tencent run_7513802f… 213 s $0.49, Carmel run_f9c3252d… 265 s $0.69, Atrium
  run_65dfeab9… 328 s $0.91): words 20/24/22 (all ≤25); batching kept 2/3 (Tencent read persona+playbook together,
  no proof); CTAs verb+object, no "Explore" CTA. Logos: Atrium balanced (both wordmarks) but a crop with stray blue
  corner pixels was accepted; Tencent horizontal Stripe wordmark × stacked Tencent lockup ~2× bigger although both
  brands have symbols (Stripe kit logo.mark, Tencent light_mark); Carmel = Garner wordmark × CCS symbol + the name
  TYPED beside it (the forbidden fabricated lockup) although Garner's kit has a mark. Headline clear on its own 1/3.
- Causes found: section 1 still says "Prefer complete wordmarks" (competes with the order); "same visual area and
  height" is not actionable; the skill never names the typed-name lockup as forbidden; review has no headline-alone
  check. Tool findings: fetch_logo reported Tencent `lockup_completeness: symbol_only` although its brandfetch
  light_lockup carries the name; `view` has no preview for some kit/fetched logos (Atrium asset_ing_97422853…, Garner
  reversed) → the agent crops logos out of other images (slow, artifacts).
- Comparison sheet: docs/design-harness-alignment/trials/2026-10-18-one-to-one-round-2.png. Refinement wording
  proposed to the founder; nothing written yet.

### Founder decisions after round 2 (2026-10-18)
- Logo-pair wording with "visual balance" (size by visible ink, weight, alignment; pair order horizontal →
  stacked → symbols; never type a name beside a symbol) APPROVED and written to
  views/scene/skills/account-identity-composition/SKILL.md (uncommitted, skill rule). The crop-removal sentence,
  "Prefer complete wordmarks" swap, headline-alone review check and logo-flaw review check: proposed, NOT yet
  confirmed — ask. Components-guide line-break sentence: REJECTED ("leave it").
- AVIF/ICO → PNG at `CoreClient.ingest_asset` (new `lumen_api/image_containers.py`, mirrors font option A) +
  backfill `subsystems/clue-design/scripts/convert_stored_web_images.py` (dry-run default; re-ingests through the
  chokepoint, register_engine_write custody, keeps id/label/tags/source, note "backfill previous digest").
  APPLIED on clue_nashville_pm_clone + shared R2: 30 rows → image/png raster_image with thumbnails, 0 failed.
  Owner action per other environment: run the backfill (dry run, then --apply). Pillow floor → 11.3 (AVIF).
  Tests: test_image_containers, test_core_ingest_image_normalization (real release helper), 
  test_convert_stored_web_images (throwaway DB clue_dushanbe_imgtest @55040).
  Data slips seen once viewable: Garner kit "reversed" logo is dark green ink; Atrium "light_lockup" is WHITE ink
  and is the full stacked lockup with the triangle symbol (ladder theme classification wrong).
  Running design API / workers still hold the old ingest code until a stack restart.
- Editor: founder declined one-box/(b); ruling: the letters' outline shows on HOVER only; a selected text with a
  dashed frame shows only the frame + handles. `selectionStrokesPaintedOutline` in adapter/scene-canvas-view.ts,
  used by SelectionChrome; verified live on the Carmel ad (selected headline: dashed frame + 4 handles only; hover
  on support: solid outline). Platform frontend only; subsystems/clue-design/apps/editor untouched.
- AVIF/ICO work COMMITTED 9bda4d25e (2026-10-19). Test notes: run design API suites with
  LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0 and without a second `-q` (root addopts already has -q;
  -qq hides the summary). test_asset_custody hangs at app shutdown in BOTH modes (conversion on and off):
  the embedded fleet worker claims an asset_enrichment job and waits for an image pool — pre-existing,
  unowned. 4 fetch_logo vendor tests fail with the conversion off too (vendor lookup bypasses MockTransport).
  Throwaway DBs: clue_dushanbe_imgtest, clue_dushanbe_imgtest2 (@55040; drop when done).
- Editor (uncommitted, awaiting the next inspector change): outline-on-hover + edit box grows to its text.
  Founder 2026-10-19: rich-text edit stays as is (no canvas-drawn draft). Text wrap is OFF by default
  (TextNode::default + DSL); founder chose: add a text Wrap row in the ad inspector (Typography, under
  Alignment, "No wrap"/"Wrap" select like auto-layout's) — mockup shown, hint-line choice pending; and
  remove the Typography "Text" field (canvas editing replaces it). "Fit to text" = height→hug (Plan 4 F).
- 2026-10-19 COMMITTED: 623a04f89 (letters' outline hover-only; text edit box covers every painted line and
  grows while typing) and 614cd0b18 (ad text inspector: Text field removed; content hydrate/write kept for
  canvas editing). Lesson: never assert.equal a jsdom element — a failing assert inspects the whole window,
  the tsx test went OOM (exit 137) and took the Claude app down twice; compare a boolean, run jsdom tests with
  NODE_OPTIONS=--max-old-space-size capped. Still pending: text Wrap row (hint line yes/no), skill wording
  confirmations (crop sentence, "Prefer complete wordmarks" swap, review checks), stack restart so running
  services pick up the AVIF/ICO ingest code.
- 2026-10-19: founder approved and I WROTE (uncommitted, skill rule): account-identity-composition — no logo crops
  (only original logo files) and "Prefer complete wordmarks" → single logo prefers its lockup, a pair follows the
  pairing order; review.md — headline-alone check after the word-count check, and logo-flaw defect check after the
  paired-logo check. Scene prompt/logo tests 30 passed. Stack restarted (dev_stack.sh down/up) so the AVIF/ICO
  ingest code is live. Next: a trial round with these edits, then decide commit with the founder.
- Round 3 one-to-one (2026-10-19 UTC 20:16, all new wording live): Tencent run_dee9a530 194s $0.61 — Stripe
  wordmark × Tencent stacked lockup, chose names over "ambiguous symbols" (rule's exception; never viewed Stripe's
  kit mark), Tencent still taller AND wider; headline "AI usage goes global. Payments and tax, too." CTA "Talk to
  Stripe". Carmel run_c7d32086 179s $0.56 — real Garner wordmark (the converted AVIF) × CCS symbol, school name as
  a kicker line (not beside the symbol), balanced; "Keep your plan. Explore savings." Atrium run_9f1e171d 338s
  $1.59 — converted logos UNVIEWABLE again → fell back to Atrium's square social tile (unbalanced), CTA "Explore
  Conduit agents". 0 crops in all three; words 21/24/23; batching 3/3.
- ROOT CAUSE of Atrium: clue_design.assets.register_scene_assets (every document save) copies an embedded scene
  record's media over the library row when digests differ. 7 documents still embed the pre-conversion AVIF/ICO
  records; a save at 18:47:40 UTC reverted the Atrium row's media (hybrid: new kind/provenance, old media, no
  thumbnail); the run pinned that snapshot at 20:19. fetch_logo's re-ingest at 20:22 rewrote it correctly; all 30
  rows are PNG now but any save of those 7 docs reverts again. Fix options proposed to founder (A: backfill also
  rewrites the 7 documents' embedded records; B: register_scene_assets must not overwrite a converted row with its
  own pre-conversion digest). Backfill ran ~18:25 UTC (not 18:47; IST/UTC mix-up).

### Imagery port from design/linkedin-ad-skill-testing (2026-10-19, founder-directed)
- Cherry-picked (fast-forwarded into design/harness-alignment, local only): a4eac8471 session record,
  e0f406ced logo ladder AVIF/ICO + real-ink light/dark + every site logo (adapted to OUR image_containers
  convert_to_png; the branch's duplicate 5c728d4e0 NOT ported), 54aca23dc findings/trials doc, 8e3438fe0 ad-style
  describer on DeepSeek (look picker reasoning off), 7a4891bfc generative-imagery guide (+12 playbook pointers;
  brand-imagery = branch opening rule + Generated imagery para + our 'components.md already in your prompt';
  account-identity-composition = branch edge pointer + our 'Meet the minimum text size'; asset tool's original
  long action-by-action description RESTORED in place of T11's short one, founder ruling), 8e689197d / 56c4b29c8
  trial docs, 87e3d268b text-free references, 866983827 hybrid CLIP search (search_assets description = union:
  brand kit+library placed by origin + query guidance; pillow>=11.3 kept + onnxruntime/tokenizers; alembic merge
  546277c8bd9d joins 1ecc7437e5bc+9429b503cc9d), dfc8058de test fix.
- EXCLUDED by founder: compaction (a49384421, bfa6ade2a), Head of ABM v71 (0c7afbc66), 'writes every word'
  (525bdd2ab), image-gen cost recording (d69669eb2, 2447c3afa); also skipped: auth redirect, langfuse default,
  solo env (already on), 8a6e30fd6 (clarify skill IS in our scene view).
- UNCOMMITTED (founder rule, trials first): imagery skills back on the scene manifest (generative-imagery,
  reference-image-direction, reference-conditioned-ads) + test; image-grammar.md order "library/generated image
  first, library icon second, vector path only for plain geometry"; plus the earlier logo/copy/review wording.
- Lane: .env gained LUMEN_ASSET_EMBEDDINGS=1 + LUMEN_ASSET_EMBEDDING_MODEL_DIR (VM path; no local model →
  visual search reports 'off'); lane DB migrated to 546277c8bd9d; stack restarted. OPEN: onnxruntime/tokenizers
  not installed in .venv and no local CLIP model (export needs torch+transformers, ~2 GB download) — asked
  founder; LUMEN_AD_DNA_MODEL: examples now deepseek-v4.1-flash, lane .env grok-4.5 — asked founder.
- 2026-10-19 follow-up: CLIP model already on disk at ~/.cache/clue/models/clip-vit-base-patch32-onnx (built
  2026-10-05 for nashville); lane .env LUMEN_ASSET_EMBEDDING_MODEL_DIR points there (examples keep the VM path).
  onnxruntime 1.30.0 + tokenizers 0.23.2 installed into the dushanbe .venv OFFLINE from the uv cache (lock pins
  match). Real-model tests: 54 passed. LUMEN_AD_DNA_MODEL=deepseek/deepseek-v4.1-flash-1017 (founder) committed
  34741e1cf (both examples + py_lumen_config default; lane .env too). Embedding backfill
  (scripts/embed_asset_library.py --apply) run for Conduit (538), Stripe, Garner (130) workspaces; restart owed.
- CTA button test (2026-10-19, offline, real sohne-var font; scratchpad cta_test.py; sheet
  docs/design-harness-alignment/trials/2026-10-19-cta-button-variants.png): hand-placed = label ink 4 px high, gap
  59 px; A row hugging content `al(h,x(c),y(c),g(12),pad(28,40)) s(hug,hug)` + label s(hug,hug) = 1 px, gap 14 px,
  no warnings (WINNER); B fixed button + fill label = 1 px, gap 45 px; C fixed button + hug label = 1 px, gap 13 px
  but LUMV0902 "overflows horizontally" false positive (the old blocks library's warning). Test gotchas: recompiling
  a page onto existing node ids keeps the old nodes; `#page:` needs the agent's DSL session (use `page id size()`
  on an empty scene); pass ABSOLUTE store_root/asset_store_root or brand fonts fall back to Inter.
  Wording for components.md CTA step + review check proposed; awaiting founder.

## 2026-10-19 — Tencent Cloud logo: preload hints (commit 5e2045533)

- Symptom: fetch_logo returned only Brandfetch's stacked lockup / a square share image for tencentcloud.com; the header's horizontal logo was missed.
- Real cause (an earlier "EdgeOne bot wall" diagnosis was WRONG — that came from a plain non-Chrome fetch; the ladder's Chrome-impersonating client gets the full page): the header logo is a CSS background on an empty `<i class="qc-topnav__logo-text">` (inline `<style>` rule). The ladder harvested it (CSS_BG) but ranked it below `/brand`'s `twitter:image` `wwCe116_cloud.png`, which is "brand-evidenced" because its name contains "cloud".
- Fix: harvest `<link rel=preload as=image>` files named logo (PAGE_LOGO_NAMED); a header/nav word in the name sets `preloaded_header_logo`, which counts as brand evidence in `pick_primary`. Tests in test_logo_ladder.py (4 new; the evidence test fails with the rule disabled). Logo + capture suites green (128 + 55).
- Live: light slot = `VYt5270_qc-topnav-logo.svg` (130x22), confidence 0.95; mark slot = the cloud symbol.
- Open: the lockup classifier labels that logo `wordmark` (lockup_completeness `wordmark_only`) though it is cloud + name — symbol-to-text gap too small for the gap rule. Not fixed.
- Open (founder call): count a CSS rule whose selector names header/nav + logo as the same evidence (covers sites that paint the header logo by CSS without preloading it).
- Scrapling facts confirmed: ladder = scrapling's curl_cffi Chrome impersonation (LUMEN_LADDER_IMPERSONATE_CHROME=1); brand-kit capture = StealthyFetcher browser (patchright, same Chromium 1228 as Playwright; prod image + fleet workers carry it); the 2026-09-02 decision kept the browser out of the ladder (14–23 s/page).
- 2026-10-19 18:53 lane stack restarted (down/up via dev_stack.sh) so every process runs the new ladder. The editor search still showed 2 logos: `design_logo_family` has NO TTL and held a pre-fix Tencent row (ws_ecf8…, saved 2026-10-18). Deleted that one row (founder OK); founder confirmed the search now shows the header logo. Lesson: after a ladder change, stale cached families persist per workspace — clear the row, or bump `identity_policy_version` (agent_logo_family_cache.py) to invalidate all.
- Open: the extras (`alternatives`) skip the ladder's identity/junk checks (Tencent's mobile-nav search-icon sprite shows as a "wordmark" extra); the cloud symbol lost the light_mark cell (variant unknown → "unclassified" extra). Both offered, not started.

## 2026-10-19 — Export no longer blocked by text overflow (commit 45626cc7a)

- Symptom: PNG export of the Tencent ad (doc_d5963bcb…) refused; the menu showed "font asset brand is not marked subsettable for PDF export" (LUMB0614, a warning that never blocks).
- Cause: an editor resize (op 47, 2026-10-19 18:29 IST) fixed the "x" separator at 26×58 (agent had made it hug-height); its 4xl text overflowed → LUMV0903 (error) → export_policy fail-closed blocked. The engine's own export returned ok with correct bytes (gate bypassed, PNG matched the canvas).
- Founder ruling (option A): text-fit codes LUMV0902/0903/0904 = `EDITOR_EXPORT_ADVISORY_CODES`, advisory only when `editor_export=True` (the two editor routes /export-preview and /documents/{id}/export). The design agent's acceptance keeps the strict rule.
- Frontend: `sceneExportResultMessage` names the first error not in the response's `warnings` (new `advisoryCodes` on EditorExportResult), never a warning. The export menu has NO designed slot for advisory warnings; none invented (overflow still shows in the canvas diagnostics panel).
- Verified: policy tests 11, test_api -k export 30 (on throwaway clue_dushanbe_imgtest2, upgraded to 546277c8bd9d), route test fails with the change reverted; frontend 62 tests; tsc errors only in unrelated test files (58, none in changed files). Stack restarted 20:12 IST.

## 2026-10-20 — main merged into design/harness-alignment; PR #130 opened

- Merge commit 946615e8f (normal merge, 879 commits from main; pushed; PR https://github.com/clue-hq/research-and-data/pull/130).
- Founder rules for the 17 conflicts: mirror the design/linkedin-ad-skill-testing port decisions (kept out: "writes every word" 525bdd2ab incl. the account-adaptation "public statement" rule; main's duplicate AVIF converter 5c728d4e0 — ours stays, duplicate core.py call removed). Scene skills/prompts/tool text identical to the branch. Compaction: OFF for the scene-ad agent only (scene solo keeps deepagents' summariser; harness.py builds compaction only `if not scene_solo`). Cost recording kept. Main's other work kept (asset_catalog hybrid_search for the site agent, research paging line, leg artifact + provenance caution on the default brief header; ad legs keep SCENE_ASSIGNMENT_LABEL). Alembic merge revision cba395a41e66 (00d525936b30 + 546277c8bd9d). uv.lock refreshed (pillow >=11.3).
- Pre-existing failures on main (verified on main's own code): test_tool_surfaces_are_exactly_the_ledger, test_flag_on_author_toolset_includes_render (search_assets), 4× test_scene_turn_persist + test_p37 pinned-kit (duplicate design_agent_run insert).
- Uncommitted work set aside in LOCAL branch wip/harness-alignment-uncommitted-20261020 (19501097f, never push) + backup patch/tarball in the session scratchpad. RESTORED (uncommitted): scene wording (9 files), memory notes, docs, trials, reports, scripts/design_workspace_export.py.
- NOT restored, awaiting founder: Head of ABM prompt v19 (brief contents + angle menu). Main now has profile v75 / manual v21 and already ships its own "page briefs give Design direction, not copy" (530e8172d, open_design_leg text). Re-mint would need profile v76 + manual v22 (generated chapters name the profile) + stage0-interview bump (its manual paths) + pins + test hashes.
- Lane DB (clue_nashville_pm_clone) is still at 546277c8bd9d; running stack processes hold pre-merge code — `alembic upgrade head` then restart before using the lane on the merged code. Throwaway DB clue_dushanbe_imgtest2 is at cba395a41e66.
- 2026-10-20 Head of ABM re-minted on main's v75 (UNCOMMITTED, under trial; founder OK after confirming rounds 1–4 + today's runs all used our old uncommitted v72, profile_sha256 67445667…): prompt v19 (our brief-contents + angle-menu paragraph; base v18 identical to main's), profile v76 = v75 + prompt v19 + manual-*@v22 + stage0-interview@v49, manual v22 = v21 copies with version/paths moved and tools/limits regenerated (`python -m clue_api.manual_build --write`; `--check` current), stage0 v49 = v48 with 6 manual links → v22. Pins: build.py (MANUAL v22, PROFILE v76), agent_registry_wiring HEAD_OF_ABM v76, composer_context head-of-abm@v76. Tests: catalog lists + registry manifest f1335bb8… + s4e + comprehensive → 148 passed. Our old open_design_leg text edit dropped (main's 530e8172d text already says Design writes the words).
- 2026-10-20 lane stack stopped (dev_stack.sh down); lane DB clue_nashville_pm_clone migrated 546277c8bd9d -> cba395a41e66 (13 upgrades: main's website/site/discovery chain + the merge). Stack still DOWN; next: dev_stack.sh up.
