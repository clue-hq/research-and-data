# 2026-08-20 — live acceptance: imagery lands after the asset-base-URL fix (D5)

Branch `integration/frontend-design-part-iv-v2`, HEAD `75d217fa`. **Verification only — no
product code changed.** This is the acceptance walk the previous record
(`2026-08-20-web-imagery-live-acceptance.md`) deferred: D5 was diagnosed there as a one-line
port drift and fixed in `75d217fa`; this run proves it in anger.

## Verdict

**Imagery lands. 3 image nodes, against a 0-node baseline that had never been beaten.**
The real Stripe logo is placed in an actual node. **No image was generated** — the director
explicitly declined generation by policy, not because the path failed.

## Setup / preflight

- Exactly **one** design API on 801x: pid 45082, istanbul, started 20:01:02 IST — after the
  `75d217fa` commit (19:53:21) with a clean tree over `apps/ subsystems/ platform/`.
  Re-checked after the run: still exactly one. Missoula's `fleet_main` (73637) carries no
  `CLUE_DESIGN_RUNTIME_ENABLED`, so it cannot poach `design_job` leases.
- Istanbul **fleet worker was dead** (previous session's worker stopped 14:24 UTC). Relaunched
  onto HEAD as pid 14802 via `/tmp/slice15_fleet_worker.sh`; design lane registered
  (`design_fleet.handler_registered kind=design_job`).
- `design_agent_run` had **0 rows `status='running'`** before starting.
- Resolved in the worker's own env: `lumen_api_origin=http://127.0.0.1:8010`,
  `settings.asset_base_url=http://127.0.0.1:8010/asset-store`,
  `AgentRuntimeConfig.from_env().asset_base_url=http://127.0.0.1:8010/asset-store`.
- `curl .../asset-store/61a219a0…` → **HTTP 200, 1922 bytes, image/svg+xml** (Stripe's logo).
- Brand kit **v6 (approved)** used; the document is bound to `…813df4f3` **version 6**.
  **v7 and v8 remain draft — nothing approved.**

## The run

Real product flow: browser → project `prj_79aa603b3c3853898045e3cfa414e136` → new chat
`thr_35ee14f41c645b9ba8ddc0f0e9d40123` → leg opened (`?surface=web`, "linked to the approved
Stripe brand kit") → second message started generation. No fallback was needed.

- Document `doc_96b26c80faa055b2ba0ebdd6e55fd81d`, run `run_c540cef868235918a86b080c55f56e17`,
  agent workspace `run_03144653644947508f2585349c68d2c1`, executed by the fleet worker.
- **Wall clock 7m 51s** (15:13:24 → 15:21:15 UTC), status `succeeded`.
- **Rounds** (deduped — the fleet log double-writes every line): **45 author, 20 orchestrator,
  2 reviewer** LLM calls; **3 preview iterations**.

## The fix is live — proven in the executing process

Fleet log, at turn start:

> `web turn asset base url resolved to http://127.0.0.1:8010/asset-store (source=config)`

And the new once-per-turn preflight, as a trace event:

```json
{"event":"asset_base_url_preflight",
 "output_summary":"http://127.0.0.1:8010/asset-store serves assets (200 for 2b0928ca4f3a3c70)",
 "payload":{"asset_base_url":"http://127.0.0.1:8010/asset-store","source":"config",
            "status_code":200,"reachable":true}}
```

No `asset_base_url_unreachable` event, no `LUMA07xx` warning.

## Hard numbers

Final `current_scene_json` (182 nodes, `assets` registry excluded):

| kind | n |
|---|---|
| container | 85 |
| text | 65 |
| button | 11 |
| icon | 11 |
| section | 7 |
| **image** | **3** |

Baseline, re-measured with the same query this session — unchanged and reproduced exactly:

| document | image nodes | total nodes | registry assets |
|---|---|---|---|
| `doc_2543706b…` | **0** | 204 | 3 |
| `doc_316aafa4…` | **0** | 167 | 1 |
| `doc_f85ad1bf…` | **0** | 210 | 2 |
| `doc_f95ba422…` | **0** | 161 | 3 |
| **`doc_96b26c80…` (this run)** | **3** | 182 | 4 |

The three image nodes:

```json
{"id":"img_2",  "kind":"image","alt":"Stripe","classes":"h-5 w-auto",
 "asset_id":"asset_ing_61a219a05909b652"}
{"id":"img_87", "kind":"image","alt":"Stripe payment card with pink-purple gradient",
 "asset_id":"asset_ing_f8ded0d6b5a66d21"}
{"id":"img_160","kind":"image","alt":"Globe with payment connection arc",
 "asset_id":"asset_ing_f0453686516c12c8"}
```

**The real logo IS placed**: `img_2` → `asset_ing_61a219a05909b652` (`logo.svg`, 1922 B,
`source.kind=manual`) — a node reference, not a registry orphan. This is the first time.

Corroboration beyond node counting — the design API's own render of the **stored** document:

- `GET /documents/doc_96b26c80…/web/render` → 200, 27,877 B, **3 `<img>` tags**, with srcs
  `asset-store/61a219a0…`, `asset-store/f8ded0d6…`, `asset-store/f0453686…`.
- Same route on baseline `doc_f95ba422…` → 200, 36,695 B, **0 `<img>` tags**.
- All three digests serve: 200 / 1922 B svg, 200 / 87,376 B webp, 200 / 131,170 B webp.
- In the product, the artifact route loads and the browser fetched
  `http://127.0.0.1:8010/asset-store/61a219a0…` → **200**; the Stripe wordmark renders in the
  header.

## The preview verdict — the thing that was broken

`iter_1/preview_1440.png` and `iter_3/preview_1440.png` show **imagery rendering, no broken
placeholders**. Last run's `iter_1` showed broken-image icons with alt text bleeding through
("Stripe", "Pink and purple gradient wave ribbons") and the reviewer BLOCKED on it. This time
the reviewer's own acceptance notes say the opposite, verbatim:

> "No horizontal overflow, clipped text, **broken image placeholder**, or unreadable body-text
> contrast is visible in the supplied previews."

and

> "How it works deliberately uses typographic/diagrammatic UI primitives with no image,
> matching the declared imagery decision."

The agent's blindness is gone: it now judges the same pixels the user sees.

## No generated image — a decision, not a failure

- `generate_image` was called **0 times** (0 occurrences in `trace.jsonl` and the fleet log).
- **No `design_asset` row was created during the run**, and **no asset with
  `record_json->source->>'kind' = 'generated'` exists anywhere in the database**, ever.
- The capability was **available**: `lumen_api.image_provider.is_configured()` → `True` in the
  worker's env, `IMAGE_MODEL_ID=google/gemini-3.1-flash-image`, and the `generate_image` action
  is exposed on the author's asset tool.
- The director declined it explicitly, twice, in its imagery decision (verbatim):

  > - Header: place actual Stripe primary wordmark asset `asset_ing_61a219a05909b652` on a light background.
  > - Hero: place actual kit abstract orange–pink fluid wave asset `asset_ing_2b0928ca4f3a3c70` as a cropped atmospheric ribbon behind/beside a hand-authored checkout/UI surface; **no generated image**.
  > - Benefits/product UI band: place library payment-card asset `asset_ing_f8ded0d6b5a66d21` exactly once … **(no generated images)** to keep product-UI-led parity.
  > - How it works: deliberately none, because the numbered integration flow should be clear, typographic, and diagrammatic.
  > - Developer/finance operational value band: place library globe payment-arc asset `asset_ing_f0453686516c12c8` once in a contained image panel …

  With four real brand assets available it preferred them over synthesis. Defensible — but it
  means **the text-to-image path is still unproven end-to-end in a live product run.**

## Finalize summary (verbatim)

```json
{"outcome":"accepted","grounding_source_count":10,"provenance_citation_count":4,
 "summary":"Built and visually verified the complete Stripe Payments landing page: branded
 header and responsive hero, developer/finance benefits, a three-step integration flow,
 operations narrative, deep-navy final CTA, and compact footer. It uses the approved Stripe
 wordmark plus selected real Stripe imagery, keeps a single verified Payments CTA destination
 throughout, and was checked at desktop, tablet, and phone widths. Mobile intentionally uses
 the required logo-and-CTA-only header."}
```

**`ladder_gap` is `null`** (0 occurrences in the trace; `"ladder_gap": null` in the fleet log).

## Known-open defects — all three bit, recorded, not fixed

1. **One bad diagnostic voids the entire page.** Iteration 0: `web_page_rejected` —
   *"1 error diagnostic(s); page not stored"* — caused by a **single** `LUMW0114` error
   (`unknown icon 'card' on 'ico_79'`). The whole 200-node authored page was discarded for one
   bad icon name. Recovered on re-author (`web_page_patched`, 201 nodes installed).
2. **`LUMW0130` dropped the logo `<img>` inside a link.** Same rejection carried
   *"inline content adjusted in `btn_2`: dropped disallowed inline tag `<img>`"* — the header
   wordmark was authored inside a button/anchor and silently dropped. The author later placed
   it as a standalone `img_2`, which is why the logo survived this time.
3. **`LUMW0212` still contradicts its own hint, and cost a whole section.** Iteration 2:
   `web_subtree_rejected` — *"3 error diagnostic(s); section not changed"* — on
   `` `text-brand`: `brand` is not a theme token `` and 2× `` `border-subtle`: `subtle` is not a
   theme token ``. One header revision was lost entirely.
4. Also seen: `LUMW0132` (`aria-label` on `<div>` not in the vocabulary; ignored) and several
   `LUMW0130` unwrappings of `<i>`.

## Still wrong (new findings, none blocking the verdict)

- **The hero ribbon was placed, rendered, then thrown away.**
  `asset_ing_2b0928ca4f3a3c70` (`payment-bento-background.jpg`) was registered via
  `use_brand_asset`, is visible as a real gradient ribbon in `iter_1/preview_1440.png`, and the
  reviewer confirmed it ("*the orange-pink fluid ribbon is visibly present as a cropped
  atmospheric asset*"). The **final** hero re-author at 15:20:21 contains no `data-asset` and no
  `2b0928ca` at all, so the asset ends **registered but referenced by zero nodes** — the old
  orphan-registry shape, now from a different cause: an author rewrite chasing the reviewer's
  typography/brand-fit notes silently dropped the image. 4 assets registered, 3 placed.
- **Visual regression across iterations.** `iter_1` is the better page; `iter_3`'s hero has the
  headline broken across three widely-spaced lines and two stray gradient blocks where the
  ribbon used to be.
- **Mobile hero clipping.** At 375px the checkout card overflows the left viewport edge
  ("heckout", "der summary", "udio bscription", "tal due") — text clipped off-canvas.
- **`search_assets` still cannot resolve images by query.** Five of six searches with
  `kind=image` returned **0 real asset result(s)** (`'abstract gradient ribbon Stripe'`,
  `'payment'`, `'globe'`, and two by asset id). The author only got its images because
  `use_library_asset` / `use_brand_asset` accept ids directly. Same class as the previous run's
  "director names ids the author's search cannot resolve".
- **Kit v8 would supply better assets** and remains **draft — deliberately not approved**
  (founder's call alone). Two of the assets used here (`f8ded0d6`, `f0453686`, both created
  13:20:08) are from the higher-quality harvest; the hero's `2b0928ca` is still the older
  23,935 B v6-lineage copy.
- `design_leg.exit_judge_failed` warning again on leg CLOSE — the pre-existing, already-recorded
  gateway-timeout issue, unrelated to imagery.

## Artifact for the founder

- Direct artifact route (verified rendering, logo loads 200):
  `http://localhost:3030/projects/prj_79aa603b3c3853898045e3cfa414e136/artifacts/doc_96b26c80faa055b2ba0ebdd6e55fd81d`
- In-chat: `http://localhost:3030/projects/prj_79aa603b3c3853898045e3cfa414e136/chats/thr_35ee14f41c645b9ba8ddc0f0e9d40123?surface=web`
- Agent previews: `.deepagent-workspace/run_03144653644947508f2585349c68d2c1/iter_{1,2,3}/preview_{375,768,1440}.png`

## Deliberately not done

- No product code changed, no brand kit approved, no existing document mutated, nothing pushed.
  Only this record is committed.
- The three known-open defects were recorded, not fixed — they are on the founder's list.
- Generation was not retried or re-prompted to force a flattering result.
