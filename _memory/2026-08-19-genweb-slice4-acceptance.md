# 2026-08-19 — genweb slice 4: the end-to-end acceptance walk (evidence + one blocker)

Plan: `docs/superpowers/plans/2026-08-19-chat-driven-website-generation.md` §"Slice 4".
Brief/report: `.superpowers/sdd/2026-08-19-chat-driven-website-generation/slice4-{brief,report}.md`.
Branch `integration/frontend-design-part-iv-v2`, worked directly. **No code changed in this
slice** — docs + this record only.

## Verdict in one line

The chat-driven generation loop is REAL end to end — ask → leg opens → document born → page
generated with layout → chat iteration lands → hand edit interleaves — and brand-themed
generation works exactly as designed. **One step of the definition-of-done walk could not be
exercised: "lock it in" does not close the leg**, because the design-leg exit judge cannot be
built in any deployment carrying the default gateway config (details below). It is a config/code
defect that predates this plan and this is its first live exercise.

## Stack used (all four relaunched mid-session after the controller stopped everything)

`/tmp/slice0-relaunch-8010.sh` (design API 8010), `/tmp/slice3_platform_8030.sh` (platform API
8030), `/tmp/slice15_fleet_worker.sh` (istanbul fleet worker), frontend 3030 from
`apps/frontend` with `CLUE_API_BASE_URL=…8030 CLUE_APP_ORIGIN=http://localhost:3030
LUMEN_API_BASE_URL=…8010`. Login `onboarding+clerk_test_20260814@example.com` / `pass@123` /
code `424242`. Workspace `ws_8040294627e146ae93f753ec0d3e1726`, project
`prj_79aa603b3c3853898045e3cfa414e136`. tunis/missoula processes untouched.

## Walk 1 — the un-branded definition-of-done walk (thread `thr_54cf1fc0e3825b0f87a5d071d67627a0`)

Leg `41a7d0df-b16f-5482-b9ab-d4b57b8d988a`, document `doc_909ca0c652375d8a947ae062c5c8cdd3`.

| # | step | outcome |
|---|---|---|
| 1 | "build me a landing page for Insight Health" | head-of-abm opened the leg unprompted; transcript line **"Design session opened — your next message goes to Design."** |
| 2 | card in rail | gallery 4 → 5, card "Insight Health landing page", **no auto-open** (F2(a)) |
| 3 | document born | `doc_909ca0c65…` v0, `theme = {}`, `effective_brand_kit_*` NULL, leg pin NULL — the recorded no-kit shape (counter-walk (a)) |
| 4 | **"go ahead"** (the real G9 test) | generation ran from the leg's brief, not the two words — the envelope's `delegation_bundle.brief` is a full 900-char page brief; **520 s (8.7 min)**, v0→v1, applied/accepted |
| 5 | open the card | real page **with layout** — nav, hero, workflow card, logo band, sections (post-G7); screenshot `slice4-3` |
| 6 | **"make the hero darker"** (the G8 risk line) | **PASSED first try** — 117 s, v1→v2, hero became deep navy; canvas re-rendered live, no navigation; screenshot `slice4-4`. The slice-3 "cannot target the hero headline node" refusal did **not** recur. |
| 7 | inspector hand-edit | R6 dock; container background set from the theme popover → **v2→v3** (13:49:05) |
| 8 | **"lock it in"** | **FAILED to close the leg** — see the blocker below. The message was routed to design as an ordinary turn (23 s, orchestrator-only, no version change) and the leg stayed `open_awaiting_user`. |
| 9 | platform agent resumes with the summary | **not reachable** (step 8 blocked) |
| 10 | mis-exit check ("go back to the design") | **not reachable** (needs a closed leg) |

The leg is deliberately LEFT OPEN at `open_awaiting_user` — once the blocker is fixed, steps
8–10 can be re-run on this exact leg without re-doing steps 1–7.

## THE BLOCKER — the design-leg exit judge can never build (fail-safe → CONTINUE forever)

Fleet log, verbatim, on the "lock it in" turn:

```
{"event": "design_leg.exit_judge_failed", … ValueError: agent model timeout must be positive
 and no greater than gateway policy}
{"event": "design_leg.exit_judgment_fail_safe", "leg_id": "41a7d0df-…"}
```

Chain of facts (all verified in code, not inferred):

- `agent_turn_fleet_wiring.build_design_leg_exit_judge` builds the judge from the DESIGN role's
  profile model policy: `models.build(timeout_s=policy.timeout_s, …)`.
- `platform/agents/catalog/profiles/design/v1/profile.yaml:225` → `timeout_s: 120.0`.
- `clue_gateway/agent_model.py:490` refuses `timeout_s > self._config.timeout_s`;
  `clue_config/gateway.py:104` → `GatewayConfig.timeout_s` default **30.0**, and
  `default_gateway_config()` (the only builder used by `fleet_main`) never overrides it. There is
  no env knob for it.
- Distribution check: of the 60 profile.yaml files under `platform/agents/catalog/profiles/`,
  **59 use `timeout_s: 30.0` and only design/v1 uses 120.0** — design is the single profile whose
  model policy the gateway refuses.
- Effect: the judge always raises → `decide_exit(None)` → CONTINUE (P3.6's fail-safe envelope
  working exactly as designed) → every message, including an exit intent, is routed to the design
  lane and the leg can never close from the chat.

Why nobody saw it before: the design *runtime* builds its own models from `LUMEN_AGENT_*`, so the
design profile's model policy has exactly one consumer — this judge — and the P3.5/P3.7 tests
stub the judge. Slice 4's walk is its first live exercise.

Two candidate fixes (**not made — this slice ships no code**; founder's call):
(a) clamp in the builder — `timeout_s=min(policy.timeout_s, gateway_timeout)` (one line, no
version ritual); (b) mint design profile **v2** with `timeout_s: 30.0` (the ritual: pin bump +
digest re-pin) — but 30 s may genuinely be too tight for a design *turn* policy, which is
presumably why 120 was written; the judge only needs a small JSON object, which argues for (a).

## Walk 2 — the brand-themed walk (thread `thr_7a6bc307c6b05cc180a76f1ba41721d5`)

Pipeline run live from the UI: `/brand-context` → **Re-extract** → ingestion job
`ingest_69940921995643f092ced1043982a197` **succeeded in 104 s** → draft **v2** of
`brand_kit_ing_813df4f30f2d429a853dbccae2277a5a` → **Approve** (14:06:4x) → `approval_status =
approved`.

New chat → "build me a landing page for Insight Health" → leg `efec9b18-4d08-51e6-a415-9ca380669bf2`,
document `doc_fde077b3595250cabec404616e8f1974`. Three proofs, all captured:

- **engine** — born document `theme = {"brand_kit": {"id": "brand_kit_ing_813df4f30f2d429a853dbccae2277a5a", "version": 2}}`,
  `effective_brand_kit_id/_version` = the same, and the **leg pin** carries `{kit, 2}` (the D5
  fail-closed pin). Unchanged after the generation committed v1.
- **visual** — "go ahead" → **586 s (9.8 min)**, v0→v1; the page renders in the kit's brand
  purple (`#533AFD` headline/CTA/links, `#EA2261` accent dot) instead of walk 1's invented
  teal/cyan. Screenshot `slice4-8`.
- **inspector** — the W4.0 theme popover lists the KIT's tokens byte-for-byte against
  `/brand-context`: Surface-brand `#533AFD`, Surface-accent `#EA2261`, Border-brand `#6D70FF`,
  Surface-canvas `#FDFDFD`, Text-accent `#4329D5`. Walk 1's un-branded document lists
  Accent `#06B6D4` / Surface-brand `#111827` (agent-invented) in the same control.
  Screenshot `slice4-9`. Zero work was needed for this — the feed picked it up, as predicted.

## Walk 3 — counter-walk (b): approval does not re-theme an open leg

After the v2 approval, walk 1's pre-approval document and leg were re-read: `theme` still `{}`,
`effective_brand_kit_*` still NULL, leg `brand_kit_id/_version` still NULL. One more chat turn on
that leg ("add a one-line copyright note to the footer", 71 s, v3→v4, succeeded) was dispatched
with `config.leg.brand_kit_id = null` **and** `config.delegation_bundle.brand_kit = null` — it
designed against no pin, honestly, and the document's theme is still `{}` at v4.

## Timings + the first live evidence on the author cap (G6 lever 1)

Counted from the fleet log's `model_call_usage` (role-tagged) and `llm_call_started`
(message-count resets ⇒ delegation boundaries); duplicate log lines de-duplicated.

| turn | wall | v | orch calls | author deleg / calls | reviewer rounds / calls | views | helper errs |
|---|---|---|---|---|---|---|---|
| walk 1 "go ahead" | **520 s** | 0→1 | 19 | **4 of 4** / 51 | **1 of 6** / 2 | 61 | 2 |
| walk 1 "hero darker" | 117 s | 1→2 | 8 | 1 / 8 | 0 | 23 | 0 |
| walk 1 "lock it in" | 23 s | — | 4 | 0 | 0 | 6 | 0 |
| walk 2 "go ahead" (branded) | **586 s** | 0→1 | 21 | **4 of 4** / 53 | **1 of 6** / 3 | 68 | 8 |
| walk 3 footer note | 71 s | 3→4 | 6 | 1 / 9 | 0 | 13 | 0 |

- **The author cap (4) is exactly consumed by a full page generation, twice, and never refused**
  (`web_author_cap_reached` fired zero times in either log). So cap=4 is live-plausible but sits
  precisely at the edge: a brief needing a fifth author round would meet the refusal, which
  routes to render→view→finalize-with-warnings. Worth watching before it is tightened.
- **Full generations still take ~9–10 min**, not the founder's 3–5 min target (G6's verdict "MET
  ONCE, NOT RELIABLY" holds; these two samples are both at the slow end). Iteration turns are
  fast: 71–117 s.
- The 8 `web_apply_ops` helper errors in the branded run are the recorded authoring-quality
  noise (G6 saw the same species).

## Gates

- **Frontend** — `design-system:build` ✓, `lint` clean, `build` ✓, `npm test` **857/857**.
- **Platform targeted** (`tests/api/test_genweb_web_turn_dispatch_db.py`,
  `test_genweb_leg_document_birth_db.py`, and the design-leg regression set `test_p34_*` ×5 /
  `test_p35_*` / `test_p36_*` / `test_p37_*` ×3) — **67 passed, 1 failed**; the single red is the
  documented pre-existing `test_p36_leg_resilience_db::test_a_gate_answer_queued_behind_a_leg_opening_still_reaches_head_of_abm`
  (`TypeError: insert_gate_answer() missing … 'expected_subject_sha256'` — another lane's
  signature drift, named as a known red since slice 2).
- **Design subsystem** (`apps/agent_runtime/tests` + `apps/api/tests/test_web_turns.py`, run
  WITHOUT the platform `.env`: `env -u CLUE_DATABASE_URL PYTHONPATH=subsystems/clue-design:…/apps/api:…/apps/agent_runtime`)
  — **604 passed, 2 skipped**.
- **`make check`** — see the report; the standing reds are other lanes' and were verified as
  such rather than chased.

## Evidence left in place (dev data)

Documents `doc_909ca0c652375d8a947ae062c5c8cdd3` (un-branded, v4, leg still OPEN) and
`doc_fde077b3595250cabec404616e8f1974` (branded, v1). Kit
`brand_kit_ing_813df4f30f2d429a853dbccae2277a5a` v2 **approved** — the workspace is no longer a
no-kit workspace, so any future un-branded walk needs a different workspace or a fresh brand.
Screenshots `.playwright-mcp/slice4-{3,4,5,6,7,8,9}-*.png` (gitignored). Two orphaned `running`
design-run rows from earlier killed sessions remain and were ignored, as briefed.

## Other observations (recorded, not fixed)

- One console error at the end of each design turn:
  `net::ERR_INCOMPLETE_CHUNKED_ENCODING` on the turn-events SSE stream. Cosmetic today (the
  transcript and refresh both land), but it is the stream closing untidily.
- The **canvas Background color control writes nothing** — picking a colour in Canvas ▸ Background
  updates the swatch but issues no request and does not bump the version; the same popover on a
  selected container DOES write (that is how v2→v3 landed). Also `Layout ▸ Padding` typed edits
  revert on blur. Both are editor-surface gaps, unrelated to this plan; worth a W-lane look.
## FOUNDER WALKTHROUGH — run it yourself in ~10 minutes (copy-pasteable)

Two generations are ~10 min each, so pick ONE of steps 4–9 (un-branded) or 10–13 (branded);
doing both is ~25 min. Everything else is seconds.

**0. Start the stack** (four terminals, from the repo root; port-check first with
`lsof -nP -iTCP -sTCP:LISTEN | grep -E ':(3030|8010|8030) '` — expect nothing):

```
zsh /tmp/slice0-relaunch-8010.sh          # design API      :8010
zsh /tmp/slice3_platform_8030.sh          # platform API    :8030
zsh /tmp/slice15_fleet_worker.sh          # istanbul fleet worker (design lane)
cd apps/frontend && CLUE_API_BASE_URL=http://127.0.0.1:8030 \
  CLUE_APP_ORIGIN=http://localhost:3030 LUMEN_API_BASE_URL=http://127.0.0.1:8010 \
  npm run dev -- --port 3030
```
Never touch the tunis / stuttgart / port-of-spain servers — other sessions own those.

**1.** Open `http://localhost:3030`. Sign in if asked:
`onboarding+clerk_test_20260814@example.com` / `pass@123` / code `424242`, then pick the
workspace.

**2.** Left rail → **Project** → **Untitled project** → the ✎ **New chat** button.

**3.** Type exactly: `build me a landing page for Insight Health` → Enter.
*You should see, within ~30 s:* an assistant paragraph naming the **Insight Health landing
page**, the grey status line **"Design session opened — your next message goes to Design."**,
and a NEW card in the right-hand Gallery (the artifact count goes up by one). The card does
**not** auto-open — that is the ruling, not a bug.

**4.** Type exactly: `go ahead` → Enter. *You should see:* **"Website generation often takes
5–15 minutes."** and a working indicator. This is the real test that the leg's brief (not your
two words) drives the generation.

**5.** Wait. When it lands (~9 min in the recorded runs) the transcript shows *"Design turn
applied on website document doc_… (now version 1): …"* followed by **"Design is ready for your
next message."**

**6.** Click the new Gallery card. *You should see:* a real landing page **with layout** — a
nav bar, a hero, cards, sections — not unstyled stacked text.

**7.** Type exactly: `make the hero darker` → Enter. ~2 min later the hero turns dark **in
place** — the canvas re-renders with no navigation and no reload.

**8.** Click **Edit** (top right). The inspector opens on the left. Click any layer (e.g.
`box_46`), then under **Style ▸ Background color** click the swatch and pick a theme token.
*You should see:* the page change and the document version bump (v2→v3).

**9.** Type exactly: `lock it in` → Enter. ⚠️ **This is the known blocker** — today the leg
does NOT close; the message is treated as another design instruction and the session stays
open. Everything after it in the original script (the platform agent resuming with a summary,
and "go back to the design" reopening the leg) is unreachable until the exit judge is fixed.

**10. (brand walk)** Left rail → **Brand context** → **Re-extract** (≈2 min) → when the palette
refreshes, **Approve**. The chip goes Draft → Approved.

**11.** Start a **new chat** in the same project and type exactly:
`build me a landing page for Insight Health` → Enter, then `go ahead`.

**12.** When it lands (~10 min), open the card. *You should see:* the page in **your brand's
colours** — the purple `#533AFD` on headline/CTA/links, the pink `#EA2261` accent — not the
generic teal a kit-less workspace produces.

**13.** Click **Edit** → any layer → **Background color** swatch. *You should see:* the popover
listing **your kit's tokens** — Surface-brand `#533AFD`, Surface-accent `#EA2261`, Border-brand
`#6D70FF` — the same values the Brand-context page shows.

**14. (counter-walk, 10 s)** Go back to the FIRST chat (born before the approval) and send any
small edit, e.g. `add a one-line copyright note to the footer`. It still designs **un-branded**:
approving a kit never re-themes a document that was born before it.
