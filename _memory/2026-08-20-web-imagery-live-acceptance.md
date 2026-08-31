# 2026-08-20 — live acceptance walk for the web-imagery wave (D1–D4) + the image-quality wave

Branch `integration/frontend-design-part-iv-v2`, HEAD `6f4e5cc5`. Verification only —
**no product code changed.** Commits under test: `a224b614` (ingestion rendition quality),
`dcd4d47a` (D1 null `brand_notes`), `209f4514` (D2 real T2I provider), `a5e6b832` (D3 icon
vocabulary), `deb718e5` (D4 forced imagery decision).

This is the acceptance step the D1–D4 record deferred ("the first real generation on a
relaunched fleet worker is the remaining acceptance step").

## Verdict

**The page still contains ZERO image nodes — same headline number as the 0-baseline.**
But the failure has moved a long way downstream and its cause is now known and small.
The four fixes did what they claimed; a **fifth defect (D5), untouched by this wave,
destroys the result at the last step.**

## Setup

- Preflight: exactly one `801x` listener (8010). No stale poacher. `design_agent_run`
  had 0 rows `status='running'`.
- Restarted **on HEAD**: design API 8010 (was 19:12, predating `deb718e5` 19:17) and the
  **istanbul** fleet worker (was 15:39, predating everything). Missoula's fleet worker
  (pid 73637) and ports 8030/3030 left alone.
- Fleet worker registered the design lane (`design_fleet.handler_registered kind=design_job`).
- `image_provider.is_configured()` → **True**; both processes carry
  `IMAGE_MODEL_ID=google/gemini-3.1-flash-image`.
- Brand kit **v6 (approved)** used. **v8 remains draft — not approved.**

## The run

Real product flow: browser → project `prj_79aa603b3c3853898045e3cfa414e136` → new chat →
leg opened (`?surface=web`) → second message started generation.

- Document `doc_f95ba42293fb59b0b1d04391497fa1d0`, work `72976ce5-…`, run
  `run_9e07aed2892b4d24aec14e4fab80326e`, executed by the **fleet worker**.
- **Wall clock 5m 40s** (13:56:35 → 14:02:15 UTC), status `succeeded`.
- **Rounds:** 32 author LLM calls, 16 orchestrator, **2 reviewer** (2 preview iterations).

## Hard numbers

Final `current_scene_json` (161 nodes, `assets` registry excluded):

| kind | n |
|---|---|
| container | 72 |
| text | 56 |
| button | 14 |
| icon | 10 |
| section | 7 |
| component | 2 |
| **image** | **0** |

Baseline for comparison, re-measured with the same query: `doc_f85ad1bf` / `doc_2543706b`
/ `doc_316aafa4` → 0 image nodes, 9 / 14 / 8 icons. Reproduced exactly.

Corroborating, not just node-kind counting:
- No node carries `src`, an `img` tag, a `background-image`, or **any** asset id. The full
  set of node property keys is `anchor_id aria_label children classes command
  command_target component content href icon id kind label new_tab tag variant`.
- The design API's own render of the final doc returns **0 `<img>` tags** in 35 KB of HTML.
- `custom_css` is 85 bytes (a focus-ring rule) — no imagery hidden there.

**The real logo is NOT placed.** `asset_ing_61a219a05909b652` (`logo.svg`) sits in the
document's asset registry along with two brand images, **referenced by zero nodes** — the
exact orphan-registry shape of the baseline. The header wordmark that *looks* like Stripe's
mark in the screenshot is `txt_2`, a **text node** styled bold/violet. The hero "gradient
ribbons" and the dark-band "rings" are **CSS** (`bg-linear-to-r … blur-2xl`,
`rounded-[50%] border-[18px]`), not images.

**No image was generated.** `generate_image` was called **zero** times; no `design_asset`
row was created during the run, so there is no `source.kind == "generated"` record and no
model id to report. Cost for the run: no image spend.

## What the fixes DID prove (all four held)

- **D1 —** `invalid type: null, expected a sequence` appears **nowhere**: not in the fleet
  log, the 8010 log, `trace.jsonl`, or `run.jsonl`. 0 occurrences.
- **D2 —** provider configured and live in the executing process (no `LUMA0710`/`LUMA0711`
  warnings were emitted, consistent with the author never invoking generation).
- **D3 —** the batch rejections carried **no `LUMW0114`** icon error. The icon vocabulary
  reaching the author before it writes worked; the class of failure that discarded Stripe's
  logo last time did not recur.
- **D4 — the strongest positive result.** The director produced an explicit, per-band
  imagery decision and it rode into the reviewer brief verbatim:

  > - Header: place the real Stripe wordmark asset_id asset_ing_61a219a05909b652.
  > - Hero: place library asset_id asset_ing_6381113f6161eafa … as a large abstract ribbon/wave motif …
  > - Benefits/features: deliberately none; … per product-led imagery posture.
  > - How it works: deliberately none; …
  > - Final CTA: place library asset_id asset_ing_827ec385bf79beea …
  > - Footer: deliberately none; text-only navigation.

  The author then actually executed it — `use_brand_asset` was called on **the real logo**
  and two brand images, and iteration 1 contained genuine `<img>` nodes for them.

## D5 — why it still ends at zero

The images the author placed **render broken**, so the (new, working) D4 reviewer gate
blocks the page, and the author strips imagery to get unblocked.

Evidence chain, in order:

1. `iter_1/preview_1440.png` visibly shows broken-image placeholders with alt text
   ("Stripe" in the header, "Pink and purple gradient wave ribbons" in the hero).
2. The reviewer returned: **"BLOCKED. The page has a broken-image-like Stripe wordmark in
   the header and a broken-image-like hero asset/alt text at all widths…"**
3. Iteration 2 removed every image. The agent says so itself in the chat summary: *"The
   supplied image/logo assets did not render in the constrained preview, so failed image
   fallbacks were replaced with intentional Stripe-like text and primitive motifs."*

**Root cause — a port drift, one line:**
`apps/agent_runtime/lumen_agent/tools/web_substrate.py:608-610`

```python
self.asset_base_url = (
    getattr(config, "asset_base_url", None)
    or "http://127.0.0.1:8000/asset-store"
)
```

`asset_base_url` is defined on **no config object anywhere in the repo** (grep: only this
site, the Rust render options, and the API), so the hardcoded fallback always wins. The
design API listens on **8010**, not 8000.

- `crates/lumen-web/src/render.rs:1131 asset_src()` builds `{asset_base_url}/{digest}`.
- `curl http://127.0.0.1:8010/asset-store/61a219a0…` → **200 image/svg+xml 1922 bytes**.
- `curl http://127.0.0.1:8000/asset-store/61a219a0…` → **connection refused**; nothing has
  ever listened on 8000 in this stack.

So every `data-asset` image in **the pixels the reviewer judges** points at a dead port.
The API's own editor render is correct (`request.base_url + "/asset-store"`), which is why
the artifact opens fine in the product — only the agent's preview loop is broken. Fixing
the base URL is the whole remaining distance to imagery on the page.

## Secondary finding — the author cannot resolve the new high-quality renditions

The director named `asset_ing_6381113f6161eafa` (hero) and `asset_ing_827ec385bf79beea`
(final CTA). Both **exist**, but `search_assets` returned **0 results** for each, so the
author substituted older assets. Those two ids are the **13:20:08 high-quality renditions
harvested by `a224b614`**, which belong to the **draft kit v8**; resolution is scoped to the
**approved v6**, whose copies are the older, smaller files:

| file | v6-lineage (used) | v8 draft (wanted, unresolvable) |
|---|---|---|
| ConnectBentoBackground.jpg | 144,596 B | **305,900 B** |
| volume-fallback_2x.png | 28,002 B | **211,866 B** |
| developer-wave-wide_2x.png | *absent* | **268,762 B** |

This is direct, measured confirmation that `a224b614` captures materially better renditions
(2.1× and 7.6× the bytes, plus a wide asset the old ingestion never captured at all) — and
that **approving v8 would improve what the page and the style-reference conditioning get.**
v8 is left **draft**; approval is the founder's call alone.

Worth a follow-up in its own right: the director surfaced asset ids the author's
approved-kit-scoped search cannot resolve. Silent substitution is the current behaviour.

## Other things observed (not caused by this wave)

- **One whole-page rejection**, 20 error diagnostics — 16× `LUMW0212`, 2× `LUMW0126`
  (command button without `data-target`), 2× `LUMW0117` (loose text) — plus warning
  `LUMW0130` *"dropped disallowed inline tag `<img>`"* in `btn_2`: the header logo was
  written **inside a button/anchor**, where `<img>` is not an allowed inline tag, and was
  silently dropped. A second, independent way the logo fails to land.
- **One subtree rejection** (hero), 11 errors, same `LUMW0212` family.
- `LUMW0212` is worth a look: the author was rejected for `text-brand`, `border-brand`,
  `text-brand/15` — while the diagnostic's own hint lists `text-brand` and `border-brand`
  as valid theme tokens. The validator strips the utility prefix and looks up the bare
  suffix (`brand`), which is not a token. The hint therefore advertises exactly the strings
  that get rejected. This cost 2 of the run's rejections.
- The standalone route `/projects/{pid}/artifacts/{docId}` returned **"Preview failed —
  Website render failed (HTTP 500)"** once immediately after the run, then rendered
  correctly on retry. Transient; not reproduced a second time.
- Two pre-existing test flakes recorded in the D1–D4 memo were not re-examined here.

## Artifact for the founder

- In-chat (verified rendering): `http://localhost:3030/projects/prj_79aa603b3c3853898045e3cfa414e136/chats/thr_5869e3ca8453594ea5ac5943fbb696e1?surface=web`
- Direct artifact route: `http://localhost:3030/projects/prj_79aa603b3c3853898045e3cfa414e136/artifacts/doc_f95ba42293fb59b0b1d04391497fa1d0`
- Agent previews: `.deepagent-workspace/run_9e07aed2892b4d24aec14e4fab80326e/iter_{1,2}/preview_1440.png`
  — iter_1 is the one that still had the images, shown broken.

## Deliberately not done

- No product code changed, no brand kit approved, no document deleted or mutated, nothing
  pushed. Only this record is committed.
- D5 not fixed — it is a one-line composition change and the founder asked to be told first.
