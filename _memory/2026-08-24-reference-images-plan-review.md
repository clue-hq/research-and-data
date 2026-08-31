# 2026-08-24 — feature 3 (reference images in platform chat): plan review + cap ruling

Status: PLAN REVIEW ONLY — no code changed. The proposed slice (from the planning
transcript in `.context/attachments/`): typed `design_asset` context refs in the
project composer, gated to an open scene-design leg, converted to the design
runtime's `reference_asset_ids`. Two Explore agents verified every claim against
this checkout; findings below are file-cited and current as of this date.

## FOUNDER RULING (ratified in chat, 2026-08-24)

**The reference cap stays at FOUR.** The earlier "up to five" ask is withdrawn;
`REFERENCE_ASSETS_MAX = 4` (`subsystems/clue-design/apps/api/lumen_api/main.py:9115`,
"more dilutes vision context (D1)") is now the platform contract too. No bump of
`MAX_TURN_REFERENCES` (`apps/editor/src/hooks/useAgentTurn.ts:88`), no
`PLACED_PREVIEWS_MAX` change, no test rewrites for the cap. The platform composer
and accept-path validation must enforce 4.

## Verified premises (hold; do not re-derive)

- Runtime support is REAL and pixel-level: `reference_asset_ids` on
  `AgentTurnPreviewRequest` (`lumen_api/models.py:128`) → resolved by value into a
  manifest (`reference_asset_manifest`, `main.py:9187`; SVGs rasterized w/ durable
  custody) → orchestrator/author/reviewer prompts (`lumen_agent/prompts.py:211-246`,
  `:439-448`, `:505-520`) → actual base64 image parts on the image-gen call
  (`image_provider.py:384-389`). Acceptance gate already exists: finalize-accepted
  with references REQUIRES critique `reference_fidelity >= 2`
  (`lumen_agent/tools/substrate.py:3736-3756`). Provenance already stamped
  ("reference-conditioned on N attachment(s)").
- Composer attachment UI is fully built + dormant (`ai-elements/attachments.tsx`,
  `project-composer-attachment.tsx`, `project-composer.tsx:112-153`); server
  capability hardcoded off (`chat/router.py:609-614` `attachments=False`); the
  thread composer in `chat-surface.tsx` never receives the attachment props.
- Upload transport is fully built: `uploadWebAsset` → BFF `/api/clue/design/assets`
  (`design-editor/data/assets.ts`; proxy stamps `X-Workspace-Id` server-side).
  `POST /assets` lives ONLY in lumen_api (`main.py:5714`), magic-byte sniffed
  (PNG/JPEG/GIF/WebP/SVG/PDF/fonts — NOT image-gated at upload).
- The `design_node` seam (commit `8d1c8862d`) is the exact template: wire literal in
  `chat/schemas.py:159`, validation block `composer_context.py:133-186`, 61-line
  CHECK-swap migration (`54ae25174405`), translation in
  `design_leg_wiring.py:1292-1341`. `design_asset` refs can carry `version: null`
  (content-addressed; no document-version handshake needed).

## THE BLOCKER the transcript plan misses (must be in any execution plan)

**`reference_asset_ids` is silently inert on the platform leg path.** The platform
builds its own `DesignTurnEnvelope` (`design_leg_wiring.py:1325-1381`) with no
`reference_assets` key; the executor reads `envelope.config.get("reference_assets")`
(`lumen_api/main.py:8181`) where `None` means "resolved: NO references" (the
`_REFERENCES_UNRESOLVED` sentinel at `main.py:7586-7589` is what triggers in-worker
resolution). Adding ids to `config["request"]` alone → no refs, no error, no signal.
Fix options: (a) leg wiring resolves the manifest into `config["reference_assets"]`
(crosses the lumen_api import boundary design_leg_wiring has kept clean); (b) ONE
LINE in the design subsystem — `envelope.config.get("reference_assets",
_REFERENCES_UNRESOLVED)` in `execute_agent_turn_job` — so a missing key resolves
in-worker. Recommendation: (b) + strict platform accept-time validation so
worker-side 422s (which the fleet worker's catch-all swallows, per the warning at
`main.py:7548-7554`) are reduced to race edges. **Mechanism choice needs founder
ratification** (it edits `subsystems/clue-design`). Envelope test must assert
references reach the runtime (extend the `test_p34_design_leg_engine_db.py:540-571`
pattern to `config["reference_assets"]`, not just the request).

## Must-fix-in-slice (verified, latent or live today)

1. **Live history-chip bug from `8d1c8862d`:** every durable `design_document`/
   `design_node` ref renders as `@Selected account` in transcript history
   (`chat-transcript.tsx:94-115` fallback only branches on `contact`; projection
   `threads.py:625-684` has no type filter). Asset refs would multiply it. Fix the
   fallback; resolve asset labels/thumbnails at READ time via the design library
   (`media.filename`/`media.thumbnail` already on `AssetRecord`) — do NOT
   denormalize display fields into the append-only ref table (`thread_refs.py:24-26`).
2. **`prepare_composer_context_entities` crashes on design refs:**
   `composer_context.py:308-311` does unguarded `UUID(ref.object_id)` before the
   type branch → 500. Guard non-entity types.
3. **Image-kind + archived-status gates:** asset lifecycle is `ready`/`archived`
   ONLY (`toolbelt/assets.py:100`) — no uploading/failed states server-side; upload
   is synchronous. Reference path today accepts archived assets and only indirectly
   rejects non-images (`reference.preview_unavailable`). Platform validation should
   gate explicitly: raster/SVG image mime, non-archived, readable bytes.
4. **Composer gate:** no leg-open signal reaches the composer today (current design
   gate is `artifactKind === "ad"`). Expose `stream.designLeg.open` from
   `use-project-chat-controller` (one line); honest caveat: backlog-truncated
   reloads report closed (`chat-transcript.ts:98-103`). Scene-only gating is
   CORRECT and deliberate — the web path hardcodes `reference_images=None`
   (`web_substrate.py:3107`) and `WebTurnRequest` has no reference field.
5. **Send-enable ignores attachments** (`project-composer.tsx:83,192-197`) —
   attach-with-empty-prompt cannot submit (edit-target chips share this gap).

## Also noted

- Envelope path bypasses `_dedupe_and_cap_reference_ids` entirely — the cap-4 must
  be enforced in `composer_context` validation, not assumed from lumen_api.
- Generic `attachment_refs` stays disabled (correct): it is artifact-store-receipt
  currency (`schemas.py:177-184`), a different mechanism; no durable upload-receipt
  endpoint exists (`router.py:723`). `design_asset` refs sidestep it.
- Per-reference cost is real (orchestrator + reviewer each view all refs; extra
  base64 part per conditioned generate; prompt-cache prefix risk per
  `harness.py:200-212`) — part of why cap-4 ruling stands.
