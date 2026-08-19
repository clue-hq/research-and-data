# Chat-Driven Website Generation — Ratified Plan (the generation mount)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development,
> task-by-task. **Process rule (founder, binding): Opus agents implement; the
> orchestrating session reviews every diff INLINE itself — never via a reviewer
> subagent.** TDD throughout. Local commits only, never push, no AI attribution.
> This doc is self-contained: every file:line fact was verified 2026-08-19 against the
> trunk at `9c1e6766` (post-W4-exit-gate) — line numbers drift; re-verify anchors before
> editing.

**Where it runs:** the trunk (`integration/frontend-design-part-iv-v2`) or its successor.
Slices 0–2 (backend) may run in parallel with W5 preparation; **slice 3 (frontend) starts
only after the W5 acceptance audit is signed off** — it touches `chat-surface.tsx` and the
rail-refresh seams that W5 audits, and auditing a moving surface voids the audit.

**Goal (the founder's sentence, and this plan's definition of done):** a marketer chats
with the platform deepagent on `/projects/{id}/chats/{chatId}`, asks for a landing page,
and the platform deepagent routes to the design deepagent — which **creates** a web
document, **generates** the page, and iterates on it through further chat messages — while
the artifact appears in the rail's gallery, opens in the editor the W-plans built, accepts
manual inspector edits between chat turns, and closes out ("lock it in") returning control
to the platform deepagent. One thread, one conversation, both agents, real microsite.
**Amendment (founder-ordered, 2026-08-19): the generated website is BRAND-THEMED** —
when the workspace has an approved brand kit (born from the now-merged brand-kit
ingestion pipeline: website scrape / PDF / assets → versioned draft → human approval on
the Brand-context screen), the leg-born document carries that kit as its theme, so the
deepagent's generation writes the client's real brand tokens, not the platform default.

---

## 1. What is ALREADY BUILT (verified — do not rebuild any of this)

The study behind this plan (two deep scouts + controller verification, 2026-08-19; memory:
`_memory/2026-08-19-*`) found the platform much further along than the stale CLAUDE.md
line ("Part III not wired") suggests. **Part III is built, merged, and on this branch**
(P3.1–P3.7, merge `199d1a76`, ancestor of HEAD):

- **The web deepagent generates complete landing pages** — a three-role trio
  (orchestrator → `lumen-web-author` → `lumen-web-reviewer` with Playwright screenshots at
  1440/768/375) driven by `run_deepagent_web_turn`
  (`subsystems/clue-design/apps/agent_runtime/lumen_agent/harness_web.py:214`; prompts
  `prompts_web.py`; empty-document → "this turn creates the page" branch at
  `harness_web.py:43-49`). Entry: `POST /documents/{id}/web/turns`
  (`apps/api/lumen_api/main.py:2978`), which enqueues a `DesignTurnEnvelope(kind="web_turn")`
  onto the platform fleet; the executor `execute_web_turn_job` (`main.py:7948`) OWNS the
  persist under a `base_version` CAS guard (`main.py:7981-7983`).
- **The leg substrate + routing rule are live:** `design_leg` table with
  one-open-leg-per-thread (`alembic/versions/549de68ae3b9…`), `open_design_leg` on the
  Head-of-ABM belt (profile **v36**, `platform/agents/catalog/profiles/head-of-abm/v36/profile.yaml:68-72`;
  authority `agent_registry_wiring.py:165-169`), worker-side routing open-leg→design
  (`agent_turn_fleet_wiring.py:385-455`), the exit judge + `finish_design_leg` + mis-exit
  reopen (P3.5/P3.6/P3.7b), leg lifecycle frames on the chat turn stream
  (`chat/turn_events.py:93-96`: `leg.opened/awaiting_user/closed/reopened`), and the
  fail-closed brand pin consumed design-side (`main.py:7861-7899`).
- **The display side is done:** the rail's gallery feed derives from legs —
  `project_design_documents` (`design_leg_wiring.py:393-452`), web-only
  (`WHERE d.doc_kind='web'`, `:444`), **no leg-state filter** (a document appears in the
  rail as soon as any leg names it, open or closed); served at `chat/router.py:1004-1101`;
  consumed by the chats-route rail since chat-flow slice 1. The whole editor experience
  (W0–W4 + chat-flow R6) awaits the artifact.
- **The BFF already reaches everything:** the design proxy
  (`apps/frontend/src/app/api/clue/design/[...path]/design-proxy-handler.ts`) is a
  wildcard, session-proving, `X-Workspace-Id`-stamping, SSE-capable pass-through. The
  frontend even carries the web-turn HTTP client as **dead code**
  (`features/design-editor/engine/webDocuments.ts:377-419` `startWebTurn`; `:299`
  `createWebDocument`) — zero callers outside its own tests.
- A live API smoke (2026-08-14) ran a full design creation through the trio on the
  platform gateway end to end (`_memory/2026-08-14-part3-multiagent-review.md`).
- **The brand-kit pipeline is merged onto this trunk** (`81e961ce`, 2026-08-19 — the
  brandkit-onboarding worktree's slices 1–6): ingestion (website scrape / PDF with
  vision assist / assets) → versioned draft kits → human approval on the
  `/brand-context` screen (re-extract publishes a new draft version), auto-enqueued at
  first-time provisioning, and — the load-bearing fact for this plan — **the frozen
  creation contract**: `subsystems/design/clue_design/documents.py::create_document`
  stamps the **latest approved** brand kit onto every new web document at birth
  (explicit `scene.theme.brand_kit` ref wins; single-brand workspaces only — multi-brand
  fails closed; approval never re-stamps existing documents; selection owned by
  `brand.py::latest_approved_brand_kit_ref`). Because the web agent's own hard law is
  "every color must be a theme token", a kit-stamped document makes generation
  brand-themed **by composition** — no new mechanism. The leg's fail-closed brand pin
  (`design_leg.brand_kit_id/version`, consumed design-side since P3.7c,
  `main.py:7861-7899`) is the version-honesty half.

## 2. The FIVE BLOCKERS this plan removes (each verified at its line)

| # | Blocker | Anchor |
|---|---|---|
| B1 | The design leg **always dispatches the scene (ad) agent** — `kind="agent_turn"` is a hardcoded literal, and the scene path is preview-only (persists nothing). The web harness is unreachable from chat. | `platform/api/clue_api/design_leg_wiring.py:1097` (verified: builds `config.request.scene` unconditionally); executor split `subsystems/clue-design/apps/api/lumen_api/fleet_handler.py:423-427` |
| B2 | **No leg can create a document.** `OpenDesignLegInput.document_id` is nullable ("a leg may create its document, §2.1", `design_leg_tools.py:158-159`) but the resolution path only validates an existing id; `legs.py`'s only mutators are state transitions; `execute_web_turn_job` requires `envelope.document_id`. "Make me a landing page" has nowhere to land. | `design_leg_tools.py:~500-527`; `subsystems/design/clue_design/legs.py` (open_leg`:57` takes `document_id` at birth — the key to the fix); `main.py:7972` |
| B3 | **`design_runtime_enabled` defaults False** — `open_design_leg` refuses before any DB touch, and the fleet worker composes no design lane. | `libs/clue-config/clue_config/settings.py:273`; `design_leg_tools.py:288-294`; `fleet_main.py:765,851,862` |
| B4 | **The chat agent is never told design exists.** Head-of-ABM prompt v4 + Stage-0 skill contain zero design/website/leg content; the model's only signal is one tool description. | `platform/agents/catalog/prompts/head-of-abm/v4/SYSTEM.md` (grep-verified) |
| B5 | **The platform frontend cannot see any of it.** No consumer of the `leg.*` frames or speaker projection; no design-run SSE client; the web-turn client is dead code; nothing refreshes the rail/canvas when a design turn lands. | grep-verified: `leg.opened|design_leg` in `apps/frontend/src` hits one fixture title string |

**Explicitly NOT blockers** (already handled): tenancy (BFF stamps the workspace header
server-side), streaming transport (proxy forwards `last-event-id`, returns unbuffered
bodies), the exit contract, per-thread single-flight, crash re-entry, undo (web turns
commit under CAS; the editor's undo stack covers regret).

## 3. Founder decisions — F1–F5 (answer before the slice that names them)

- **F1 (before slice 1) — v1 generation scope.** One-page landing page, fixed
  landing-page/ABM recipe, closed component vocabulary, **direct-commit web turns** (no
  propose→accept gate — matching the shipped web editor UX; the scene path's accept gate
  does not apply, and the editor's undo + the leg's mis-exit reopen cover regret).
  *Recommendation: confirm as stated.* Multi-page, accept-gates, and vocabulary growth are
  registered out of scope (§8).
- **F2 (before slice 3) — what happens on first generation completion.** Options:
  (a) the card simply appears in the rail's gallery and the agent's transcript reply names
  it (zero new UI — cleanest under the dummy-is-presentation-truth rule); (b) the artifact
  tab auto-opens on the *first* birth of a leg's document (uses only the existing
  `shell.openArtifact` machinery, but is behavior the dummy never specified).
  *Recommendation: (a) for v1; (b) is a one-line addition later if living with (a) annoys.*
- **F3 (scope fence, confirm now) — live build-streaming onto the canvas** (watching
  sections appear as the agent works) stays a **separate follow-up plan** (it was already
  deferred by chat-flow §6 item 2). V1 shows progress in the transcript and re-renders the
  canvas when the turn completes. *Recommendation: confirm the fence.*
- **F4 (scope fence, confirm now) — selection-scoped chat edits** ("make THIS button
  red" while a canvas node is selected → `target_node_ids`) need the `focus_refs`
  vocabulary widened past account|contact (schema + DB CHECK + reader,
  `chat/schemas.py:139` et al.). *Recommendation: out of v1; registered §8. The user
  can already hand-edit any node precisely with the inspector between chat turns.*
- **F5 (before slice 2) — the born document's title.** The tool gains an optional
  `title`; the platform deepagent supplies it from the user's ask ("Insight Health
  landing page"); absent → first ~8 words of the brief. *Recommendation: as stated.*

## 4. Architecture of the fix (the shape, before the slices)

**One principle: extend the leg, don't invent a second path.** The leg is the ratified
HITL carrier (PD-part3 D1–D5); everything in this plan makes the *existing* leg able to
carry web work, then makes the frontend show what the leg already emits.

1. **Document birth at leg-open** (kills B2 with zero new mutators): when
   `open_design_leg` is called with `document_id=None` and `doc_kind="web"` (new input
   field), the tool's resolution path creates the empty web document through the same
   governed seam the 49 design tools use (`platform/api/clue_api/design_tools.py` →
   `lumen_api.toolbelt` `design_create_document`, forced `doc_kind="web"`,
   idempotency-keyed on the tool invocation so a retried turn cannot mint twins), then
   opens the leg with that `document_id` pinned at birth (`legs.py::open_leg` already
   accepts it) and `document_version_guard=0`. Consequence, for free: the rail's
   derivation picks the document up immediately (no state filter) — the card appears in
   the gallery the moment the leg opens.
   **Brand-theming amendment:** the birth MUST route through the DAL's
   `create_document` (the governed tool already does — verify, don't assume), because
   that is where the frozen creation contract stamps the workspace's latest approved
   brand kit. Then close the loop on version honesty: read the born document's stamped
   kit ref back and pin it as the leg's `brand_kit_id`/`brand_kit_version` (the D5
   fail-closed pin the design runtime already consumes) — so every generation turn on
   the leg designs against exactly the kit version the document was born with, even if
   a newer version is approved mid-conversation. No approved kit (or a multi-brand
   workspace, which fails closed by contract) → the document keeps the platform default
   theme and the leg carries no pin — generation still works, un-branded, honestly.
2. **Turn-kind dispatch by document kind** (kills B1): `DesignLegTurnRunner._envelope`
   reads the leg document's `doc_kind`; `web` → `DesignTurnEnvelope(kind="web_turn")`
   with a `WebTurnRequest`-shaped `config.request` (`prompt`, `base_version` = the
   document's *current* version read at envelope build — the executor's CAS re-check
   remains the authority, `main.py:7981-7983`; `target_node_ids` empty in v1 per F4;
   `model` unset → design default), keeping `config.leg` (the brand pin P3.7c already
   consumes), `config.delegation_bundle`, and `config.history` exactly as today.
   `scene` documents keep the existing `agent_turn` path byte-identical.
3. **Teaching + the versioning wave** (kills B4, carries the F5 schema change): one
   coordinated version bump — `open_design_leg@2` (adds `doc_kind`, `title`), Head-of-ABM
   prompt v5 (a short "website/design delegation" section: when to open a leg, what to
   put in `brief`/`title`, what the leg does, that further messages route to the design
   agent until lock-in), profile v37 pinning both, Recipe #0 v17 re-pinning the tool in
   its four sites — executed by the documented pin ritual (§6 trap 1).
4. **The visible loop** (kills B5, minimal and designed-slot-compliant): the design
   turn's reply already lands on the thread as an `agent_turn` row (D3) and flows through
   the existing chat stream — the transcript shows it with **no new UI**. Slice 3 adds
   the two missing reactions: (a) render the `leg.*` lifecycle frames as ordinary
   transcript system-lines (the pattern the transcript already uses for gate/queue
   events), and (b) when a design turn completes on the active thread (its stream frame
   arrives), re-fetch the gallery feed and bump the canvas reload nonce so the rail and
   any open tab show the new version. **No speaker chip** — founder ruling, 2026-08-18
   (Part IV rulings memory): the transcript's own attribution is the display.
5. **Iteration loop synergy already in place:** R6's dismiss-on-send means a user who is
   hand-editing presses send → the dock yields → the message routes to the open leg → the
   web turn commits → the canvas re-renders. Manual inspector edits and chat edits
   interleave on the same document under the same CAS/undo machinery. Nothing to build —
   but slice 4 proves it explicitly.

## 5. Slices

### Slice 0 — enablement preflight (no new code; half a day)
- Dev env: `CLUE_DESIGN_RUNTIME_ENABLED=1` for the platform API **and** the fleet worker;
  design API env needs `LUMEN_AGENT_API_KEY` explicitly (`CLUE_OPENROUTER_API_KEY` does
  NOT flow through — the recorded 2026-08-14 smoke trap).
- Prove the substrate before any code: (1) `open_design_leg` preconditions pass (no
  `design_leg_runtime_not_configured` refusal); (2) a **hand-driven** web turn through
  the BFF on a scratch web document (`POST /api/clue/design/documents/{id}/web/turns`
  with a real brief) runs on the fleet and commits — this re-proves the whole Part-II/III
  substrate on today's trunk before slice 1 builds on it.
- Record the working env/launch recipe in `_memory/` (ports, flags, keys, worker).
- Commit: `chore(genweb): design runtime enabled in dev + substrate preflight record`.

> **Slice 0 OUTCOME (2026-08-19): PASSED — the substrate is proven end to end on this
> trunk** (BFF-driven turn → embedded worker claim in ~2s → trio → committed v0→1 in
> 6m29s → artifact route renders it; `_memory/2026-08-19-genweb-slice0-preflight.md`
> holds the working recipe incl. the NEW `LUMEN_AGENT_BASE_URL` trap). **One blocker
> found and adopted into slice 1's scope:** the reviewer's page previews have no size
> ceiling (`lumen_agent/tools/view.py::_normalize_image_bytes` clamps only a 512px
> floor), so any page taller than ~8000px — roughly 3–4 sections, i.e. nearly every
> realistic landing-page brief — kills the review call (`invalid_prompt: image
> dimensions exceed max allowed size`), the transactional turn discards ALL authored
> nodes, and `result.diagnostics` stays empty. Slice 1 therefore also ships: a
> downscale-to-ceiling (or tile) clamp in `_normalize_image_bytes` with tests, and the
> review-failure reason landed as a real diagnostics entry. Also recorded: a no-kit
> workspace births an ALL-NULL theme (not a "platform default kit") — slice 2's tests
> assert that real fallback shape.

### Slice 1 — web-turn dispatch (backend; B1) + the preview-ceiling fix
- `DesignLegTurnRunner._envelope` branches on the leg document's `doc_kind` (read with
  the doc row the runner already loads for the scene path — verify; else one store read):
  web → `kind="web_turn"` + `WebTurnRequest`-shaped `config.request` per §4.2; scene →
  unchanged. The runner's thread-summary write works for both kinds (verify the web
  result shape feeds it; adjust the summary text to name the artifact).
- Tests (DB-gated, the P3.4/P3.6 test idiom): envelope shape per doc kind; scene
  regression byte-stable; version read = current version; the web result's summary lands
  on the thread; a conflicted CAS (`conflicted_web_turn_response`) surfaces as an honest
  turn outcome, not a silent success.
- Verification: on the slice-0 scratch doc, hand-open a leg (SQL or the tool with
  `document_id` set), send a chat message on that thread → the WEB agent runs, the
  document changes, the transcript carries the reply.
- Commit: `feat(genweb): design legs dispatch web turns for web documents (B1)`.

> **Slice 1 OUTCOME (2026-08-19): DONE, live-verified** (commits `79dac699` +
> `a27440fa`; record `_memory/2026-08-19-genweb-slice1-web-turn-dispatch.md`). A chat
> message on a leg pinned to a web document now runs the WEB agent end to end: run
> `run_96cbbc52…` (`kind=web_turn`), the slice-0 doc v1→v2, transcript summary naming
> the artifact; a lost CAS race fails the turn honestly (pinned by test). The ceiling
> fix landed as a 7500px long-side clamp (LANCZOS down / NEAREST up, band-tested), and
> non-applied web turns now always carry their reason as a real `diagnostics` entry.
> **Recorded for later slices:** (a) the leg path has NO draft/published gate — the
> design API's own web-turn route calls `require_draft_document`, the leg dispatch does
> not (pre-existing for scene, inherited by web; policy decision pending); (b) the leg
> web envelope carries no `account_card`, so chat turns on account-stamped derived docs
> run un-personalized (v1 scope per F4 — name it before personalization enters chat);
> (c) downscale-not-tile: the reviewer judges long pages at reduced scale — tiling is
> the follow-up if review quality degrades; (d) a real generation took ~13 min when the
> reviewer looped once — slice 3's refresh-on-completion must not assume ~6 min; (e) the
> platform FLEET worker is where the design turn actually executes (InlineDesignLane),
> so it needs the full `LUMEN_AGENT_*`/`LUMEN_CORE_HELPER` env and must NOT inherit the
> design API's `CLUE_STORAGE_FS_ROOT` (launch traps recorded in the slice-1 memory note).

### Slice 2 — document birth at leg-open + the versioning wave (backend; B2, B4, F5)
- `open_design_leg@2`: `doc_kind: "web" | "scene" | None` (required when
  `document_id is None`; refuse `scene` creation in v1 — scene legs keep requiring an
  existing document), optional `title`. Resolution path per §4.1: governed create,
  idempotency key derived from the turn/tool invocation, leg born with the document
  pinned; `OpenDesignLegOutput` gains `document_created: bool`.
- Refusals stay typed and loud: runtime off; workspace mismatch; `doc_kind` missing on a
  document-less open; reopen path (`reopen_leg_id`) ignores the new fields (a resumption,
  not a fresh delegation — existing rule).
- The versioning wave, one commit, by the ritual (§6 trap 1): prompt v5 (the delegation
  teaching — SHORT; the tool description remains the contract), profile v37 (tool @2 +
  prompt v5), Recipe #0 v17 (four insertion sites), `C6_ACTIVE_PROFILE_VERSIONS`,
  registry digests, the exact-equality authority audit, frozen-contract digest re-pins.
- Tests: create-path (doc born web, empty, workspace-scoped, version_guard 0); twin-proof
  idempotency (same invocation replayed → same doc, `created=false` semantics); rail
  derivation picks the new doc up (extend the existing `project_design_documents` DB
  test); refusal matrix; profile/recipe pin parity suites green.
  **Brand-theming tests:** a leg-born document in a workspace with an approved kit
  carries the kit's theme ref at birth AND the leg row pins the same
  `{brand_kit_id, version}` (read back from the stored document, not re-derived); no
  approved kit → default theme, no pin; a kit approved AFTER birth does not re-stamp
  the document or move the leg's pin (the frozen-contract + D5 guarantees, asserted at
  this new call site).
- Verification: in chat (API-driven or scripted turn), ask for a landing page → the leg
  opens, the document is born, **the card appears in the rail's gallery feed read**, the
  first web turn generates the page.
- Commits: `feat(genweb): open_design_leg@2 births the web document (B2)` +
  `feat(genweb): head-of-abm v37 — the design delegation teaching (B4)`.

### Slice 3 — the visible loop (frontend; B5; AFTER W5 sign-off)
- Transcript: render `leg.opened` / `leg.awaiting_user` / `leg.closed` / `leg.reopened`
  frames as the transcript's existing system-line pattern (schema additions to the chat
  stream repository + conversation content; wording founder-visible in review). Design
  agent replies already render (verify role=design turns display; fix attribution only if
  broken — no new UI).
- Refresh: on a design-turn/leg frame for the active thread → re-fetch the gallery feed
  (the slice-1-of-chat-flow server helper via a client read or router refresh — match the
  existing data-flow idiom) and bump the canvas reload nonce (`useWebEditingSession`
  already exposes the seam). Apply F2's ruling.
- NO speaker chip; NO new visible components; NO design-run SSE port in v1 (the chat
  stream's frames are the signal; the run-level progress stream is the F3 follow-up).
- Tests: pure decisions for frame→refresh mapping (the repo's `tsx --test` idiom);
  stream-repository parse tests for the new frame kinds.
- Browser: full loop — ask in chat → card appears → open tab → page renders → iterate via
  chat → canvas updates after the turn → hand-edit via inspector → send another message
  (dock dismisses per R6) → the edit and the chat turn coexist (versions advance, undo
  sane).
- Commit: `feat(genweb): the chat surface shows the design leg — frames, feed refresh, canvas reload (B5)`.

### Slice 4 — end-to-end acceptance + close-out (~1 day)
- The definition-of-done walk, scripted for the founder: strategy chat → "build me a
  landing page for <account>" → leg opens (transcript line) → generation (~minutes) →
  card in rail → open → real page → "make the hero darker" → change lands → inspector
  hand-edit → "lock it in" → leg closes (transcript line) → platform agent resumes with
  the summary → mis-exit check ("go back to the design" reopens the same leg).
- **The brand-themed walk (the amendment's acceptance):** run the ingestion pipeline for
  a real brand (website scrape suffices), approve the kit on `/brand-context`, then ask
  for a landing page in chat → the generated page's colors/type resolve through the
  approved kit (visual: the brand's palette on the page; engine: the document's theme
  ref = the approved `{kit, version}`; inspector: the color popover lists the KIT's
  tokens — the W4.0 theme feed picks this up with zero work). Counter-walks: a
  workspace with no approved kit generates on the platform default theme; a kit
  approved mid-conversation does not re-theme the open leg's document.
- Full gates (frontend suite/lint/build + backend targeted suites + `make check` with the
  5 known pre-existing reds recorded), contract/doc recordings (this plan's status
  header; the CLAUDE.md stale Part-III line fixed with a dated supersession), `_memory/`
  close-out, founder walkthrough script.
- Commit: `docs(genweb): chat-driven website generation — acceptance record + close-out`.

## 6. Constraints & traps (bind every slice)

1. **The version-bump ritual is exacting** — profile/recipe/digest pins are exact-equality
   audited; follow the documented sequence in
   `_memory/2026-08-16-part-iii-merge-into-platform-base.md` (version collisions,
   `C6_ACTIVE_PROFILE_VERSIONS`, aggregate manifest digest re-pin, merged-count
   arithmetic). Never hand-edit a frozen prior version; mint the next one.
2. **The design API trusts `X-Workspace-Id` blindly by contract** — every new platform→
   design call rides the existing seams (`design_tools.py` / the BFF), never a raw HTTP
   call with a hand-set header.
3. **Idempotency on document birth is non-negotiable** — a retried `open_design_leg`
   invocation must not mint a second document (key on the tool invocation identity, the
   A9 discipline).
4. **Scene behavior is frozen** — every slice carries a scene-path regression test;
   the ad flow's preview semantics must be byte-stable.
5. **No UI invention** — the dummy frontend is presentation truth; data with no designed
   slot stays invisible pending founder ruling (the F2 gate exists for exactly this).
6. **Repo traps carried forward:** `tsx --test` (never vitest); no sync setState in
   effects; port-check before every server launch (four dead-server incidents on this
   branch); `LUMEN_CORE_HELPER` for the design API; `LUMEN_AGENT_API_KEY` for the design
   runtime; any `lumen-web` change needs helper rebuild + API restart (none expected —
   this plan touches no Rust); `make check` carries 5 pre-existing reds (recorded
   2026-08-16/19, other lanes').
7. **Model/economics note:** the design trio runs its own pinned models via the platform
   gateway (`profiles/design/v1/profile.yaml`); a full generation turn is minutes and
   ~40+ LLM calls (the smoke's shape) — set that expectation in the transcript wording
   ("this takes a few minutes"), don't engineer around it in v1.

## 7. Launch recipe (dev)

Ports 3030 (frontend) / 8030 (platform API) / 8010 (design API), all port-checked first.
Platform API + fleet worker: `CLUE_DESIGN_RUNTIME_ENABLED=1`. Design API:
`LUMEN_CORE_HELPER=<repo>/subsystems/clue-design/target/release/lumen-api-helper`,
`LUMEN_AGENT_API_KEY=<openrouter key>`. One platform fleet worker running with the design
lane composed (slice 0 records the exact command). Test login per
`_memory/2026-08-17-w01-shell-lift-file-set.md`. Browser work: Playwright MCP only.

## 8. Out of scope (registered, never silently dropped)

1. **Multi-page microsites** — no AddPage/RemovePage `WebOperation` exists
   (`crates/lumen-web/src/ops.rs:53-130`; agent pins `HOME_PAGE_ID`). Engine + agent +
   editor work; own plan, founder-gated.
2. **Live build-streaming onto the canvas** (F3) — the design-run SSE consumer +
   `design.*` progress rendering; the follow-up plan chat-flow §6 item 2 already named.
3. **Selection-scoped chat edits** (F4) — `focus_refs` widening past account|contact.
4. **Propose→accept gate / clarification rounds on web turns** — the web harness has
   neither (`useWebAgentTurn.ts:10-13`; no clarification tool in `harness_web.py`);
   direct-commit stands per F1.
5. **Content-plane bundle consumption** — the design harness reads `config.request` (+
   the brand pin) and stays bundle-blind to claims/content-schema (recorded residual,
   `_memory/2026-08-14-p34-leg-engine.md:73-76`); joining research outputs to page copy
   is the Doc-S content-plane story.
6. ~~**Brand-kit onboarding** — its own live worktree; when an approved kit exists, the
   leg's brand pin and the theme feed pick it up with zero work here.~~ **[SUPERSEDED
   2026-08-19 — the worktree MERGED (`81e961ce`) and brand-themed generation entered
   THIS plan's scope by founder order: §4.1's stamp-at-birth + leg pin, slice 2's
   tests, slice 4's brand-themed walk.]** Still out of scope from that pipeline:
   multi-brand kit selection (the create contract carries no `brand_id` selector and
   fails closed — a future contract change), manual re-stamping of pre-approval
   documents, and tone/knowledge extraction feeding page COPY (that is the content
   plane, item 5).
7. **Publishing/share chrome + public-URL routing** (master plan Part IV item 5; founder
   ruled tenant-subdomain v1) — own contract.
8. **Scene-leg document creation** — v1 refuses `doc_kind="scene"` creation; the ad flow
   keeps its editor-first shape.

## 9. Effort

Slice 0 ≈ 0.5d · Slice 1 ≈ 1d · Slice 2 ≈ 1.5–2d (the ritual is the cost) · Slice 3 ≈
2d · Slice 4 ≈ 1d → **6–7 focused days**, sequenced so slices 0–2 can overlap W5
preparation and slice 3 follows the W5 sign-off.
