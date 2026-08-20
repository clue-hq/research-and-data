# 2026-08-20 — imagery defect register (founder-ordered: note, do not fix)

Founder instruction 2026-08-20: record every defect discovered while fixing web imagery,
**start no new work on them**, pause, then resume only the already-targeted items.
This file is the register. Nothing below is being worked on except where marked IN FLIGHT.

Evidence for everything here lives in `_memory/2026-08-20-*.md` (extraction quality, the
four-defect record, the live acceptance) plus the run traces named inline.

---

## A. Landed today (fixed, reviewed inline, tests green)

| # | defect | commit |
|---|---|---|
| A1 | Ingestion took only `img[src]` — no `srcset`/`<picture>`, no CSS `background-image`, no favicon fetch; image cap 12; 8000px scroll budget. **13 → 48 images, 296px family eliminated, 15 at ≥2048px.** | `a224b614` |
| A2 | `brand_notes: None` vs Rust `Vec<String>` — **web image generation had never once succeeded** | `dcd4d47a` |
| A3 | No text-to-image provider configured; `except Exception: pass` swallowed provider failures | `209f4514` |
| A4 | Icon vocabulary reached the author only *after* a rejection destroyed the page | `a5e6b832` |
| A5 | Web lane never had to decide about imagery; reviewer could not judge its absence | `deb718e5` |

## B. IN FLIGHT (dispatched before the pause instruction; the blocker for A1–A5)

**B1 — the agent's preview renders every image against a dead port.**
`web_substrate.py:~608` hardcodes `http://127.0.0.1:8000/asset-store`; `asset_base_url` is a
field on **no config object in the repo**, so the fallback always wins. The design API is on
**8010**. Proven: `:8010/asset-store/<logo digest>` → 200, 1922 B; `:8000/…` → connection
refused. Only the agent's *preview* loop is affected — the editor render route resolves
correctly, so the agent is blind to its own images working.
Consequence, from the acceptance run's own reviewer: *"BLOCKED. The page has a
broken-image-like Stripe wordmark in the header…"* → iteration 2 stripped every image.
Visual proof: `run_9e07aed2…/iter_1/preview_1440.png` — imagery present, broken.
Also in this dispatch: a loud preflight, the C6 ordering fix, and the C7 quality floor.

---

## C. OPEN — recorded, NOT started

### Page-write atomicity (the family the founder asked about)

**C1 — one bad diagnostic voids the ENTIRE authored page.** `crates/lumen-web/src/ingest.rs`
returns "page not stored" on any Error diagnostic. Observed twice, different causes each time,
same outcome — the logo was authored and then discarded:
- run `run_13a2a40b…`: `LUMW0114 unknown icon 'globe'` killed a header containing
  `<img data-asset=…>` for the real Stripe logo.
- run `run_9e07aed2…`: a batch of `LUMW0212` theme-token errors killed another.
The retries are smaller, safer rebuilds, so imagery never returns. **This is the all-or-nothing
mechanism that actually costs us imagery** — it is page authoring, NOT kit ingestion.
Candidate fix: downgrade to warn-and-drop-the-node, precedent `LUMW0124` (bad component prop)
in the same file. Changes the ingest contract → founder ruling + the AGENTS.md engine gate.

**C2 — `LUMW0212` contradicts its own hint.** Rejected `text-brand` / `border-brand` while the
diagnostic it printed lists `brand` as a valid token; the validator looks up the bare suffix.
Cost 2 whole-page rejections in one run.

**C3 — `LUMW0130`: an `<img>` inside a link/button is silently dropped.** "Logo wrapped in a
home link" is the most standard logo pattern on the web and is currently not expressible.
A second, independent way the logo fails to land.

### Brand-kit ingestion robustness (the founder's question — mostly already safe)

Ingestion is **already per-asset fail-soft**: a 4xx, a byte-cap overrun, or missing bytes skips
that one asset (`LUMI0502/0503`) and the kit still publishes. Empirically 149 downloads → 48
images published. Two real gaps remain:

**C4 — `asyncio.gather(*(_one(job) for job in jobs))` has no `return_exceptions=True`**
(`capture/evidence_builder.py:~265`). The *expected* failure path is isolated by
`raise_on_error=False`, but any **unexpected** exception in one asset aborts the whole asset
batch. This is the only place where one asset can genuinely harm the rest.

**C5 — a failed asset is silently dropped.** `_ingest_one` passes `raise_on_error=False` and
**discards the result** — no diagnostic, no count. So "this brand has no logo" and "the logo
failed to ingest" are indistinguishable after the fact.

### Style-reference selection

**C6 — lexicographic ordering picks a thumbnail as a style anchor.** `emit` already ranks kit
images best-first (`img.N` follows an area-descending sort), but `web_substrate.py:~3286` sorts
those keys as strings → `img.1, img.10, img.11 …`; `img.2` is unreachable at
`_BRAND_REFERENCE_MAX = 2`. On **approved kit v6**, `img.10` is **296×124**, so half the style
conditioning of every generated image is a thumbnail. v8 escapes this only because the harvest
no longer contains thumbnails — luck, not design. *(Included in the B1 dispatch.)*

**C7 — no quality floor on style anchors.** Three `continue` guards mean the picker takes the
first two *resolvable* images, which on a kit published elsewhere can land arbitrarily deep.
v8 still carries a 64×64 icon and a QR code. *(Included in the B1 dispatch.)*

### Cost and coverage

- **C8 — fetch cost is 3×** (50 → 149 downloads): most images spend all three ladder rungs and
  only the first is used. Fix is a staged collector; breaks the documented single-batch property.
- **C9 — describe cost ~4×**: ~53 vision calls per ingestion, but the brand card only ever shows
  the agent **16** images (`brand_card.py:43 MAX_IMAGE_LIST = 16`). ~33 descriptions per
  ingestion are paid for and never read. Fix: describe top-N by area.
- **C10 — `data-src` / `data-srcset` unread.** Lazy-loading libraries that never populate a real
  `src` still yield nothing. Cheap to add as ladder rungs.
- **C11 — inline `<svg>` never harvested.** Deliberately deferred; needs its own
  serialization/sanitization/dedup design.

### Ingestion data quality

- **C12 — the full-page screenshot is stored as a brand asset**, 6.5 MB, 1440×14871, labelled
  **`"in"`** because the capture is geo-redirected to `stripe.com/in` (Stripe's *India* page) and
  the filename is taken from the URL's last path segment. Junk in the library, and we are partly
  profiling the wrong page.
- **C13 — vision descriptions mislabel tiny crops** ("Overhead green gift box with tulips" for a
  296×128 enterprise panel). Should improve with A1's resolutions; unverified.
- **C14 — the brief agent may attach an unclamped full-page screenshot** to the vision request
  (`brief_agent.py:~214`), which would fail on any site taller than ~8000px. **Unverified** —
  our briefs did succeed, so this needs checking before it is believed.

### Infrastructure / dev hygiene

- **C15 — the fleet lease has no worker-version fence.** `clue_fleet/queue.py:~170` filters by
  job **kind** with no workspace or code-version predicate, so any stale design API on the same
  Postgres silently executes today's jobs with yesterday's modules. **Cost us three separate
  misdiagnoses today** (the `GeometryEvidence` ImportError, a confounded test bisect, a false
  regression attribution). The code documents it at `lumen_api/main.py:370-381` and says a real
  fence "belongs to the fleet". Highest-leverage infrastructure fix on this list.
- **C16 — 20 pre-existing suite failures**: `cd subsystems/clue-design/apps/custom-component-compiler && npm ci`
  (NOT the design subsystem root — it has no `package.json`).
- **C17 — `LUMEN_CORE_HELPER` unset** makes the agent_runtime suite rebuild the Rust helper
  mid-run and fail a random test. Pin it.

### Carried from earlier (founder queue, unchanged)

- **C18 — the design-leg exit judge can never build** (profile timeout 120s > gateway 30s), so
  "lock it in" cannot close a design session. Fix (a) clamp in the builder, or (b) mint design
  profile v2.
- **C19 — `missing_finalize` on Terra**: the delegation teaching ends "end your turn", which
  Terra takes literally and skips `finalize_turn`.
- **C20 — the proposal-card false positive**: Head-of-ABM declares its open interaction as
  `open_gate_refs = [{object_type: "design_leg"}]`, and the turn-close path renders *every*
  open-gate ref as a human-approval card. The frontend fail-closes → "This review request is
  incomplete". Clicking "Create a new proposal" then sends a canned message that routes to
  Design. Zero `agent_gate` rows exist for such threads — verified.
- **C21 — editor write bugs**: Canvas ▸ Background colour writes nothing; Layout ▸ Padding
  reverts on blur.
- **C22 — `make check` at 59 reds**, wants a triage owner.

---

## Founder decisions pending

Approve **kit v8** (measured: the agent already asks for v8 asset ids by name and is handed
smaller v6 files instead — `ConnectBentoBackground` 144 KB → 306 KB). Rule on **C1** (the
page-write contract). Plus the standing queue: W5 acceptance sign-off, slice-3 wording, the
sidebar-spinner ruling, the artifact-identity URL param, the director edit-tool grant.
