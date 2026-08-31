# Website-editor integration — W5 acceptance record

Recorded 2026-08-19 on `integration/frontend-design-part-iv-v2` (post-W4-exit-gate,
post-W5.1 fix `15d7a6c8`). Contract: `web-inspector-mapping-contract.md` (v1, fully
ratified 2026-08-17). Item numbering follows `decisions-recorded.md`.

**Method.** Every VISIBLE behavior was proven against the running app in the browser on
this HEAD: the W4 exit-gate consolidated sweep (2026-08-19 — §1 22/22 live with
engine-verified writes, §2 6/6 absent, §3 5/5 provably inert; evidence
`.playwright-mcp/w4gate-*.png`), the W5.1 fallback fix's four-scenario verification
(`.playwright-mcp` + `.context/w5-layoutonly-fix-report.md`), and the lane close-outs
for the flows exercised at full depth there (replace-image multipart upload, F2 radius
corner-clearing, rich-text range-link writes). INVISIBLE items (§4's
invisible-but-alive) are data-integrity guarantees: their evidence is the write
discipline — every facet `set` preserves unrelated tokens byte-exact (engine facet
suites, both copies), every props write resends full props from the current node (lane-B
R-B4), proven live by the §4 `tag`/`anchor_id` byte-identical API read-back — plus the
adapter batteries. W5.2's formal visual-parity gate was **waived by the founder**
(2026-08-19, "a lot of manual testing; nothing broke visual parity drastically"); the
already-completed pass's findings are registered at the bottom, not dropped.

| # | Item | Observed state | Verdict |
|---|---|---|---|
| R1 | Font family select | Visible, provably inert (interaction → engine version unchanged) | PASS |
| R2 | Colors = theme tokens only | Every color control writes tokens through the real theme feed (52-token compiled theme, F3-filtered to ~30); Custom/hex tab visible-inert | PASS |
| R3 | Padding 4→2 boxes | Two X/Y boxes on every schema; Enter/blur commit; live writes | PASS |
| 1 | Canvas → Background | Live end to end incl. the §8.2 page-root render fix: root selectable, token paints `<body>`, persists | PASS |
| 2 | Canvas opacity input | Visible-inert, no write | PASS |
| 3 | Text Link-to (conditional) | Hidden by default; appears only during a live rich-text range; binds the range link (write proven lane C W4.8b); vanishes on session end | PASS |
| 4 | Text color | Live (token popover, real swatches) | PASS |
| 5 | Size select (13 dropped, 32→3xl) | Options 12,14,16,18,20,24,32; live writes | PASS |
| 6 | Weight select | Regular/Medium/Semi Bold/Bold → normal/medium/semibold/bold, live | PASS |
| 7 | H alignment | left/center/right live (no justify exposed) | PASS |
| 8 | Text vertical alignment | Absent (hidden per ruling) | PASS |
| 9 | Stroke section | As the dummy ships it, provably inert | PASS |
| 10 | (informational: real toolbar/variant/line-spacing) | Delivered as items 24/25/26 | — |
| 11 | Image Link-to | URL + new-tab live (full-props resend) | PASS |
| 12 | Replace image | Live: multipart upload → `upsert_asset`+`replace_asset` one batch, one undo step (lane-B full proof; gate presence re-check) | PASS |
| 13 | Image Mode (Tile dropped) | Fit/Fill/Stretch → contain/cover/fill live; Tile absent | PASS |
| 14 | Shape/Radius | W4.1 engine facet; all+4 corners hydrate/write; F2 all-clears-corners proven in one op | PASS |
| 15 | Button Link-to | Live (props resend; command-form buttons refused per 36) | PASS |
| 16 | Button Style (Critical dropped) | Primary/Secondary/Transparent live; Critical absent | PASS |
| 17 | Button color token buttons | Live token popover on both chips | PASS (see W5.2 notes D2/D3 — founder-waived, registered) |
| 18 | Icon (18b) | Layout(-padding) + Layers only; icon-specific sections absent | PASS |
| 19 | Container style tokens | Live | PASS |
| 20 | Container Flex/Grid/Hide | Live, reflects real layout, interplays with the eye (40) | PASS |
| 21 | Container reverse-gap controls | Agent-only as ruled; registered §7 item 1 | PASS (registered) |
| 22 | Section Direction/Gap/Wrap | Live; gap coerces to the ratified step scale (7→6 proven); truthful Wrap=No ruling in force | PASS |
| 23 | Section Link-to | Absent | PASS |
| 24 | Rich-text toolbar | Kept as-is per ruling + the 2026-08-18 retheme amendment (inspector design language); session keys Escape/⌘-Enter | PASS |
| 25 | Text style/variant select | Added per ruling, live (heading options disabled for structured rich text) | PASS |
| 26 | Line-spacing select | Added per ruling, live | PASS |
| 27 | Slot keys / personalization | Invisible; survives every inspector write (facet byte-preservation + full-props resend) | PASS |
| 28 | Raw CSS-classes escape hatch | Invisible; unrelated tokens survive byte-exact by the facet law | PASS |
| 29 | Node move/duplicate/delete | **State corrected by the W4.10 audit (§7 item 8):** no keyboard path exists anywhere on web (upstream included); agent-only via ops (`InsertNode`/`RemoveNode`/`MoveNode`); affordance needs a future founder ruling | PASS (as honestly recorded) |
| 30 | Margin X/Y | Agent-only; preserved by the facet law | PASS |
| 31 | Computed-layout card | Dropped; absent | PASS |
| 32 | Embed → Layout-only | **Fixed at W5.1** (`15d7a6c8` — the mapper's `layoutOnly` flag now consumed): embed renders Layout + Layers only, both mounts. Note registered: the seeded embed has no user-facing selection path (live iframe swallows clicks; depth-1 layers cap) — reachable via the bridge; an embed-clickability rule is future engine work | PASS |
| 33 | Interactive components → Layout-only | Same fallback path (mapper routes component kinds → `layoutOnly`, mapper-tested); no interactive component exists in seed data — structural + fix evidence | PASS |
| 34 | Custom component props form | Live: manifest-driven form joins the (now truly) layout-only fallback; Escape-abandons vs committed-edit both proven; `set_custom_component_props` engine-verified | PASS |
| 35 | Bg-image + scrim | Agent-only; preserved | PASS |
| 36 | Button dialog actions | Invisible; inspector edits link mode only; command-form link writes refused (tested) | PASS |
| 37 | Image alt text | Agent-only; preserved by full-props resend | PASS |
| 38 | `tag`/`anchor_id` preservation | Hard guarantee proven twice: adapter battery + live API read-back byte-identical after real edits | PASS |
| 39 | Lock toggle | Visible, provably inert (document JSON unchanged) | PASS |
| 40 | Visibility eye | Live hide/show on the display facet; un-hide restores captured pre-hide value; undo-pair clean | PASS |
| 41 | Layer tree | Real hierarchy, names/kinds/selection, nesting display capped at depth 1 | PASS |
| 42 | Failure surfacing | Save-failure + 409/422 ruled (W3.3) inline-only and shipped; version-refused + publish-failure remain open for their flows (§7 item 5) | PASS (as ruled) |

**Verdict: 41/41 substantive items PASS** (item 10 is informational). The one defect the
audit itself surfaced (32/33 fallback rendering) was fixed before recording, per W5.1's
rule.

## W5.2 — visual parity (founder-waived; findings registered)

The founder waived the formal parity gate 2026-08-19 after extensive personal manual
testing. The already-completed comparison pass (13 states vs the reference PNGs AND a
live dummy-HEAD instance) is registered here:

- 11/13 states at parity modulo the ratified §2 deltas. Supporting: our
  `chat-shell.module.css` is a strict subset of the dummy's with zero
  declaration-value drift.
- **The reference PNG set is stale** (committed at dummy `03e85e0`; the dummy advanced
  3 commits) — three apparent reference mismatches are reference staleness, verified
  identical between dummy HEAD and our app (Share-menu slug, opacity cell width,
  section collapse states).
- Registered findings (founder-waived at W5; candidates for a polish pass):
  **D1 (functional, not cosmetic):** the color popover renders ~1231px tall in a
  1000px viewport with no max-height/scroll — the last ~8 tokens and the hex/recents
  footer are unreachable. **D2:** the button schema's two color chips keep the dummy's
  fixture swatch colors while their labels hydrate (container/section hydrate both).
  **D3:** the button token popover lacks the ColorControl tab-strip chrome (item 17's
  "dummy Theme-tab pattern" is partially applied). **D4:** the edit-mode selection
  overlay draws drag-grip/handle dots with no dummy equivalent — adjacent to §7 item 6
  (in-canvas resizing) and ruling 29; wants a founder ruling on whether the affordance
  stays visible while inert.
- Minor notes (recorded): inspector header titles are dummy fixtures (matching the
  dummy exactly); image radius fields render blank vs the dummy's 0/4 placeholders;
  the seeded doc's image asset 404s in both apps; custom-component prop labels are raw
  schema keys.

## W5.3 — gates

- `apps/frontend`: design-system:build ✓ · `npm test` **772/772** · lint ✓ · production
  build ✓ (re-run at recording).
- Root `make check`: 5 failures, all **pre-existing and provably unrelated** (zero
  backend paths touched by W0–W5; recorded at the Part-III merge note 2026-08-16 and
  re-verified 2026-08-19: pilot-budget-controls ×3 [dev-DB field-registry drift],
  unified-agent-gate-migration head pin, o3-account-deep-behavior skill-version pin —
  owned by their lanes).

**Founder sign-off:** pending — this record is the input to it.
