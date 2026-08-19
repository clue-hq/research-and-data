# 2026-08-19 — genweb slice 2: document birth at leg-open + the versioning wave (B2, B4, F5)

Branch `integration/frontend-design-part-iv-v2`, worked directly. Plan:
`docs/superpowers/plans/2026-08-19-chat-driven-website-generation.md` (§4.1 + its brand-theming
amendment, the Slice 2 section, F5). Brief:
`.superpowers/sdd/2026-08-19-chat-driven-website-generation/slice2-brief.md`. Report:
`…/slice2-report.md`.

Commits (local only, never pushed):

- `a186445b` — `feat(genweb): open_design_leg@2 births the web document (B2)`
- `ef4884d0` — `feat(genweb): head-of-abm v37 — the design delegation teaching (B4)`

## The governed-create seam — VERIFIED, and the plan's assumption was half right

The plan named `design_tools.py → lumen_api.toolbelt design_create_document` and said "verify,
don't assume". What is actually there:

- `design_create_document@1` **exists** (`lumen_api/toolbelt/documents.py:300`) and its `run()`
  does reach `clue_design.documents.create_document` — but only through
  `host.repository(ws)` → `lumen_api.design_store.DesignStoreBridge._run`, which opens **its own
  engine, connection and transaction on another thread** (`design_store.py:216-246`). Calling it
  from the leg tool would (a) commit the document in a different transaction from the leg insert
  — a failed delegation would orphan a document and its retry would then hit
  `design_document_exists`; (b) block the event loop; (c) require a full `DesignToolHost`
  (storage + node bins + component compiler) the leg tool has no business owning.
- **The governed tool does NOT do the engine round-trip.** Every caller mints the scene itself:
  the design API's own `POST /documents` calls `core.web_new_doc(...)` and then hands the result
  to the tool (`lumen_api/main.py:2004-2053`), and `design_derive_web_document` /
  `design_create_web_template` are the same shape. So routing through the tool saves no work on
  the half that actually needs the engine.

**Route taken (the brief's sanctioned fallback):** the leg tool calls the DAL's
`create_document` directly, inside its OWN transaction — which is exactly where the binding
requirement lives (the frozen creation contract that stamps the latest approved brand kit). The
engine half rides a new, narrow public seam `clue_api.design_tools.mint_empty_web_document`,
which reuses the platform's existing `_core_client()` (the same `design_tools.py` composition
seam trap 2 names), hopped onto a thread with `asyncio.to_thread` because
`CoreClient._run` is a blocking `subprocess.run`.

## What changed

- **`open_design_leg` → `@2`** (`platform/api/clue_api/design_leg_tools.py`). New inputs
  `doc_kind: "web"|"scene"|None` and `title: str|None`; new output `document_created: bool`.
  On a document-less, non-reopen open:
  - `doc_kind is None` → `design_leg_doc_kind_required`;
  - `doc_kind == "scene"` → `design_leg_scene_creation_unsupported` (§8 item 8);
  - otherwise `document_id = derive_leg_document_id(leg_id)` = `doc_<uuid5(leg_id).hex>` and
    `document_version_guard = 0`.
  The birth runs in `invoke` (never in `preconditions` — that path must not write): engine mint
  → DAL `create_document(doc_kind="web")` → read the stamp back → `open_leg(...)`, all one
  transaction.
- **Brand pin = read-back, never re-derived.** `design_leg.brand_kit_id/version` come from the
  STORED row's `effective_brand_kit_id/_version`, which `create_document` fills from
  `scene.theme.brand_kit`. Both-or-neither, else no pin. When the agent supplies an explicit
  pin on a create, it is handed to `web_new_doc` as the doc's own `theme.brand_kit` (which the
  creation contract treats as authoritative) — so even then the leg pin is a read-back of
  durable truth, not a parallel decision.
- **The frozen bundle records what was BORN.** `_bundle_payload` now takes the resolved
  `document_id`, and on the birth path `invoke` re-freezes the bundle with the read-back brand
  ref before persisting (the kit is not knowable at `_resolve` time) and re-checks the byte cap.
  Byte-stable for every non-birth path.
- **`mint_empty_web_document`** added to `platform/api/clue_api/design_tools.py`. Injectable at
  the tool (`web_document_minter=`) so DB tests need no Rust binary.
- **The versioning wave** (registry was the truth; the plan's numbers happened to match):
  prompt `head-of-abm@v5` (v4 + one short design-delegation paragraph), profile
  `head-of-abm@v37` (prompt v5 + `open_design_leg@2` digests), `recipe0-stage0@17` (@16 with the
  address re-pinned at all four sites), `CONVERSATION_RECIPE_VERSION = 17`,
  `C6_ACTIVE_PROFILE_VERSIONS[HEAD_OF_ABM] = "v37"`,
  `PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v37"`,
  `RECIPE_0_TOOL_ADDRESSES` → `open_design_leg@2`. No frozen version was edited.

## Facts worth keeping

- **The engine's empty WebDoc** (`lumen_web::WebDoc::new`, recorded from
  `target/release/lumen-api-helper`): `{assets:{}, custom_css:"", id, pages:[{id:"home",
  name:"Home", nodes:{root:{classes:"", id:"root", kind:"container", new_tab:false}},
  root:"root", route:"/"}], schema_version:1, theme:{}, title}`. `theme` is `{}` unless a
  `brand_kit_ref` is passed. `tests/api/test_genweb_leg_document_birth_db.py::engine_web_doc`
  reproduces it and is imported by the P3.7 stream tests too.
- **`design_leg.document_id` has no FK to `design_document`** (documented at
  `project_design_documents`), so ordering inside the birth transaction is a choice, not a
  constraint. It is created first anyway.
- **`create_document` derives the web document's id and title from the SCENE**
  (`scene["id"]`/`scene["title"]`), not from parameters — so the engine mint is what names the
  row, and the caller-derived id must be handed to `web_new_doc`.
- **The design API's `new_id("doc")` shape is `doc_<uuid4 hex>`**; the leg's derived id keeps
  that shape so nothing downstream can tell a leg-born document from a route-born one.
- **`recipe` / `recipe_revision` columns:** `recipe.recipe_key` (not `key`), and
  `recipe_revision` has no `status` column. The **fleet worker** (`fleet_main.py:805`) is what
  seeds system recipes — restarting it is what installed `recipe0-stage0@17`.
- The P3.4 test `..._accepts_a_leg_with_no_pins` was re-purposed to
  `..._with_no_document_must_say_what_to_create`: the pin-free success shape WAS blocker B2, so
  it is gone by design, and the birth path has its own module.

## Live verification (dev data, left in place)

Stack: platform API 8030 + design API 8010 already up (untouched); the istanbul fleet worker was
restarted onto this slice's code (`/tmp/slice15_fleet_worker.sh`, log `/tmp/slice2_fleet_worker.log`).
Scripts: `/tmp/slice2_live_ask_for_a_page.py` (durable submission), `/tmp/slice2_gallery_read.py`
(projections-route feed read), `/tmp/q.py` (ad-hoc SQL).

Thread `thr_genweb_slice2_ask`, workspace `ws_804029…`, project `prj_79aa60…`.

1. **The agent called the tool unprompted.** One chat message ("I want a landing page for our
   Insight Health launch…") on a fresh thread → head-of-abm turn `b3e7ee26…` →
   `toolbelt.open_design_leg_started/completed`, one `web_new_doc` helper call, turn ended
   `awaiting_input` with the assistant message: *"The design session is open for the **Insight
   Health launch landing page**. Your next message will go directly to Design to begin
   generation; it may take a few minutes."* — the v5 teaching, verbatim in behaviour.
2. **The document was born**: `doc_a37154cd822352b898ef6ac96fd733f2`, `doc_kind='web'`,
   `status='draft'`, `current_version=0`, title *"Insight Health launch landing page"* (the
   agent supplied it), workspace-scoped; leg `529b34a1-1bd9-5da5-a516-10a710ebc310` state
   `open_awaiting_user`, `document_version_guard=0`. No approved kit in this dev workspace →
   `theme = {}` and NO leg pin, the slice-0 fallback shape exactly.
3. **The card appears in the gallery feed** through the real projections route
   (`GET /api/v1/projects/{id}/design-artifacts` → HTTP 200), first in the list, exact wire
   shape. NOT proven through the browser BFF: the headless Playwright context has no Clerk
   session and the shell-lift credentials are not recorded in `_memory/`. The BFF is a
   pass-through proxy over this exact route (and W1.3 already verified it live in a browser), so
   the gap is the cookie, not the code.
4. **The follow-up message routed to Design**: turn `8cda8b52…` was created with `role='design'`
   and dispatched a web turn on the born document.

## Open items / concerns

- `LUMEN_CORE_HELPER` is now a **production requirement for the platform process that runs
  head-of-abm turns** (the fleet worker), not only for the design API: without it `CoreClient`
  falls back to `cargo run` from `subsystems/clue-design`, which in a deployed image would fail
  or be absurdly slow. The recorded fleet-worker launch recipe already sets it; a deployment
  checklist should state it.
- `doc_kind` is **ignored** when `document_id` is present (the durable row's kind is the truth).
  The founder's refusal matrix listed four refusals and this is not one of them, so a mismatched
  `doc_kind` is silently ignored rather than refused — deliberate, recorded, cheap to add later.
- Known pre-existing reds confirmed still red and NOT caused by this slice:
  `tests/api/test_p36_leg_resilience_db.py::test_a_gate_answer_queued_behind_a_leg_opening_still_reaches_head_of_abm`
  (`insert_gate_answer` TypeError — the brief's named red) and
  `tests/api/test_toolbelt_wiring.py::test_out_of_order_matrix`
  (`DraftAccountResearchDirectiveInputV3` validation — verified red on a stashed tree too).
