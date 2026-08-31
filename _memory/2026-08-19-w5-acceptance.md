# 2026-08-19 — W5 acceptance audit COMPLETE (website-editor integration closed, pending founder sign-off)

Branch: `integration/frontend-design-part-iv-v2` (istanbul). Plan:
`docs/superpowers/plans/2026-08-17-website-editor-integration.md` — W5 marked done.
Record: `docs/specs/website-editor-integration/acceptance-record.md`.

## What happened

- **W5.1 (contract audit):** the pre-record sweep surfaced ONE defect — the schema
  mapper computes `layoutOnly: true` for embed/component/custom-component kinds
  (`hydrate.ts:174-176`) but `web-inspector.tsx` never consumed it, so §5 fallback
  kinds rendered the full container view (Link/Style/Alignment inert-but-present)
  instead of Layout-only. Fixed per W5.1's fix-before-recording rule: `15d7a6c8`
  (Opus implemented, controller reviewed inline; both mounts thread the flag; real
  containers byte-stable; four-scenario browser proof incl. the lane-C custom
  component). Then the 42-item record composed: **41/41 substantive PASS** (item 10
  informational), built on the same-day W4 exit-gate sweep + lane close-out deep
  proofs + the fix verification; §4 invisible items recorded on the write-discipline
  evidence (facet byte-preservation, full-props resend, live tag/anchor_id read-back).
- **W5.2 (visual parity): founder-waived mid-run** ("a lot of manual testing; nothing
  broke visual parity drastically"). The pass had just completed, so its findings were
  REGISTERED, not dropped: 11/13 states parity modulo ratified deltas; the reference
  PNG set is STALE (committed at dummy `03e85e0`, dummy advanced 3 commits; the
  verifier stood up dummy-HEAD on :3080 as a second baseline and confirmed 3 apparent
  diffs are reference staleness; our chat-shell CSS is a strict declaration-value
  subset of the dummy's — zero drift). Registered founder-waived findings:
  **D1 functional** — `.inspectorColorPopup` ~1231px tall in a 1000px viewport, no
  max-height/scroll → last ~8 tokens + hex/recents unreachable; **D2** button chips
  keep fixture swatch colors while labels hydrate; **D3** button token popover lacks
  the ColorControl tab-strip chrome; **D4** edit-mode selection grip/handle dots have
  no dummy equivalent (adjacent §7 item 6 + ruling 29 — wants a ruling). Minors in the
  record.
- **W5.3 (gates):** frontend design-system:build / **772/772** / lint / build green;
  `make check` = the same 5 pre-existing reds (pilot-budget ×3 dev-DB registry drift,
  gate-migration head pin, o3 skill pin — other lanes'; W0–W5 touched zero backend
  paths).

## Also registered en route

- Embeds have **no user-facing selection path** in the seeded doc: live iframes keep
  `pointer-events:auto` (canvas clicks land inside the embedded page) and the depth-1
  layers cap hides deep embeds; custom-component frames DO get pointer-events:none in
  edit mode. One-rule engine change if wanted; needs a ruling.

## State

**The website-editor integration plan (W0–W5) is COMPLETE** on this branch, pending the
founder's sign-off on the acceptance record. The chat-flow integration is complete.
Next per the founder's direction: the chat-driven website generation plan
(`docs/superpowers/plans/2026-08-19-chat-driven-website-generation.md`) — awaiting its
F1–F5 rulings; slice 0 (enablement preflight) can start immediately after.

## Founder decision queue (accumulated, one place)

1. Generation plan F1–F5 (scope, completion behavior, streaming fence, selection-scoped
   edits, document title).
2. Artifact-identity URL param (chat-flow deep-link limitation).
3. Node-op affordance (contract §7 item 8) + the D4 selection-grip visibility.
4. D1 color-popover overflow fix (functional; small).
5. Embed clickability engine rule (§5 note).
