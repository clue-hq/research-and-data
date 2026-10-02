# Brandfetch account-ad tests

User authorized replacing Logo.dev with Brandfetch and four fresh one-to-one
creatives: Clue→Google, AWS→Insight Health (insighthealth.ai), Google Cloud→NVIDIA,
Conduit→Hyatt. Preserve older approved artifacts. Brand Asset Intelligence stays
in its separate worktree; no new ingestion agent in this task.

- Removed the active Logo.dev adapter, settings and example-env entries. Removed
  local ignored credential entries without printing them. Historical provenance
  labels remain readable; cache entries containing retired-provider assets now miss.
- Two regressions observed failing before change: retired provider still contacted,
  old provider cache still accepted. After change, 141 focused logo/runtime tests
  pass; read-only reviewer reported no actionable issues. No engine changes.
- Live Brandfetch probe returned verified original logo families for all four
  targets. Hyatt has only a light-surface lockup from this provider. Other targets
  returned light/dark lockups and a mark. No generated/synthetic logos.
- Reloaded idle design API/four fleet workers; frontends, DB and storage unchanged.
- Ordinary requests sent through authenticated localhost3021–3024 Home UI, then
  standard design handoff. No supplied asset IDs, headlines or layouts. Home took
  multiple minutes and showed failed interview-evidence writes before opening
  design. Existing stale designing overlay required reload before handoff sends.
- Read-only observers record exact workspace/project/thread/run bindings and
  immutable first outputs under ignored evaluation/skill-family-v1/
  abm-brandfetch-20260916. All four first deliveries frozen: three runtime accepted,
  Google Cloud unaccepted. Independent review does not qualify the first pass:
  oversized/disconnected logos, small support, wrong Hyatt subbrand and AWS avatar
  remain. Google Cloud also required an accurately scoped product argument.
- First runs chose existing logos/native composition rather than new raster image
  generation. Correct logo retrieval is not proof of finished creative quality.
- Tightened account identity skill for whole-logo duplication, optical pairing,
  corporate/product/loyalty identity and unsuitable advertiser avatars. Account
  adaptation now binds capabilities to the exact named product. Independent
  read-only review found no actionable issue; 307 focused logo/skill tests passed.
- Founder clarified that "big" means a balanced advertiser × target pair, not a
  giant target logo. Four assisted revision turns now run through the app; original
  first deliveries remain in immutable evidence. Revisions are not autonomous
  first-pass successes. Existing approved historical docs remain untouched.
- Founder explicitly authorized committing and pushing all repository progress
  on this feature branch. Prior uncommitted September 8 experiment notes are now
  included; ignored credentials, local storage/DBs and evaluation artifacts remain
  local. All 131 accumulated commits through ae56be72 were pushed to
  origin/codex/design-agent-v1. Local and remote hashes match; working tree clean.
  An initial approval review rejected an unverified destination. Verified the
  existing origin is the private clue-hq/research-and-data repo with ADMIN access;
  the same push was then approved and succeeded. No main merge or deployment.
- Last visual checkpoint: Clue assisted revision completed and independently
  inspected: coherent Clue × Google row, charcoal/cream, enlarged support. AWS,
  Google Cloud and Conduit revisions still running at 07:41 UTC; no claim of their
  quality or completion. Conduit agent retrieved corporate identity from Hyatt's
  investor site after main-site HTTP 429s; inspect its baked background carefully.
  Resume exact revision evidence under the same ignored experiment root; do not
  redispatch or treat the earlier first-pass acceptance labels as qualification.
- Probe initially failed DNS inside sandbox; authorized network retry succeeded.
  System `python` absent; use repository `.venv/bin/python` for runtime tooling.

## Ordinary-request identity skill test (2026-09-16, in progress)

- User clarified that one-to-one ads should compose advertiser × target as one
  balanced group; fix the reusable skill rather than submit layout instructions.
- Audited prior runs: both account skills were loaded, but authored directions
  deliberately made target logos dominant. Prior assisted revisions are not proof
  of ordinary-request autonomy. Original four deliveries failed this intent.
- Replaced vague balancing with a positive reference-led procedure: select
  treatment, compare visible wordmarks, build one optically balanced group,
  connect it to the message, and review against the request as well as direction.
  Explicit target-only/name-only requests remain supported; original assets only.
- Frozen model planning probe: five no-identity-skill samples chose separate large
  target blocks; five candidate samples chose paired groups. This is plan-only
  evidence, not rendered-quality acceptance or statistical generalization.
- 166 skill discovery/materialization/format checks passed. Independent review
  found an over-broad pair-only rejection; qualified it before live dispatch.
- Four fresh ordinary requests dispatched via browser at 08:03Z: Clue to Google,
  AWS to Insight Health, Google Cloud to NVIDIA, Conduit to Hyatt. User messages
  prescribe advertiser/target/audience/square LinkedIn format, not layout or copy.
- Ignored evidence: evaluation/skill-family-v1/paired-identity-20260916. Exact source
  frozen under live-guidance. Materialized identity SHA256
  7d6992a2fb0a3ed5eaaaed66d40a72d2f157f156fa4317330366844a8e5d2579
  matches snapshot; all four read the full skill (100 lines plus tail).
- Head-of-ABM still requires a second generation confirmation. Clue and Conduit
  retried failed evidence writes before handoff; a separate latency issue.
- Do not alter live guidance during these runs. First-delivery and independent
  visual review remain pending. A note-append command initially used the subsystem
  cwd and failed before writing; rerun correctly at root, no data lost.

- First ordinary-request batch completed: all four selected paired identity, but
  only Clue and Conduit used complete wordmarks. AWS and Google Cloud misread
  transparent logo previews as baked dark plates and selected inferior symbols.
  All exceeded four minutes; runtime acceptance is not visual qualification.
- Root cause reproduced in a frozen real-logo vision probe: 5/5 original previews
  falsely described transparent wordmarks as opaque dark plates; 5/5 comparison
  previews identified transparency and chose the light-surface full lockup.
- Added candidate-scene-only asset inspection: decoded alpha counts/bounds plus
  white/charcoal comparison, while keeping the original preview and placement
  asset intact. No image/logo edits, no website or legacy changes. Regressions
  first failed for white/black transparent art; now cover translucent/opaque art,
  source bytes, scene immutability and legacy compatibility. 247 focused tests
  passed. Independent review plus palette/all-transparent edge probes found no
  actionable issue.
- Reloaded idle local design API/workers at 08:23Z after checking all tasks
  terminal. Four workspace frontends, auth, database and storage unchanged.
  Second ordinary-request batch will test the tool fix with unchanged skill.

## Closing verification for paired identity

- Second batch finished with ordinary short requests and no layout/copy/asset
  instructions. All four read the full updated identity skill; materialized SHA256
  matches frozen guidance. Actual asset views include the new inspection blocks.
- Independent rendered identity review: 4/4 pass. Clue × Google, AWS × Insight
  Health (full wordmark), Google Cloud × NVIDIA (full wordmark), Conduit × corporate
  HYATT. Separate original image/vector assets with contain fit and native text ×;
  no generated logos. Hyatt source crop is pixel-identical to its recorded crop
  from an authentic, nongenerated source. Brandfetch plus official-site fallback.
- Overall ads are NOT fully qualified: Clue small CTA/product detail and generic
  proof card; AWS small support and over-broad source wording; Google Cloud copy
  infers train/ship/infrastructure benefit absent from cited Gemini Enterprise
  evidence; Conduit product crop and routing implication remain weak. Three
  runtime accepted, Conduit completed_with_warnings. Independent quality judgment
  does not promote these acceptance labels to success.
- Finished generation after confirmation: Clue 9.35 min, AWS 10.21 min,
  Google Cloud 7.85 min, Conduit 11.12 min. None meets four minutes. Home handoff
  latency is additional. Do not report this as speed qualification.
- Frozen second-pass results and exact URLs live in ignored paired-identity-
  20260916/second-pass/outcome-summary.json; first-terminal snapshots preserved.
  This is a practical live comparison, not a causally isolated brand-library test;
  later runs may reuse legitimate crops fetched in earlier runs.
- Reloaded saved artifacts in authenticated four-port browser sessions. Existing
  stale designing status and occasional gallery auto-open races remain UI issues;
  source and live canvas exist. No auth changes, manual prompt repairs, changes
  to old approved artifacts, website harness or separate brand-agent worktree.
- Commit 2c2b5305 contains the skill/tool/regression fix; 247 focused tests passed
  and independent code review found no defect. No Rust/engine changes. One earlier
  pytest result was lost to output truncation; the focused run was repeated with a
  saved log and exit 0. Two gallery clicks raced automatic opening; inspected
  current state and continued without duplicate artifacts.


## Balanced whole-ad goal (2026-09-16, implementation checkpoint)

- User rejected the previous four paired drafts as whole creatives and explicitly
  set an active goal: compatible original logo variants (white Google on Clue dark
  treatment), optical balance, no unnecessary CTA, readable support, relevant fresh
  imagery, whole-ad balance and prior editable/save/export/four-minute criteria.
  Plan is two more rounds across Clue, AWS, Google Cloud and Conduit. Goal remains
  active and is not achieved by the previous narrow identity-pair pass.
- Current-run audit proved all four had native_copy_review_profile=null. Runtime
  accepted native labels at 16–25 source px on 1080 pages; support was 6.67–8.33px
  at a 360px view. The model described known words as readable despite that size.
- Added optional legible-feed-v1, 10px nominal em at360 (30 source px at1080), using
  the existing caller-owned gate. Preserves compact-feed-v1 and code default off.
  Explicitly selected in local ignored env and documented matching examples for
  these feed tests; running services have NOT been reloaded in this continuation.
  It also covers native separators. This is a policy floor, not proof of legibility
  or a platform specification; 32px source support remains permitted.
- Boundary tests first failed for the absent profile, then passed at25/29.999
  rejection and30/32 acceptance. All304 focused profile, review-delivery, logo,
  skill discovery, solo-runtime and format-library tests passed (exit0); log
  /tmp/balanced-account-tests.log. No Rust/core/website changes.
- Drafted revised reusable identity procedure: original reversed-pair comparison,
  visible wordmark letter heights with width for long names, no-CTA/awareness action
  decision, meaningful imagery, and whole-ad judgment. Preserves target-only/name-
  only requests, approved colored support, authentic variants on approved fields,
  and faithful/background-only variation scope. Added a short review opening before
  the JSON contract; its full rejected example still fits the first100-line read.
- Independent review corrected an initial audit error: components.md WAS eagerly
  pinned in the solo system prompt. No read_file event did not mean absent context.
  Thus no redundant load was added. Three draft over-broad rules were corrected;
  reviewer found no remaining structural blocker. This is NOT visual qualification.
- Five control planning probes all failed before model execution. Minimal diagnostic
  proved OpenRouter HTTP403: existing app key weekly limit exceeded. No behavioral
  samples, no new live drafts, no provider/billing workaround. User was asked to
  restore the existing key limit or configure an approved key; answer pending.
- Ignored evidence root balanced-account-20260916 contains frozen candidate guidance,
  exact ordinary requests/criteria for eight pending cases, original-output native
  readability audit, and baseline latency. No old artifact or user edit mutated.
- Baseline measured22–35 calls per creative, 7.85–11.12min after confirmation; model
  calls account for most time. Latency remains unresolved. Final generated quality,
  fresh-image diversity, save/reload/edit/export and four-minute delivery need live
  verification after provider access is restored. Do not mark the goal complete.
- Operational slips: an initial multi-file patch failed atomically on context, then
  was reapplied; one skill write used a subsystem-relative path from that subsystem
  and failed without modifying a file, then succeeded via the absolute path.


### Runtime readiness and provider recheck (next goal turn)

- Previous turn was progress: committed skill/profile implementation as4d0df34e,
  with304 checks passing. Live creative acceptance remains unproven.
- Second consecutive goal-turn provider check at23:28Z still returned HTTP403,
  API key weekly limit exceeded. User's provider-restoration question remains
  pending. No failed creative cases were dispatched or counted as completed tests.
- Guarded runtime reload at23:29Z checked authoritative local DB:235 fleet tasks
  done;118 design runs succeeded and5 failed; no active jobs. Reloaded only existing
  design API and four workers with legible-feed-v1. New handles68912–68916 verified
  live with expected commands; design API8010 and all four frontends3021–3024
  returned HTTP200. This is availability proof, not authenticated creative proof.
- Ignored receipt: balanced-account-20260916/runtime-reload-final.json and provider-
  recheck-2.json. Database/storage, frontend sessions and prior user edits preserved.
  If a different key is configured rather than its limit restored, reload idle
  runtime again before live tests so long-lived processes receive that key.
- Goal stays active. The same external blocker has now occurred in two consecutive
  goal turns; do not claim success or silently replace the configured provider.


### Blocked goal checkpoint

- Third consecutive goal-turn check at23:32Z returned the same provider HTTP403,
  API key weekly limit exceeded (provider-recheck-3.json). No user response restored
  access. Marked the goal blocked after the required three-turn audit, not complete.
- Implementation and runtime readiness are preserved. Remaining work requires live
  model calls: controlled skill probes, two four-brand generation rounds, independent
  visual/source review, editable-save/export checks and240-second delivery.
- Resume after the user restores the key limit or configures an approved replacement.
  A replacement key needs an idle runtime reload. Do not repeat failed generation
  batches, narrow the quality goal, or claim304 local tests establish ad quality.


### Flare selection and resumed budget check (September 16 evening)

- User selected openai/gpt-image-2.5-flare and reported a higher weekly budget.
  Verified the model's official OpenRouter page: dedicated Images API. Updated
  root/subsystem env examples and local ignored env to this model with API style
  images. Agent text model remains unchanged. Existing cache keys already include
  the configured image model, separating old-model output from new generations.
- Added Flare to known Images-API IDs and parametrized request/body/reference-byte
  tests for old2 and Flare. Wrong-transport diagnostic now recommends setting
  IMAGE_MODEL_API_STYLE=images, preserving the selected model rather than advising
  a different one. Diagnostic regressions failed before their fixes; final focused
  suite:27 passed,136 deselected; /tmp/flare-model-final-tests.log. Diff check clean.
- Broader test selection inadvertently included five DB-backed route tests. They
  failed connecting to sandbox-blocked localhost5432 before writes. Did not rerun
  against the shared live DB. Focused adapter tests above are DB-independent;
  no live generation/quality or DB-persistence acceptance claimed from them.
- Guarded reload checked235 fleet tasks done and123 terminal design runs, then
  restarted only the existing design API and four fleet workers. Verified each
  running process's model ID and API style without displaying other environment
  values. API OpenAPI route200; four frontends' unauthenticated requests followed
  normal redirects to sign-in200. This is availability, not authenticated proof.
  Initial root-path assertion expected200 incorrectly: API root404 and frontend
  roots307. Corrected route/redirect checks; no product/auth changes needed.
- Fresh key metadata still reports individual key weekly limit200, weekly usage
  200.70, remaining0. User then supplied screenshot with WORKSPACE budget500;
  another minimal actual model call still returned403, key weekly limit exceeded.
  Asked user to raise the individual key cap as well. Workspace and key limits
  must not be conflated. Both image and text service use that same current key.
- Ignored evidence: evaluation/skill-family-v1/flare-20260916 includes runtime
  receipt and dated access check. No new image, planning sample or live creative
  generated. Pending: fresh planning comparison and two four-brand rounds with
  Flare provenance, whole-ad review, edit/save/export and240-second measurement.
  Previously blocked goal was explicitly resumed; blocker audit starts fresh,
  no new goal or false completion. Preserve all prior artifacts/user edits and
  the separate brand-intelligence worktree.

### Approved Flare retry: eight live results and identity recovery

- User explicitly approved transmission of internal skill instructions, prepared
  briefs and selected four-workspace assets to the existing OpenRouter models.
  Individual key access recovered after its cap changed; no provider/key bypass.
  Scope receipt and all raw evidence stay ignored under
  evaluation/skill-family-v1/flare-20260916. No production change or new account.
- Completed two real Home-to-design rounds in the four existing authenticated
  local workspaces (3021 Clue,3022 AWS,3023 Google Cloud,3024 Conduit). Ordinary
  square account-ad requests plus normal confirmation; no skill names, asset IDs,
  prescribed headlines, geometry or image prompt supplied in user chat. The
  runtime selected reference assets and supplied their actual bytes itself.
- All eight traces prove a fresh reference-conditioned GPT Image2.5Flare call
  through the Images API. Logos remain original asset layers, not image-model
  inventions. Round1 Conduit substituted native target text incorrectly; Round2
  recovered the authentic Hyatt original from the existing workspace catalog.
- Round1 design seconds (Clue/AWS/Google/Conduit):449.237/496.913/518.322/620.707.
  Round2:538.549/421.028/532.428/481.866. These exclude preceding Home handoff.
  Zero of eight met240seconds. Model calls dominate latency, with25–38 calls
  and1.85–3.41million input tokens including repeated context per creative.
  New image model alone does not solve latency or whole-ad quality.
- Initial broad tool-free planning probe was invalid: the prompt required tools
  that were unavailable. It is not skill-quality evidence. A separate narrow
  decision probe (five control/five candidate) found both versions knew the main
  rules when explicit failure evidence was supplied; candidate avoided needless
  retry suggestions. No overall creative-quality improvement is established by
  that probe. Live rounds share existing asset catalogs, not a strict isolated A/B.
- Updated account-identity-composition guidance: inspect the complete asset catalog
  before replacing originals; a failed fetch does not invalidate stored originals;
  no self-authorized name-only substitution; neutral copy ink needs reference
  evidence; measure wrapped text before artwork boundaries and inspect final ground.
- Fixed logo-fetch error propagation. A provider identity refusal followed by an
  official-site429 previously surfaced only the429. The combined error preserves
  the original capture code and a fixed, safe provider category. No relaxed
  identity matching, tenancy, cache or download policy. Tests cover the exact
  Hyatt Hotels/Hyatt mismatch, reverse qualification, wrong host and secret-shaped
  vendor exceptions. Verified red/green before implementation; final four-file
  regression/skill suite passed92 checks. No Rust/frontend source change.
- Idle-only API/four-worker reload installed this candidate before Round2. No
  active run was killed. Frontends, DB, asset storage and user edits preserved.
  Round2 trace confirms the combined failure then autonomous catalog recovery.
- Independent review differs from runtime acceptance (runtime accepted7/8):
  Round1 Clue retains unwanted peach support; AWS text touches image boundary;
  Google has occlusion and correctly remains unresolved; Conduit lacks authentic
  target lockup. Round2 AWS spacing and visual idea improve; Conduit has a coherent
  original-logo pair and readable copy; Google fixes overlap/white ground but has
  weak repetitive account copy; Clue still chooses peach support. No user approval
  of these new outputs and no full quality/latency goal pass claimed.
- All eight saved originals export SVG/PNG without document-version mutation;
  PNG pixels exactly match their final previews. Latest four SVGs have three native
  text nodes and three independent image layers. Browser checks confirm all four
  latest correct-workspace artifacts are available; tabs retained as deliverables.
  On NEW Round1 Clue only, changed support38→37 through editor, reloaded, confirmed
  persistence, restored38 and exported SVG. Restored PNG matches first delivery.
  Reload lands on Gallery and requires reopening the artifact; record this UX gap.
  Do not claim browser edit/reload coverage across all eight from one check.
- Eight-case assessment.json, export-parity receipts and frozen first-terminal
  traces are the evidence. Do not overwrite them during future fixes. Next work:
  carry user-approved brand preferences into review, improve account propositions,
  and reduce repeated context/sequential calls while preserving visual inspection.
  Goal remains active/incomplete; this checkpoint is not a production qualification.
