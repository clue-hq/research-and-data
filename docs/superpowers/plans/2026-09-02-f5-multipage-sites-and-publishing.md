# F5 — Multi-Page Sites + Real Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A web document becomes ONE SITE with N pages; the agent and the user can add pages and edit each page's route; Publish in the platform shell puts the whole site live at `{workspace-handle}.pages.cluehq.ai/{site-slug}{page-route}` (interim `/w/{ws}/p/{slug}{route}` until the host is wired), every page at its own route.

**Architecture:** The engine (`crates/lumen-web`) is already N-page-shaped (`WebDoc.pages: Vec<WebPage>`, per-page validate/derive/render, a `SetPageMeta` op nothing calls) — F5 adds `AddPage`/`RemovePage` + a route grammar, then makes every "home"-assuming aperture page-aware: the render/preview/review endpoints, the agent substrate's active page, the publish package (one HTML per page, persisted per `(workspace, slug, route)`, served by route), and the platform shell (real publish wiring over the existing design-API routes, a page switcher, a route editor). A design-owned workspace handle + a Host-matched public sub-app give the default domain; a resolver table is the seam custom domains will land in.

**Tech Stack:** Rust (lumen-web ops/validate; `cargo test --workspace`), Python 3 / FastAPI (design API `apps/api/lumen_api`, DAL `subsystems/design/clue_design`, Alembic at repo root), Python agent runtime (`apps/agent_runtime/lumen_agent`, deepagents), TypeScript/Next.js (`apps/frontend`, node `tsx --test` tests), Playwright (previews). Postgres only.

**Spec:** `docs/superpowers/plans/2026-08-27-clone-fidelity-master-plan.md` — Phase F5 section (rulings R-F5-1..8) and the scout facts in `_memory/2026-09-02-f5-multipage-scope-reratified.md`. Read both first.

## Global Constraints

- **Founder rulings are law (R-F5-1..8).** URL = `{handle}.pages.cluehq.ai/{site-slug}{route}`; publish unit = the SITE; dialog slug = site slug, home route stays `/`; indexing law unchanged (ABM `noindex` durable, R-F1); handle auto-derived, editable until first publish, immutable after (R-F5-5 default — confirm with founder at dispatch); CP3 target = per-account ABM microsite (R-F5-6); pages from the homepage section library + composed sections, NO multi-page capture (R-F5-7); links structurally FREE, guidance only, the F4 escape-route gates demote to advisory (R-F5-8). **No new mechanical gates anywhere.**
- **Local commits only. Never push. No AI attribution in commit messages** (no `Co-Authored-By`, no "Generated with").
- **Env-parity rule:** every new env key lands in root `.env.example` (its section), in `subsystems/clue-design/.env.example` (subsystem-owned keys), and in the local `.env`, WITH its default, in the same commit that introduces it.
- **Alembic:** `alembic revision -m "<slug>"` (hash ids), `down_revision` = current head (`6eff96862040` at plan time — re-check with `uv run alembic heads`), hand-written reversible `downgrade()`, exactly one head. Design tables live in the ROOT alembic tree (precedent `be0659753362_design_document_thumbnail_cache_index.py`).
- **Engine changes ritual (design `AGENTS.md` §1/§3), in order:** `cargo test --workspace` → `cargo build -p lumen-api-helper --release` → `bash scripts/build_wasm_core.sh` → `node scripts/verify_handshake.mjs` (must print `HANDSHAKE OK`) → restart any process holding `LUMEN_CORE_HELPER`. Run from `subsystems/clue-design/`.
- **Design Python tests:** from `subsystems/clue-design/`: `PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/pytest <one file> -q`. ONE FILE PER PROCESS for `apps/agent_runtime/tests` (the multi-file pytest run wedges on the engine helper — known, unowned). Design tests run WITHOUT the platform `.env`.
- **Platform DB-gated tests:** `postgresql+asyncpg://clue:clue@localhost:55040/clue` (never 5432); `tests/design/` is the DAL test home (`conftest.py` there).
- **Frontend gate:** from `apps/frontend/`: `npm run design-system:build && npm run lint && npm run build`; unit tests `npm test` (node `tsx --test` over `src/**/*.test.ts`).
- **Presentation-truth rule:** the dummy frontend is the only source of designed UI. The page switcher (Task 18) and the page/route section (Task 19) have NO designed slot today — ship the minimal neutral control the plan specifies, mark it "FLAGGED: founder/design slot pending" in code comment and close-out, add no other chrome.
- **Never `git stash`** (shared stash stack across worktrees).
- Keep `HOME_PAGE_ID` constants only where a FALLBACK is genuinely needed (first page); every consumer that can know the page must be told the page.

---

## File structure (whole-plan map)

```
subsystems/clue-design/crates/lumen-web/src/validate.rs        MODIFY T1  route grammar (LUMW0036)
subsystems/clue-design/crates/lumen-web/src/ops.rs             MODIFY T2  AddPage/RemovePage (+ inverses, tests)
subsystems/clue-design/apps/api/tests/test_web_documents.py     MODIFY T3  add-page via /web/operations round-trip
subsystems/clue-design/apps/api/lumen_api/main.py               MODIFY T4  render ?page_id; T7 turn literals; T11 serving; T12/T15 public address; T14 handle routes
subsystems/clue-design/apps/api/lumen_api/web_bridge.py         MODIFY T4  page-aware bridge; T20 lumen:navigate
subsystems/clue-design/apps/api/lumen_api/fragments/render.py   MODIFY T7  web_doc_all_fragment_ids
apps/frontend/src/features/design-editor/engine/webDocuments.ts MODIFY T5 (pageId on render), T13 (noindex), T17 (page op builders)
apps/frontend/src/features/design-editor/hooks/use-web-render.ts MODIFY T5
apps/frontend/src/features/design-editor/components/web-artifact-canvas.tsx MODIFY T5, T20
subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py MODIFY T6 (page tools, active page), T9 (advisory)
subsystems/clue-design/apps/agent_runtime/tests/test_web_pages.py CREATE T6
subsystems/clue-design/apps/agent_runtime/lumen_agent/harness_web.py MODIFY T8
subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts_web.py MODIFY T8
subsystems/clue-design/apps/agent_runtime/knowledge_docs/skills/{create-website,edit-website,campaign-page-workflow,conversion-copywriting}/SKILL.md MODIFY T8
subsystems/clue-design/apps/api/lumen_api/fragments/campaign_shell.py MODIFY T9 advisory shape notes
subsystems/clue-design/apps/api/lumen_api/agent_cloned_sections.py MODIFY T9
alembic/versions/<hash>_design_web_publish_pages.py             CREATE T10
subsystems/design/clue_design/publishes.py                      MODIFY T10 page DAL
subsystems/clue-design/apps/api/lumen_api/design_store.py       MODIFY T10 facade
tests/design/test_web_publish_pages_dal_db.py                   CREATE T10
subsystems/clue-design/apps/api/lumen_api/web_export.py         MODIFY T11 per-page package + export bundle
subsystems/clue-design/apps/api/lumen_api/toolbelt/publishes.py MODIFY T11 persist pages
subsystems/clue-design/apps/api/lumen_api/public_address.py     CREATE T12 (PublicSiteAddress + config)
alembic/versions/<hash>_design_workspace_handle.py              CREATE T14
subsystems/design/clue_design/workspace_handles.py              CREATE T14
subsystems/clue-design/apps/api/lumen_api/public_pages.py       CREATE T15 Host sub-app
apps/frontend/src/features/design-editor/data/web-publish.repository.ts CREATE T13
apps/frontend/src/features/chat-shell/hooks/use-artifact-sharing-controller.ts MODIFY T13
apps/frontend/src/features/chat-shell/components/artifact-header.tsx MODIFY T13, T18
apps/frontend/src/features/chat-shell/components/artifact-stage.tsx MODIFY T13, T18, T20
apps/frontend/src/features/chat-shell/components/web-inspector.tsx MODIFY T19
apps/frontend/src/features/design-editor/hooks/use-inspector-writes.ts MODIFY T19
subsystems/clue-design/apps/editor/src/components/web/{WebEditorApp,WebInspectorPanel}.tsx MODIFY T21 (dev-shell parity)
.env.example, subsystems/clue-design/.env.example, .env         MODIFY T12, T15
docs + _memory                                                  T22
```

Lane order: **F5.0 (T1–T3) → F5.1 (T4–T5) → F5.4 agent (T6–T9) → F5.2 publish (T10–T12) → F5.3 shell + domain (T13–T16) → F5.5 editor (T17–T21) → close (T22).** T9, T10 and T17 have no dependency on their predecessors and may run in parallel worktrees.

---

## Lane F5.0 — Engine page ops

### Task 1: Route grammar in the validator (LUMW0036)

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-web/src/validate.rs:32-58` (page loop) + a new fn `route_is_valid`
- Test: same file, `mod tests`

**Interfaces:**
- Produces: `pub fn route_is_valid(route: &str) -> bool` (exported from `lumen_web::validate`, re-exported in `lib.rs` next to `validate_web_doc`) — Task 2 (AddPage/SetPageMeta refusal), Task 6 (agent tool pre-check), Task 19 (client-side mirror) all follow this exact grammar.
- Grammar: exactly `/`, or one-or-more segments `/[a-z0-9]+(-[a-z0-9]+)*`; no trailing slash; whole route ≤ 128 chars; reserved: any segment equal to `manifest.json`, and a FIRST segment of `p-assets` or `asset-store` (they collide with the publish surface).

- [ ] **Step 1: Write the failing tests** (append to `mod tests` in `validate.rs`; the module already has `WebDoc::new` + `ingest_html_into_page` helpers in scope):

```rust
#[test]
fn route_grammar_accepts_root_and_kebab_paths() {
    assert!(route_is_valid("/"));
    assert!(route_is_valid("/pricing"));
    assert!(route_is_valid("/pricing/enterprise-2026"));
}

#[test]
fn route_grammar_refuses_bad_shapes() {
    for bad in ["", "pricing", "/Pricing", "/pricing/", "//a", "/a b", "/a_b", "/manifest.json",
                "/p-assets/x", "/asset-store/x", "/x/manifest.json"] {
        assert!(!route_is_valid(bad), "{bad:?} should be refused");
    }
    assert!(!route_is_valid(&format!("/{}", "a".repeat(128))));
}

#[test]
fn a_page_with_an_invalid_route_is_an_error_diagnostic() {
    let mut doc = WebDoc::new("d", "Site", None);
    doc.pages[0].route = "/Bad Route".to_owned();
    let diagnostics = validate_web_doc(&doc);
    assert!(diagnostics.iter().any(|d| d.code == "LUMW0036"), "{diagnostics:#?}");
}
```

- [ ] **Step 2: Run to verify failure**

Run (from `subsystems/clue-design/`): `cargo test -p lumen-web route_grammar a_page_with_an_invalid_route`
Expected: compile error `cannot find function route_is_valid`.

- [ ] **Step 3: Implement**

Add above `validate_web_doc`:

```rust
/// The publish-surface route grammar (F5, Task 1). `/` or `/seg(/seg)*` where a segment is
/// `[a-z0-9]+(-[a-z0-9]+)*`; no trailing slash; ≤128 chars; `manifest.json` is never a
/// segment and `p-assets` / `asset-store` are never the first one (both are served beside
/// a published site and would shadow it).
pub fn route_is_valid(route: &str) -> bool {
    if route == "/" {
        return true;
    }
    if route.len() > 128 || !route.starts_with('/') || route.ends_with('/') {
        return false;
    }
    let mut segments = route[1..].split('/');
    let Some(first) = segments.next() else { return false };
    if first == "p-assets" || first == "asset-store" {
        return false;
    }
    std::iter::once(first).chain(segments).all(segment_is_valid)
}

fn segment_is_valid(segment: &str) -> bool {
    if segment.is_empty() || segment == "manifest.json" {
        return false;
    }
    segment
        .split('-')
        .all(|run| !run.is_empty() && run.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit()))
}
```

Inside the `for page in &doc.pages` loop (after the duplicate-route check at line ~52):

```rust
        if !route_is_valid(&page.route) {
            diagnostics.push(
                Diagnostic::error(
                    Phase::Web,
                    "LUMW0036",
                    format!("page `{}` route `{}` is not a valid site route", page.id, page.route),
                    Some(DiagnosticSubject::Page(page.id.clone())),
                )
                .with_hint("Routes are `/` or `/lowercase-segments/like-this`; no trailing slash, ≤128 chars."),
            );
        }
```

Re-export in `crates/lumen-web/src/lib.rs` beside `validate_web_doc` (`pub use validate::{route_is_valid, validate_web_doc, ...}` — match the existing `pub use` line).

- [ ] **Step 4: Run tests** — `cargo test -p lumen-web` → all green (existing fixtures use route `/`).
- [ ] **Step 5: Commit** — `git commit -m "feat(lumen-web): route grammar LUMW0036 — the publish-surface shape every page route must have"`

---

### Task 2: `AddPage` / `RemovePage` operations (invertible, checked)

**Files:**
- Modify: `subsystems/clue-design/crates/lumen-web/src/ops.rs` — enum at `:52-129`, dispatch `apply_operation_in_place` at `:339`, `require_page_mut` at `:788`, tests `mod tests` at `:797`
- Test: same file

**Interfaces:**
- Produces two ops (serde `kind` tag, snake_case):
  - `add_page { page: WebPage, index: Option<usize> }` — inserts a full page (an "empty" page is a page whose `nodes` holds only its root Container and whose `root` names it). Refuses: duplicate page id (`op.page_exists`), duplicate route (`op.route_exists`), invalid route (`op.route_invalid`, via Task 1's `route_is_valid`), a page whose `root` is not in `nodes` (`op.page_root_missing`), index > len (`op.index_out_of_range`). Inverse: `remove_page { page_id }`.
  - `remove_page { page_id: PageId }` — refuses removing the last page (`op.cannot_remove_last_page`, validation would fail with LUMW0002 anyway; refusing first gives a named reason). Inverse: `add_page { page: <the removed page verbatim>, index: Some(<its former index>) }`.
- `SetPageMeta` additionally refuses an invalid or duplicate route (`op.route_invalid` / `op.route_exists`) — today it accepts anything and only the checked apply catches duplicates.
- Consumers: the helper's `WebApplyOps` (generic serde — NO helper change), Task 3 (API round-trip), Task 6 (agent tools), Task 17 (TS builders).

- [ ] **Step 1: Write the failing tests** (append inside `mod tests`; `fixture()` builds a one-page doc ingested from HTML, `page_id()` = `home`):

```rust
    fn empty_page(id: &str, route: &str) -> crate::doc::WebPage {
        let root_id = NodeId::from(format!("root_{id}"));
        let root = WebNode::branch(
            root_id.clone(),
            WebNodeKind::Container { href: None, new_tab: false, background: None },
            "",
        );
        let mut nodes = BTreeMap::new();
        nodes.insert(root_id.clone(), root);
        crate::doc::WebPage {
            id: PageId::from(id),
            name: id.to_owned(),
            route: route.to_owned(),
            root: root_id,
            nodes,
        }
    }

    #[test]
    fn add_page_then_inverse_restores_the_document() {
        let mut doc = fixture();
        let before = doc.clone();
        let inverses = apply_operations_checked(
            &mut doc,
            &[WebOperation::AddPage { page: empty_page("pricing", "/pricing"), index: None }],
        )
        .expect("add page")
        .0;
        assert_eq!(doc.pages.len(), 2);
        assert_eq!(doc.pages[1].route, "/pricing");
        assert!(matches!(inverses[0], WebOperation::RemovePage { .. }));
        apply_operations(&mut doc, &inverses).expect("inverse applies");
        assert_eq!(doc, before);
    }

    #[test]
    fn remove_page_inverse_reinserts_at_the_same_index() {
        let mut doc = fixture();
        apply_operations(
            &mut doc,
            &[WebOperation::AddPage { page: empty_page("a", "/a"), index: Some(0) }],
        )
        .unwrap();
        let before = doc.clone();
        let inverses = apply_operations(
            &mut doc,
            &[WebOperation::RemovePage { page_id: PageId::from("a") }],
        )
        .unwrap();
        assert_eq!(doc.pages.len(), 1);
        apply_operations(&mut doc, &inverses).unwrap();
        assert_eq!(doc, before);
        assert_eq!(doc.pages[0].id, PageId::from("a"));
    }

    #[test]
    fn add_page_refuses_duplicates_and_bad_routes() {
        let mut doc = fixture();
        let dup_id = apply_operations(&mut doc, &[WebOperation::AddPage { page: empty_page("home", "/x"), index: None }]);
        assert_eq!(dup_id.unwrap_err().code, "op.page_exists");
        let dup_route = apply_operations(&mut doc, &[WebOperation::AddPage { page: empty_page("x", "/"), index: None }]);
        assert_eq!(dup_route.unwrap_err().code, "op.route_exists");
        let bad_route = apply_operations(&mut doc, &[WebOperation::AddPage { page: empty_page("x", "/Bad"), index: None }]);
        assert_eq!(bad_route.unwrap_err().code, "op.route_invalid");
        assert_eq!(doc.pages.len(), 1, "a refused batch leaves the document untouched");
    }

    #[test]
    fn the_last_page_cannot_be_removed() {
        let mut doc = fixture();
        let err = apply_operations(&mut doc, &[WebOperation::RemovePage { page_id: page_id() }]).unwrap_err();
        assert_eq!(err.code, "op.cannot_remove_last_page");
    }

    #[test]
    fn set_page_meta_refuses_an_invalid_route() {
        let mut doc = fixture();
        let err = apply_operations(
            &mut doc,
            &[WebOperation::SetPageMeta { page_id: page_id(), name: None, route: Some("/Bad Route".into()) }],
        )
        .unwrap_err();
        assert_eq!(err.code, "op.route_invalid");
    }
```

- [ ] **Step 2: Run to verify failure** — `cargo test -p lumen-web add_page remove_page the_last_page set_page_meta_refuses` → compile errors (no such variants).

- [ ] **Step 3: Implement**

Enum additions (after `SetPageMeta` at `:121-127`):

```rust
    /// Insert a whole page (F5). An empty page is its root Container alone. Refused when the
    /// id or route already exists, the route fails the grammar, or `root` is not in `nodes`.
    AddPage {
        page: crate::doc::WebPage,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        index: Option<usize>,
    },
    /// Remove a page; the inverse re-inserts it verbatim at its former index. The last page
    /// is refused by name (validation would refuse it too, as LUMW0002).
    RemovePage {
        page_id: PageId,
    },
```

`use crate::validate::{route_is_valid, validate_web_doc};` at the top (replace the existing `validate_web_doc` import line).

Dispatch arms (append inside the `match operation` in `apply_operation_in_place`, before the closing brace):

```rust
        WebOperation::AddPage { page, index } => {
            if doc.page(&page.id).is_some() {
                return Err(WebOpError::new("op.page_exists", format!("page `{}` already exists", page.id)));
            }
            if doc.pages.iter().any(|existing| existing.route == page.route) {
                return Err(WebOpError::new("op.route_exists", format!("route `{}` is already taken", page.route)));
            }
            if !route_is_valid(&page.route) {
                return Err(WebOpError::new("op.route_invalid", format!("route `{}` is not a valid site route", page.route)));
            }
            if !page.nodes.contains_key(&page.root) {
                return Err(WebOpError::new("op.page_root_missing", format!("page `{}` root `{}` is not in its nodes", page.id, page.root)));
            }
            let at = index.unwrap_or(doc.pages.len());
            if at > doc.pages.len() {
                return Err(WebOpError::new("op.index_out_of_range", format!("page index {at} is past the end ({})", doc.pages.len())));
            }
            doc.pages.insert(at, page.clone());
            Ok(WebOperation::RemovePage { page_id: page.id.clone() })
        }
        WebOperation::RemovePage { page_id } => {
            if doc.pages.len() <= 1 {
                return Err(WebOpError::new("op.cannot_remove_last_page", "a document keeps at least one page"));
            }
            let Some(at) = doc.pages.iter().position(|page| &page.id == page_id) else {
                return Err(WebOpError::new("op.page_missing", format!("page `{page_id}` not found")));
            };
            let page = doc.pages.remove(at);
            Ok(WebOperation::AddPage { page, index: Some(at) })
        }
```

`SetPageMeta` arm: before `require_page_mut`, add

```rust
            if let Some(candidate) = route {
                if !route_is_valid(candidate) {
                    return Err(WebOpError::new("op.route_invalid", format!("route `{candidate}` is not a valid site route")));
                }
                if doc.pages.iter().any(|other| &other.id != page_id && &other.route == candidate) {
                    return Err(WebOpError::new("op.route_exists", format!("route `{candidate}` is already taken")));
                }
            }
```

`WebPage` must derive `Serialize, Deserialize, Clone, PartialEq, Debug` — it already does (`doc.rs:81`).

- [ ] **Step 4: Run** — `cargo test -p lumen-web` green; then `cargo test --workspace` green.
- [ ] **Step 5: Rebuild ritual** — `cargo build -p lumen-api-helper --release && bash scripts/build_wasm_core.sh && node scripts/verify_handshake.mjs` (expect `HANDSHAKE OK`). Restart the running design API / fleet worker if any (they hold `LUMEN_CORE_HELPER`).
- [ ] **Step 6: Commit** — `git commit -m "feat(lumen-web): AddPage/RemovePage ops — invertible, route-checked; SetPageMeta refuses bad or duplicate routes"` (include the rebuilt wasm artifacts if they are tracked — check `git status`; the editor's `public/` wasm copy is tracked in this repo per prior F1 commits).

---

### Task 3: API round-trip — a page added through `/web/operations` reads back and renders

**Files:**
- Test: `subsystems/clue-design/apps/api/tests/test_web_documents.py` (helpers `create_web_document` at `:30`)

No production change is expected: `POST /documents/{id}/web/operations` (`main.py:3836`) forwards ops to the helper's checked apply. This task PROVES that and pins it.

- [ ] **Step 1: Write the test**

```python
def _empty_page(page_id: str, route: str, name: str = "Pricing") -> dict:
    root = f"root_{page_id}"
    return {
        "id": page_id,
        "name": name,
        "route": route,
        "root": root,
        "nodes": {root: {"id": root, "kind": "container", "classes": "", "children": []}},
    }


def test_add_page_operation_round_trips_and_is_inverted(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "operations": [{"kind": "add_page", "page": _empty_page("pricing", "/pricing")}],
            "base_version": document["current_version"],
            "intent": "add pricing page",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    routes = [page["route"] for page in body["document"]["scene"]["pages"]]
    assert routes == ["/", "/pricing"]
    assert body["inverse_operations"][0]["kind"] == "remove_page"


def test_add_page_with_a_bad_route_is_refused_whole(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [{"kind": "add_page", "page": _empty_page("x", "/Bad Route")}]},
    )
    assert response.status_code == 422, response.text
    assert "op.route_invalid" in response.text
    again = client.get(f"/documents/{document['id']}").json()["scene"]
    assert len(again["pages"]) == 1
```

- [ ] **Step 2: Run** — `PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/pytest apps/api/tests/test_web_documents.py -q -k add_page`. If the response key names differ from `document` / `inverse_operations`, read the route's return dict at `main.py:3836-3920` and correct the TEST to the route's real keys (do not change the route).
- [ ] **Step 3: Commit** — `git commit -m "test(design-api): add_page rides the checked /web/operations path end to end"`

---

## Lane F5.1 — Page-aware render / preview

### Task 4: `GET /documents/{id}/web/render?page_id=` and a page-aware bridge

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:3564-3700` (`render_web_document`) — literals at `:3594, :3619, :3635, :3646, :3652, :3660, :3686`
- Modify: `subsystems/clue-design/apps/api/lumen_api/web_bridge.py:1250` (`render_bridge_script(nonce, web_doc=None, page_id="home")` — keep the signature, callers now pass the resolved page)
- Test: `subsystems/clue-design/apps/api/tests/test_web_documents.py`

**Interfaces:**
- Produces: query param `page_id: Optional[str] = None`; omitted ⇒ the document's FIRST page (not the literal `home`); unknown ⇒ `404 {"code": "web_render.page_missing"}`. A module-level helper in `main.py`:

```python
def resolve_web_page_id(web_doc: JsonObject, requested: Optional[str]) -> str:
    """The page a web read targets: the caller's page when it exists, else the first page.
    Raises HTTPException 404 `web_render.page_missing` for a named page that is not there."""
    pages = [p for p in (web_doc.get("pages") or []) if isinstance(p, dict)]
    if requested:
        if any(p.get("id") == requested for p in pages):
            return requested
        raise HTTPException(status_code=404, detail={"code": "web_render.page_missing",
                            "message": f"page {requested!r} is not in this document"})
    first = pages[0].get("id") if pages else None
    return first if isinstance(first, str) and first else "home"
```

- Task 5 (frontend), Task 6 (agent preview), Task 11 (publish) reuse `resolve_web_page_id`.

- [ ] **Step 1: Failing tests**

```python
def test_render_targets_the_requested_page(client: TestClient) -> None:
    document = create_web_document(client)
    client.post(f"/documents/{document['id']}/web/operations",
                json={"operations": [{"kind": "add_page", "page": _empty_page("pricing", "/pricing")}]})
    home = client.get(f"/documents/{document['id']}/web/render", params={"runtime_src": "/x.js"})
    pricing = client.get(f"/documents/{document['id']}/web/render",
                         params={"runtime_src": "/x.js", "page_id": "pricing"})
    assert home.status_code == 200 and pricing.status_code == 200
    assert 'data-lumen-node="root_pricing"' in pricing.json()["html"]
    assert 'data-lumen-node="root_pricing"' not in home.json()["html"]


def test_render_unknown_page_is_a_typed_404(client: TestClient) -> None:
    document = create_web_document(client)
    response = client.get(f"/documents/{document['id']}/web/render",
                          params={"runtime_src": "/x.js", "page_id": "nope"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "web_render.page_missing"
```

(If editor-mode markup does not stamp `data-lumen-node`, read one editor render in the existing tests to find the per-node attribute the engine emits and assert on that instead — the assertion is "the pricing root renders on the pricing page only".)

- [ ] **Step 2: Run** — expect the first test to fail on the `page_id` param being ignored.
- [ ] **Step 3: Implement** — add `page_id: Optional[str] = None` to the route signature; `page = resolve_web_page_id(web_doc, page_id)` right after `web_doc = document["scene"]`; replace every `"home"` literal in the route body with `page` (seven sites). Keep the bridge's default parameter but pass `page`.
- [ ] **Step 4: Run** the file → green.
- [ ] **Step 5: Commit** — `git commit -m "feat(design-api): web render targets a page — ?page_id, first-page default, typed 404"`

---

### Task 5: Platform shell render fetch takes a page

**Files:**
- Modify: `apps/frontend/src/features/design-editor/engine/webDocuments.ts:509` (`fetchWebRenderHtml`)
- Modify: `apps/frontend/src/features/design-editor/hooks/use-web-render.ts`
- Modify: `apps/frontend/src/features/design-editor/components/web-artifact-canvas.tsx`
- Test: `apps/frontend/src/features/design-editor/engine/webDocuments.test.ts` (create beside it if absent; existing tests live as `*.test.ts` siblings)

**Interfaces:**
- `fetchWebRenderHtml(options, documentId, runtimeSrc, bridge?, pageId?: string)` — appends `page_id` when given.
- `useWebRender({ ..., pageId?: string })` — refetches when `pageId` changes (add it to the effect deps next to the reload nonce).
- `WebArtifactCanvas` gains prop `pageId?: string` and forwards it. Task 18 supplies it from the stage.

- [ ] **Step 1: Failing test**

```ts
import test from "node:test";
import assert from "node:assert/strict";
import { fetchWebRenderHtml } from "./webDocuments";

test("fetchWebRenderHtml appends page_id when a page is named", async () => {
  const seen: string[] = [];
  const fetchImpl = (async (url: URL | string) => {
    seen.push(String(url));
    return new Response(JSON.stringify({ html: "<html></html>", diagnostics: [] }), {
      status: 200, headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
  await fetchWebRenderHtml({ apiBaseUrl: "http://api.test", fetchImpl } as never, "doc_1", "/rt.js", undefined, "pricing");
  assert.match(seen[0], /page_id=pricing/);
  await fetchWebRenderHtml({ apiBaseUrl: "http://api.test", fetchImpl } as never, "doc_1", "/rt.js");
  assert.doesNotMatch(seen[1], /page_id/);
});
```

- [ ] **Step 2: Run** — `npx tsx --test src/features/design-editor/engine/webDocuments.test.ts` → fails (arg ignored).
- [ ] **Step 3: Implement** — `if (pageId) url.searchParams.set("page_id", pageId);` in `fetchWebRenderHtml`; thread `pageId` through `useWebRender` and `WebArtifactCanvas`.
- [ ] **Step 4: Run** test + `npm run lint && npm run build`.
- [ ] **Step 5: Commit** — `git commit -m "feat(frontend): web render fetch and canvas take a pageId"`

---

## Lane F5.4 — Agent page vocabulary

### Task 6: Active page + page tools on `LumenWebTools`

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py` — `HOME_PAGE_ID`/`has_existing_content` at `:175-193`, `__init__` at `:870-905` (`self.page_id = HOME_PAGE_ID` at `:890`), `_consume_round_budget` `:1094`, `_record_operations` `:1177`, `render_web_preview` `:8670` (unchanged-render guard + `_preview_by_width`), `_render_page_html` `:8834`, `finalize_web_run` `:9386`
- Create: `subsystems/clue-design/apps/agent_runtime/tests/test_web_pages.py` (fixture style from `tests/test_web_account_logo_bind.py:109-118`: real `CoreClient(repo_root=REPO_ROOT).web_new_doc(...)` seed, `AgentRuntimeConfig.from_env(REPO_ROOT)` with `trace_dir` under `tmp_path`)

**Interfaces (tool methods on `LumenWebTools`; plain methods with docstrings, the harness passes bound methods):**
- `list_pages() -> str` — JSON `{"active_page": id, "pages": [{"id","name","route","sections": n}]}`; non-mutating, no budget charge.
- `add_page(page_id: str, name: str, route: str) -> str` — builds the empty page (root `root_<page_id>`), applies `add_page` through `self.core.web_apply_ops` (same refusal handling as `web_ops` at `:2334-2415`), records to `operations_ledger`, charges the budget, SWITCHES the active page to it, returns `{"status":"ok","active_page":page_id}`. Pre-checks the route with a Python mirror of Task 1's grammar (`_ROUTE_RE = re.compile(r"^/$|^(/[a-z0-9]+(?:-[a-z0-9]+)*)+$")` plus the reserved-segment rule) so the model gets a plain sentence, not an engine code.
- `remove_page(page_id: str) -> str` — `remove_page` op; if it was the active page, the active page becomes the first remaining page.
- `switch_page(page_id: str) -> str` — sets `self.page_id`; clears `self._preview_by_width` and the standing state captures (previews belong to a page) and resets `_mutations_since_render = 0` (founder: budget resets per page render; a switch is the start of a fresh page round). Non-mutating. Refuses an unknown page with the page list in the message.
- `has_existing_content(web_doc, page_id=None)` — `None` ⇒ any page has content (harness uses this, Task 8).
- `render_web_preview` records `page_id=self.page_id` in its `web_preview_rendered` event `payload` and writes `iter_N/page.txt` with the page id so the trace viewer knows which page a screenshot shows.
- `finalize_web_run` payload gains `"pages": [{"id","route","sections"}]` (informational; NO gate).

- [ ] **Step 1: Failing tests** (`tests/test_web_pages.py`)

```python
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from lumen_agent.config import AgentRuntimeConfig
from lumen_agent.tools.web_substrate import LumenWebTools, has_existing_content

REPO_ROOT = Path(__file__).resolve().parents[3]


def _tools(tmp_path: Path) -> LumenWebTools:
    from lumen_api.core import CoreClient

    config = replace(AgentRuntimeConfig.from_env(REPO_ROOT), trace_dir=tmp_path / "workspace_root")
    seed = CoreClient(repo_root=REPO_ROOT).web_new_doc("doc_site", "Site", None)["web_doc"]
    return LumenWebTools(config, "Build a microsite", initial_web_doc=seed)


def test_add_page_switches_the_active_page_and_lands_in_the_ledger(tmp_path):
    tools = _tools(tmp_path)
    out = json.loads(tools.add_page("pricing", "Pricing", "/pricing"))
    assert out["status"] == "ok" and out["active_page"] == "pricing"
    assert tools.page_id == "pricing"
    assert [p["route"] for p in tools.web_doc["pages"]] == ["/", "/pricing"]
    assert tools.operations_ledger[-1]["kind"] == "add_page"
    listing = json.loads(tools.list_pages())
    assert listing["active_page"] == "pricing" and len(listing["pages"]) == 2


def test_add_page_refuses_a_bad_route_in_plain_words(tmp_path):
    tools = _tools(tmp_path)
    out = json.loads(tools.add_page("x", "X", "/Bad Route"))
    assert out["status"] != "ok"
    assert "lowercase" in json.dumps(out)
    assert len(tools.web_doc["pages"]) == 1 and tools.operations_ledger == []


def test_switch_page_resets_the_round_budget_and_previews(tmp_path):
    tools = _tools(tmp_path)
    tools.add_page("pricing", "Pricing", "/pricing")
    tools._mutations_since_render = 9
    tools._preview_by_width = {1440: tmp_path / "fake.png"}
    out = json.loads(tools.switch_page("home"))
    assert out["status"] == "ok" and tools.page_id == "home"
    assert tools._mutations_since_render == 0 and tools._preview_by_width == {}
    bad = json.loads(tools.switch_page("nope"))
    assert bad["status"] != "ok" and "pricing" in json.dumps(bad)


def test_remove_page_moves_the_active_page_and_keeps_the_last_one(tmp_path):
    tools = _tools(tmp_path)
    tools.add_page("pricing", "Pricing", "/pricing")
    assert json.loads(tools.remove_page("pricing"))["status"] == "ok"
    assert tools.page_id == "home"
    last = json.loads(tools.remove_page("home"))
    assert last["status"] != "ok" and len(tools.web_doc["pages"]) == 1


def test_has_existing_content_without_a_page_means_any_page(tmp_path):
    tools = _tools(tmp_path)
    tools.add_page("pricing", "Pricing", "/pricing")
    assert has_existing_content(tools.web_doc) is False
    page = tools.web_doc["pages"][1]
    page["nodes"]["sec"] = {"id": "sec", "kind": "section", "classes": "", "children": []}
    page["nodes"][page["root"]]["children"] = ["sec"]
    assert has_existing_content(tools.web_doc) is True
    assert has_existing_content(tools.web_doc, "home") is False
```

- [ ] **Step 2: Run** — `PYTHONPATH=.:apps/api:apps/agent_runtime .venv/bin/pytest apps/agent_runtime/tests/test_web_pages.py -q` → AttributeError on `add_page`.
- [ ] **Step 3: Implement** — the four tools next to `web_ops` (`:2270`), sharing its `CoreError` → `_rejected` handling verbatim (copy the `except CoreError` block; do not invent a new shape). `add_page` body core:

```python
        refusal = self._consume_round_budget("add_page")
        if refusal is not None:
            return refusal
        clean_id = (page_id or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", clean_id):
            return self._tool_error("add_page.bad_id", "page_id must be lowercase letters, digits, '-' or '_' (start with a letter).")
        if not _route_is_valid(route):
            return self._tool_error("add_page.bad_route", f"route {route!r} is not a valid site route: use '/' or '/lowercase-segments/like-this' (no trailing slash, no 'manifest.json', not starting with 'p-assets' or 'asset-store').")
        root_id = f"root_{clean_id}"
        page = {"id": clean_id, "name": (name or clean_id).strip(), "route": route.strip(), "root": root_id,
                "nodes": {root_id: {"id": root_id, "kind": "container", "classes": "", "children": []}}}
        operations = [{"kind": "add_page", "page": page}]
        # … core.web_apply_ops(self.web_doc, operations) with the web_ops error handling …
        self.web_doc = response["web_doc"]
        self._record_operations(operations)
        self._doc_version += 1
        self.page_id = clean_id
        self._preview_by_width = {}
        self.record("author", "web_page_added", input_summary=f"{clean_id} {route}", payload={"page_id": clean_id, "route": route})
        return json.dumps({"status": "ok", "active_page": clean_id, "pages": self._page_listing()}, indent=2)
```

`_route_is_valid` module-level (mirror of Task 1). `_page_listing()` = list of `{id, name, route, sections: web_doc_page_section_count(self.web_doc, id)}` (import from `lumen_api.fragments.render`, already imported at `:8041`). Update the `has_existing_content` signature (`page_id: Optional[str] = None`, loop all pages when `None`). Update the web_ops docstring lines `:2284-2315` — replace `page_id is ALWAYS "home" in v0` with `page_id names the page (see list_pages; the active page is the one you were briefed on)`.

- [ ] **Step 4: Run** the new file + `tests/test_web_substrate.py` + `tests/test_web_review_gate.py` (one file per process) → green.
- [ ] **Step 5: Commit** — `git commit -m "feat(design-agent): active page + list/add/remove/switch page tools on the web substrate"`

---

### Task 7: The API's turn side stops assuming `home`

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/fragments/render.py` (add `web_doc_all_fragment_ids`, `web_doc_page_ids`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:8664-8700` (`_describe_web_turn_targets`), `:8840-8847` (turn fragment package)
- Test: `subsystems/clue-design/apps/api/tests/test_agent_cloned_sections.py` (or a new `test_web_turn_pages.py` beside it)

**Interfaces:**
- `web_doc_page_ids(web_doc) -> list[str]`; `web_doc_all_fragment_ids(web_doc) -> list[str]` (union in page order, once each).
- `build_fragment_render_package(storage, *, workspace_id, web_doc, page_id)` keeps its signature; the turn builds the package for ALL pages by passing each page and merging `fragments`/`missing` maps — add a thin `build_fragment_render_package_for_document(storage, *, workspace_id, web_doc)` that loops pages and merges (dict union for `fragments`, list union for `missing`, `css` concatenated once per fragment id).
- `_describe_web_turn_targets(web_doc, target_node_ids)` searches every page and names the page in each line: `- node <id> (<kind>) on page <page_id> in section <sec>`.

- [ ] **Step 1: Failing tests**

```python
def test_all_fragment_ids_unions_pages_in_order():
    from lumen_api.fragments.render import web_doc_all_fragment_ids
    doc = {"pages": [
        {"id": "home", "root": "r1", "nodes": {"r1": {"id": "r1", "kind": "container", "children": ["f1"]},
                                               "f1": {"id": "f1", "kind": "fragment", "fragment_id": "frag_a", "children": []}}},
        {"id": "pricing", "root": "r2", "nodes": {"r2": {"id": "r2", "kind": "container", "children": ["f2", "f3"]},
                                                  "f2": {"id": "f2", "kind": "fragment", "fragment_id": "frag_b", "children": []},
                                                  "f3": {"id": "f3", "kind": "fragment", "fragment_id": "frag_a", "children": []}}},
    ]}
    assert web_doc_all_fragment_ids(doc) == ["frag_a", "frag_b"]


def test_turn_targets_are_found_on_any_page():
    from lumen_api.main import _describe_web_turn_targets
    doc = {"pages": [
        {"id": "home", "root": "r1", "nodes": {"r1": {"id": "r1", "kind": "container", "children": []}}},
        {"id": "pricing", "root": "r2", "nodes": {"r2": {"id": "r2", "kind": "container", "children": ["s"]},
                                                  "s": {"id": "s", "kind": "section", "children": ["t"]},
                                                  "t": {"id": "t", "kind": "text", "children": []}}},
    ]}
    text = _describe_web_turn_targets(doc, ["t"])
    assert "pricing" in text and "t" in text
```

- [ ] **Step 2: Run** → ImportError / "pricing" missing.
- [ ] **Step 3: Implement** the helpers; rewrite `_describe_web_turn_targets` to iterate `(page, nodes)` over all pages; in the turn config (`:8840`) replace `web_doc_fragment_ids(web_doc, "home")` with `web_doc_all_fragment_ids(web_doc)` and the package builder with the for-document variant.
- [ ] **Step 4: Run** the test file(s) → green. Also run `apps/api/tests/test_agent_cloned_sections.py` (it exercises the package builder).
- [ ] **Step 5: Commit** — `git commit -m "fix(design-api): the web turn resolves fragments and targets across every page"`

---

### Task 8: Harness, prompts, and skills teach pages (and R-F5-8's guidance)

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/harness_web.py` — orchestrator tool list `:391-413`, author tool list `:300-320`, `has_existing_content(initial_web_doc, HOME_PAGE_ID)` `:~428`
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/prompts_web.py` — `build_web_orchestrator_prompt` (`:102`; `starting_state` `:128-130`; "PLAN THE WHOLE PAGE INTO ONE AUTHOR BRIEF" `:178-183`), `build_web_author_prompt` (`:472`)
- Modify skills: `knowledge_docs/skills/create-website/SKILL.md` (add `## Multi-page sites` after `## Page structure and rhythm` `:179`), `edit-website/SKILL.md` (page verbs in the ladders `:40-60`), `campaign-page-workflow/SKILL.md` (Step 4 plan → routes; Step 5 skeleton per page; Step 9 render per page), `conversion-copywriting/SKILL.md:2` (quote the description — the unquoted colon breaks YAML and the materializer skips the skill)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_web_pages.py` (extend) + `tests/test_format_skill_library.py` style check that every `skills/*/SKILL.md` frontmatter parses

**Interfaces:**
- Orchestrator gets `tools.list_pages, tools.add_page, tools.remove_page, tools.switch_page`. Author gets `tools.list_pages` only (it writes the active page the director set; ops still carry an explicit `page_id`, so nothing is mechanically fenced — R-F5-8 spirit).
- Prompt law (verbatim text to add to the orchestrator prompt, replacing the "PLAN THE WHOLE PAGE" paragraph's absolutism):

```
ONE AUTHOR BRIEF PER PAGE. A site is one document with N pages. Before the first
delegation, create every page the plan names (add_page: id, name, route — the home
page's route stays "/"), then for EACH page: switch_page, delegate ONE author brief
that plans that whole page (every section, copy angle, image, CTA — nothing held back),
render_web_preview, review, amend. Never brief two pages in one delegation: the author
edits the ACTIVE page, and the edit budget is per page-round.

LINKS. A page may link anywhere — nothing refuses a link. On a campaign page it is
still poor practice to send the visitor off the argument: prefer links between THIS
site's pages (write the route, e.g. href="/pricing") and the one CTA; treat any link
to the seller's public site or a third party as a deliberate choice you can defend
in the finalize summary.
```

- Author prompt gains one line under its page-authoring rules: `Write site-internal links as the page's ROUTE (href="/pricing"); publishing rewrites them to the live address.`
- `starting_state` (`:128-130`) becomes page-aware: `"The document has {n} page(s): {routes}. Treat the turn as an edit …"`.
- Skill wording follows the standing rule: plain, simple language; brevity from fewer rules, never compression. (Skill text is founder-review material — quote the final wording in the task report.)

- [ ] **Step 1: Failing tests**

```python
def test_conversion_copywriting_frontmatter_parses():
    import yaml
    path = REPO_ROOT / "apps/agent_runtime/knowledge_docs/skills/conversion-copywriting/SKILL.md"
    front = path.read_text().split("---")[1]
    meta = yaml.safe_load(front)
    assert meta["name"] == "conversion-copywriting"


def test_orchestrator_prompt_teaches_one_brief_per_page():
    from lumen_agent.prompts_web import build_web_orchestrator_prompt
    text = build_web_orchestrator_prompt(doc_title="Site", has_existing_content=False, brand_card="",
                                         review_cap=6, author_cap=4, account_card=None, page_routes=["/"])
    assert "ONE AUTHOR BRIEF PER PAGE" in text and "add_page" in text and "switch_page" in text
```

(Match the real keyword list of `build_web_orchestrator_prompt` at `:102`; add the new `page_routes: list[str]` keyword and pass `[p["route"] for p in initial_web_doc["pages"]]` from the harness.)

- [ ] **Step 2: Run** → yaml error / assertion.
- [ ] **Step 3: Implement** the four edits + the skill sections. `create-website` `## Multi-page sites` (draft):

```
## Multi-page sites

A site is one document with many pages. Each page has an id, a name and a route.
The home page's route is `/`. Other routes look like `/pricing` or `/security/soc-2`:
lowercase words joined by dashes, no trailing slash.

- The director creates pages and switches the active page before briefing you.
  You author the active page. Every op you write names its `page_id`.
- Link between pages by route: `<a href="/pricing">`. Publishing turns the route
  into the live address.
- You may link off the site. On a campaign page that is rarely a good idea — every
  link away is a visitor who stops reading the argument. Prefer the site's own
  pages and the one CTA. If you link away, say why in your summary.
```

- [ ] **Step 4: Run** `tests/test_web_pages.py`, `tests/test_deepagent_harness.py`, `tests/test_format_skill_library.py` (one per process) → green.
- [ ] **Step 5: Commit** — `git commit -m "feat(design-agent): page vocabulary in the harness, prompts and skills — one author brief per page; links free, guided"`

---

### Task 9: R-F5-8 — the F4 escape-route gates become advisory

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/fragments/campaign_shell.py:437-500` (`assert_campaign_shell_shape(role, html) -> None` raising `FragmentRefused("fragment.shell_escape_route", …)`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/agent_cloned_sections.py:944, :1099, :1402` (the three callers)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/tools/web_substrate.py:7073, :7117` (`is_escape_route_role` refusals inside `assemble_abm_page`)
- Test: `apps/api/tests/test_campaign_shell.py`, `apps/agent_runtime/tests/test_web_abm_assembly.py`, `apps/api/tests/test_abm_assembly.py`

**Interfaces:**
- New `campaign_shell_shape_notes(role, html) -> list[str]` returns the SAME findings as sentences (e.g. `"the campaign header carries 3 anchors; the campaign-shell practice is one CTA"`); `assert_campaign_shell_shape` stays as a thin wrapper for any test that still imports it but is no longer called on the mint path.
- The three mint callers append the notes to the tool result's `advice` list (the `warnings`/`advice` split already exists — `_split_non_error_diagnostics` in the substrate; on the API side the mint result dict already carries `warnings`; add `advice` if absent).
- `assemble_abm_page`: a cloned `nav`/`footer` role is PINNED when asked and the result carries `advice: ["<id> is a cloned nav — its links leave this page; on a campaign page that is usually poor practice (R-F5-8: allowed, not recommended)"]`.
- The publish-manifest `_escape_route_audit` (`web_export.py:94`) is unchanged.

- [ ] **Step 1: Flip the tests first** — in `test_campaign_shell.py` the cases that `pytest.raises(FragmentRefused)` on a multi-anchor header become `notes = campaign_shell_shape_notes("campaign_header", html); assert notes and "anchors" in notes[0]`; in `test_web_abm_assembly.py` the "refuses a cloned nav" case becomes "pins it and advises". Run → red.
- [ ] **Step 2: Implement** the demotion (keep every detection; change only the verb from raise to append).
- [ ] **Step 3: Run** the three files → green. Grep: `grep -rn "assert_campaign_shell_shape(" apps/api/lumen_api` must show zero non-test call sites.
- [ ] **Step 4: Commit** — `git commit -m "feat(design): R-F5-8 — escape-route gates advise instead of refusing; nav/footer clones pin with a note"`

---

## Lane F5.2 — N-page publish + serving

### Task 10: Publish pages — migration + DAL

**Files:**
- Create: `alembic/versions/<hash>_design_web_publish_pages.py` (`alembic revision -m "design_web_publish_pages"`; `down_revision = "6eff96862040"` — verify with `uv run alembic heads`)
- Modify: `subsystems/design/clue_design/publishes.py` (`register_web_publish_revision` `:120`, `upsert_web_publish` `:249`, `rollback_web_publish` `:315`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/design_store.py:1268-1345` (facade)
- Test: `tests/design/test_web_publish_pages_dal_db.py` (DB-gated; copy the fixture pattern from `tests/design/test_dal_foundation_db.py`)

**Schema (two tables; the revision one is immutable like its parent, the current one is derived):**

```sql
CREATE TABLE design_web_publish_revision_page (
    publish_id   text NOT NULL REFERENCES design_web_publish_revision (publish_id),
    route        text NOT NULL,
    page_id      text NOT NULL,
    html         text NOT NULL,
    html_digest  text NOT NULL,
    CONSTRAINT design_web_publish_revision_page_pkey PRIMARY KEY (publish_id, route)
);
-- reject UPDATE/DELETE by trigger, mirroring design_web_publish_revision_reject_update (86a9ce389e6e:200)

CREATE TABLE design_web_publish_page (
    workspace_id text NOT NULL,
    slug         text NOT NULL,
    route        text NOT NULL,
    page_id      text NOT NULL,
    html         text NOT NULL,
    html_digest  text NOT NULL,
    CONSTRAINT design_web_publish_page_pkey PRIMARY KEY (workspace_id, slug, route),
    CONSTRAINT design_web_publish_page_publish_fk FOREIGN KEY (workspace_id, slug)
        REFERENCES design_web_publish (workspace_id, slug) ON DELETE CASCADE
);
```

**DAL interfaces (async, `conn: AsyncConnection`, keyword-only like their siblings):**
- `register_web_publish_revision(conn, *, workspace_id, revision)` — `revision` gains `"pages": [{"route","page_id","html","html_digest"}]`; inserts the revision pages (`ON CONFLICT DO NOTHING`, same idempotency as the parent).
- `materialize_web_publish_pages(conn, *, workspace_id, slug, publish_id)` — `DELETE FROM design_web_publish_page WHERE workspace_id=:w AND slug=:s` then `INSERT … SELECT :w, :s, route, page_id, html, html_digest FROM design_web_publish_revision_page WHERE publish_id=:p`. Called by `upsert_web_publish` after its upsert, and by `rollback_web_publish` with the swapped-in `publish_id`.
- `get_web_publish_page(conn, *, workspace_id, slug, route) -> JsonObject | None`.
- `list_web_publish_pages(conn, *, workspace_id, slug) -> list[JsonObject]` (route, page_id, html_digest — no html).
- Back-compat: `design_web_publish.html` keeps holding the `/` page's HTML (Task 11 passes it), so nothing that reads it today breaks; a publish with no revision pages (pre-F5 rows) serves the legacy `html` at `/` and 404s elsewhere.
- Facade (`design_store.py`): `register_web_publish_revision` (unchanged signature, revision dict grows), `get_web_publish_page(slug, route)`, `list_web_publish_pages(slug)`.

- [ ] **Step 1: Failing DB test**

```python
import pytest
from clue_design import publishes

pytestmark = pytest.mark.asyncio


async def test_publish_pages_materialize_and_roll_back(conn, workspace_id, web_document):
    slug, doc_id = "site", web_document["id"]
    rev1 = {"slug": slug, "document_id": doc_id, "doc_version": 1, "html": "<h1>v1 home</h1>",
            "html_digest": "a" * 64, "manifest": {}, "manifest_digest": "m1", "package_digest": "p1" * 32,
            "runtime_version": None,
            "pages": [{"route": "/", "page_id": "home", "html": "<h1>v1 home</h1>", "html_digest": "a" * 64},
                      {"route": "/pricing", "page_id": "pricing", "html": "<h1>v1 pricing</h1>", "html_digest": "b" * 64}]}
    await publishes.register_web_publish_revision(conn, workspace_id=workspace_id, revision=rev1)
    await publishes.upsert_web_publish(conn, workspace_id=workspace_id, slug=slug, document_id=doc_id, doc_version=1,
                                       html=rev1["html"], runtime_version=None, publish_id="webpub_" + rev1["package_digest"])
    page = await publishes.get_web_publish_page(conn, workspace_id=workspace_id, slug=slug, route="/pricing")
    assert page["html"] == "<h1>v1 pricing</h1>"

    rev2 = {**rev1, "doc_version": 2, "package_digest": "p2" * 32, "html": "<h1>v2 home</h1>",
            "pages": [{"route": "/", "page_id": "home", "html": "<h1>v2 home</h1>", "html_digest": "c" * 64}]}
    await publishes.register_web_publish_revision(conn, workspace_id=workspace_id, revision=rev2)
    await publishes.upsert_web_publish(conn, workspace_id=workspace_id, slug=slug, document_id=doc_id, doc_version=2,
                                       html=rev2["html"], runtime_version=None, publish_id="webpub_" + rev2["package_digest"])
    assert await publishes.get_web_publish_page(conn, workspace_id=workspace_id, slug=slug, route="/pricing") is None

    await publishes.rollback_web_publish(conn, workspace_id=workspace_id, slug=slug)
    back = await publishes.get_web_publish_page(conn, workspace_id=workspace_id, slug=slug, route="/pricing")
    assert back is not None and back["html"] == "<h1>v1 pricing</h1>"
```

(Use the workspace/document fixtures `tests/design/conftest.py` provides; if there is no web-document fixture, insert a `design_document` row the way `test_dal_foundation_db.py` does.)

- [ ] **Step 2: Run** — `uv run pytest tests/design/test_web_publish_pages_dal_db.py -q` → fails (no table / no fn).
- [ ] **Step 3: Write the migration** (hand-written `upgrade()`/`downgrade()`, triggers mirrored from `86a9ce389e6e:198-215`), then the DAL, then the facade. `make db-smoke` on a throwaway DB (never the dev DB): up → down → up must pass; `uv run alembic heads` → exactly one.
- [ ] **Step 4: Run** the test → green. Run `tests/design/test_dal_foundation_db.py` (enum/parity guards) → green.
- [ ] **Step 5: Commit** — `git commit -m "feat(design-db): per-route publish pages — immutable revision pages + materialized current pages, rollback-aware"`

---

### Task 11: The publish package renders every page; serving by route; export ZIP per page

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/web_export.py` — `PublishPackage` `:273`, `_home_page` `:458`, `_resolve_fragments` `:624`, `_custom_component_package` `:1157`, `_delivery_manifest` `:1210`, `build_export_bundle` `:1291` (render at `:1356-1358`, `index.html` at `:1471`), `build_publish_package` `:1484-1675`
- Modify: `subsystems/clue-design/apps/api/lumen_api/toolbelt/publishes.py:91-170` (`publish_web_document`)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:5467-5525` (serving), `:4358` (publish state gains `pages`)
- Test: `apps/api/tests/test_web_export.py` (pattern at `:259-280`), `apps/api/tests/test_abm_batch_publish.py` (must stay green — batch publishes one-page documents)

**Interfaces:**
- `PublishedPage(page_id: str, route: str, html: str, html_digest: str)` dataclass; `PublishPackage.pages: List[PublishedPage]`; `PublishPackage.html` = the `/` page's HTML (first page when no page has route `/`).
- `build_publish_package(core, repo, document, *, blobs, slug, public_base, workspace_id, node_bin, noindex, site_address: "PublicSiteAddress | None" = None)` — Task 12 supplies `site_address`; until then the interim `public_prefix = f"{base}/w/{workspace_id}"` and `site_path = f"/p/{slug}"` stand. Per page: render (`core.web_render(web_doc, page["id"], …)`), per-page SEO head (`canonical`/`og:url` = `{origin}{site_path}{route_suffix}` where `route_suffix` is `""` for `/` and the route otherwise), `noindex` on every page, static CSS compiled per page (`_compile_static_css` on that page's document-only HTML), manifest `pages: [{page_id, route, html_digest}]`, `package_digest` over the sorted page digests + manifest digest + asset digests.
- **Internal link rewrite** (`rewrite_site_links(html, routes, site_path) -> str`): for every `href="<route>"` whose value EXACTLY equals one of the document's routes, replace with `{site_path}` (route `/`) or `{site_path}{route}`; nothing else is touched (a cloned band's `/asset-store/…` or `/careers` that is not a route stays as it is). Unit-tested in isolation.
- Fragment and custom-component resolution use `web_doc_all_fragment_ids` (Task 7) and iterate pages for `_custom_component_package` (`page_id` per page; merge frames/assets by digest).
- `publish_web_document` passes `pages` to `register_web_publish_revision`; the `WebPublishRef` gains `page_count: int` and `routes: list[str]`.
- Serving (`main.py`): route ORDER matters — keep `serve_publish_manifest` (`/w/{ws}/p/{slug}/manifest.json`) declared BEFORE the new `@app.get("/w/{workspace_id}/p/{slug}/{route:path}")`; both `serve_published_page` (route `/`) and the new handler resolve through one helper `_serve_site_page(repo, slug, route, request)`: `repo.get_web_publish(slug)` must be `active`; page = `repo.get_web_publish_page(slug, route)`; when the pages table has no row for `/` (pre-F5 publish) fall back to `publish["html"]`; otherwise 404 with the existing not-found HTML. Same headers/CSP as today.
- `GET /documents/{id}/web/publish` adds `"pages": repo.list_web_publish_pages(slug)`.
- Export ZIP (`build_export_bundle`): `index.html` for `/`; `<route without leading slash>/index.html` for every other page; links rewritten with `site_path=""` and a relative-safe form: for the ZIP, rewrite route `/pricing` → `/pricing/` (folder form) so a static host serves it. Manifest `file_names` includes them.

- [ ] **Step 1: Failing tests**

```python
def test_publish_serves_every_page_at_its_route(client: TestClient, workspace_id: str) -> None:
    document = create_web_document(client)
    client.post(f"/documents/{document['id']}/web/operations", json={"operations": [
        {"kind": "add_page", "page": {"id": "pricing", "name": "Pricing", "route": "/pricing", "root": "rp",
                                      "nodes": {"rp": {"id": "rp", "kind": "container", "classes": "", "children": []}}}}]})
    web_doc = client.get(f"/documents/{document['id']}").json()["scene"]
    home_html = '<section id="hero"><h1>Home</h1><p><a href="/pricing">See pricing</a></p></section>'
    seeded = client.app.state.core.web_ingest_html(web_doc, "home", home_html, None, None)["web_doc"]
    seeded = client.app.state.core.web_ingest_html(seeded, "pricing", '<section id="plans"><h1>Plans</h1></section>', None, None)["web_doc"]
    seed_content(client, document["id"], seeded)

    published = client.post(f"/documents/{document['id']}/web/publish", json={"slug": "multi"})
    assert published.status_code == 200, published.text
    assert published.json()["routes"] == ["/", "/pricing"]

    home = client.get(f"/w/{workspace_id}/p/multi")
    pricing = client.get(f"/w/{workspace_id}/p/multi/pricing")
    assert home.status_code == 200 and "Home" in home.text
    assert pricing.status_code == 200 and "Plans" in pricing.text
    assert f'href="/w/{workspace_id}/p/multi/pricing"' in home.text  # site link rewritten
    assert f'<link rel="canonical" href="' in pricing.text and "/p/multi/pricing" in pricing.text
    assert client.get(f"/w/{workspace_id}/p/multi/nope").status_code == 404

    state = client.get(f"/documents/{document['id']}/web/publish").json()
    assert [p["route"] for p in state["pages"]] == ["/", "/pricing"]


def test_rewrite_site_links_touches_only_document_routes():
    from lumen_api.web_export import rewrite_site_links
    html = '<a href="/pricing">a</a><a href="/careers">b</a><img src="/asset-store/abc"><a href="/">home</a>'
    out = rewrite_site_links(html, ["/", "/pricing"], "/w/ws1/p/site")
    assert 'href="/w/ws1/p/site/pricing"' in out and 'href="/w/ws1/p/site"' in out
    assert 'href="/careers"' in out and 'src="/asset-store/abc"' in out
```

- [ ] **Step 2: Run** → red (no `routes`, 404 on `/pricing`).
- [ ] **Step 3: Implement** in this order: `rewrite_site_links` (pure, `re.sub(r'href="(/[^"]*)"', …)` with an exact-route set), `PublishedPage` + the per-page loop in `build_publish_package`, the toolbelt persistence, the serving helper, the export bundle loop.
- [ ] **Step 4: Run** `test_web_export.py`, `test_abm_batch_publish.py`, `test_web_fragment_export.py`, `test_custom_component_publish.py` → green. The `package_digest` of a ONE-page document changes because the manifest gains `pages` — that is expected; update any test that pinned a literal digest, and say so in the commit.
- [ ] **Step 5: Commit** — `git commit -m "feat(design-api): publish renders every page and serves it by route; site links rewritten; export ZIP per page"`

---

### Task 12: Public address from config (`PublicSiteAddress`)

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/public_address.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py:7345-7352` (`public_publish_path`), `:4317-4345` (publish route passes the address), `:4358` (publish state returns an ABSOLUTE `url` + `page_urls`), `:5260-5330` batch (same)
- Modify: `.env.example` (design section after line 252), `subsystems/clue-design/.env.example` (after `LUMEN_API_ORIGIN`, line 22), local `.env`
- Test: `apps/api/tests/test_public_address.py` (new)

**Interfaces:**
```python
@dataclass(frozen=True)
class PublicSiteAddress:
    origin: str        # "https://acme.pages.cluehq.ai" or the interim "http://127.0.0.1:8010"
    site_path: str     # "/abm-openai" (host mode) or "/w/ws_x/p/abm-openai" (interim)
    asset_origin: str  # where /p-assets and /asset-store resolve — same as origin in both modes

    def page_url(self, route: str) -> str:
        return f"{self.origin}{self.site_path}" + ("" if route == "/" else route)

def public_site_address(*, request_base_url: str, workspace_id: str, slug: str, handle: str | None) -> PublicSiteAddress
```
- Env: `LUMEN_PUBLIC_PAGES_HOST_SUFFIX=` (blank = interim mode; production `pages.cluehq.ai`), `LUMEN_PUBLIC_PAGES_SCHEME=https`. Read in `public_address.py` via `os.environ.get` (the design API has no settings class — see `LUMEN_API_ORIGIN` precedent in `lumen_agent/config.py:151`). When the suffix is set AND a handle exists → host mode; otherwise interim (so dev keeps working with no DNS).
- `build_publish_package` takes `site_address` and derives `public_prefix`/canonical/og/manifest link/p-assets URLs from it (Task 11 left the parameter in place).
- `GET /documents/{id}/web/publish` returns `url` as the absolute `page_url("/")` and `page_urls: {route: url}`; the frontend (Task 13) shows exactly this — no client-side host constant.

- [ ] **Step 1: Failing tests**

```python
def test_interim_address_when_no_host_suffix(monkeypatch):
    monkeypatch.delenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", raising=False)
    from lumen_api.public_address import public_site_address
    a = public_site_address(request_base_url="http://127.0.0.1:8010/", workspace_id="ws1", slug="site", handle="acme")
    assert a.page_url("/") == "http://127.0.0.1:8010/w/ws1/p/site"
    assert a.page_url("/pricing") == "http://127.0.0.1:8010/w/ws1/p/site/pricing"


def test_host_address_when_suffix_and_handle(monkeypatch):
    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", "pages.cluehq.ai")
    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_SCHEME", "https")
    from lumen_api.public_address import public_site_address
    a = public_site_address(request_base_url="http://127.0.0.1:8010/", workspace_id="ws1", slug="site", handle="acme")
    assert a.page_url("/") == "https://acme.pages.cluehq.ai/site"
    assert a.page_url("/pricing") == "https://acme.pages.cluehq.ai/site/pricing"
    assert public_site_address(request_base_url="http://x/", workspace_id="ws1", slug="s", handle=None).origin == "http://x"
```

- [ ] **Step 2: Run** → ImportError.
- [ ] **Step 3: Implement**; thread through the publish route, the batch, the publish-state read (handle lookup lands in Task 14 — until then pass `handle=None`, which is the interim path; leave a one-line `# F5 T14 supplies the handle` marker). Add the two env keys to all three env files with a comment block ("blank = interim path routing; set to the wildcard host suffix once DNS + TLS exist").
- [ ] **Step 4: Run** the new test + `test_web_export.py` → green.
- [ ] **Step 5: Commit** — `git commit -m "feat(design-api): PublicSiteAddress — config-sourced public origin, interim path fallback, absolute publish URLs"`

---

## Lane F5.3 — Shell publish wiring + default domain

### Task 13: The platform shell's Publish is real

**Files:**
- Create: `apps/frontend/src/features/design-editor/data/web-publish.repository.ts` (+ `.test.ts`)
- Modify: `apps/frontend/src/features/design-editor/engine/webDocuments.ts:1861-2030` (`fetchWebPublishInfo` parses `pages`/`page_urls`; `publishWebDocument(options, documentId, slug?, { noindex?: boolean })`)
- Modify: `apps/frontend/src/features/chat-shell/hooks/use-artifact-sharing-controller.ts` (whole file — see interface), `components/artifact-header.tsx:120-130` (pass `documentId`), `components/artifact-stage.tsx:290, :312` (header already receives `activeDocumentId` nearby — pass it to the header)
- Modify: `subsystems/clue-design/apps/api/lumen_api/models.py:259` (`WebPublishRequest.noindex: bool = False`) and `main.py:4317` (pass `noindex=payload.noindex`)
- Test: `apps/frontend/src/features/chat-shell/hooks/use-artifact-sharing-controller.test.ts` (node test runner; test the controller's pure reducer/effects by extracting a `publishTransition` helper, the pattern `use-chat-session-menu-controller.test.ts` uses)

**Interfaces:**
```ts
export interface WebPublishRepository {
  state(documentId: string): Promise<WebPublishState>;             // GET /documents/{id}/web/publish via BFF
  publish(documentId: string, input: { slug: string; noindex: boolean }): Promise<WebPublishResult>;
  unpublish(slug: string): Promise<void>;                           // DELETE /web/publishes/{slug}
}
export function createFixtureWebPublishRepository(): WebPublishRepository;   // in-memory, for tests/fixture mode
export function createHttpWebPublishRepository(config: DesignEditorConfig): WebPublishRepository; // uses designBffConfig()
```
- `useArtifactSharingController({ kind, title, documentId, repository })`:
  - on menu open: `repository.state(documentId)` → `publishStatus` = `published` when `state.published && state.status === "active"`, `slug` = server slug when published, `shareUrl` = `state.url` (absolute, from Task 12). `SHARE_HOST` is DELETED.
  - `publishAsset`: `publishing` → `repository.publish(documentId, { slug, noindex: !allowIndexing })` → on success `published`, `shareUrl` = result url, `statusMessage = "Published"`; on failure `draft` + the server message. No timers.
  - `saveSlug` no longer flips status by itself; it marks `slugDirty` so the button reads "Republish".
  - The `clue:artifact-publish-request` window event stays (integration hook) but fires AFTER the real call.
  - `description`, `customHtml`, `regenerateDescriptionOnPublish` stay as designed controls but are NOT sent (the backend derives the description) — mark in code `// FLAGGED F5: designed field, no backend contract yet`.
- `allowIndexing` default: `true` for ordinary sites; the server ORs the durable ABM `noindex`, so the toggle can never un-noindex an ABM page (R-F1).
- Non-web artifacts (`kind !== "web"`): the controller keeps today's inert behaviour (no repository call) — scene publish is not in F5.

- [ ] **Step 1: Failing test** (pure transition helper exported from the hook module):

```ts
import test from "node:test";
import assert from "node:assert/strict";
import { publishWithRepository } from "./use-artifact-sharing-controller";
import { createFixtureWebPublishRepository } from "../../design-editor/data/web-publish.repository";

test("publishWithRepository publishes the slug and returns the server url", async () => {
  const repo = createFixtureWebPublishRepository();
  const outcome = await publishWithRepository(repo, "doc_1", { slug: "openai-cfo", noindex: false });
  assert.equal(outcome.status, "published");
  assert.match(outcome.url, /\/openai-cfo$/);
  const state = await repo.state("doc_1");
  assert.equal(state.published, true);
});

test("a failing publish reports draft with the message", async () => {
  const repo = createFixtureWebPublishRepository();
  const outcome = await publishWithRepository({ ...repo, publish: async () => { throw new Error("slug taken"); } }, "doc_1", { slug: "x", noindex: false });
  assert.equal(outcome.status, "draft");
  assert.equal(outcome.message, "slug taken");
});
```

- [ ] **Step 2: Run** → module missing.
- [ ] **Step 3: Implement** repository (fixture + HTTP), `publishWithRepository`, rewire the hook, thread `documentId` from `artifact-stage.tsx` through `artifact-header.tsx`, add `noindex` to the design API request model.
- [ ] **Step 4: Run** `npm test`, then `npm run design-system:build && npm run lint && npm run build`. Browser check on the dev stack (start ONLY via `DEV_STACK.md` / `scripts/dev_stack.sh`; frontend on :3020): open a web artifact → Share → Publish → the menu shows the served URL → the URL opens the page → a second page's route opens too.
- [ ] **Step 5: Commit** — `git commit -m "feat(frontend): Publish in the artifact share menu is real — repository seam over the design API, server url, no fake timer"`

---

### Task 14: Workspace handle (R-F5-5 default)

**Files:**
- Create: `alembic/versions/<hash>_design_workspace_handle.py`
- Create: `subsystems/design/clue_design/workspace_handles.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/design_store.py` (facade: `get_workspace_handle()`, `ensure_workspace_handle(default_from: str)`, `set_workspace_handle(handle)`, `lock_workspace_handle()`), `main.py` (routes + hook at publish)
- Test: `tests/design/test_workspace_handle_dal_db.py`, `apps/api/tests/test_workspace_handle.py`

**Schema:**
```sql
CREATE TABLE design_workspace_handle (
    workspace_id text NOT NULL PRIMARY KEY REFERENCES workspace (workspace_id),
    handle       text NOT NULL,
    locked_at    timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT design_workspace_handle_unique UNIQUE (handle),
    CONSTRAINT design_workspace_handle_shape CHECK (handle ~ '^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$')
);
```
(The shape is a DNS label: 3–63 chars, lowercase alnum + inner dashes — it is a hostname segment.) Reserved handles refused in the DAL: `www`, `app`, `api`, `admin`, `pages`, `static`, `assets`, `mail`.

**DAL / routes:**
- `ensure_workspace_handle(conn, *, workspace_id, default_from) -> JsonObject` — returns the row; creates it when absent from `web_slugify(default_from)` clamped to the label shape, appending `-<last 4 of workspace_id>` on UNIQUE conflict (retry once).
- `set_workspace_handle(conn, *, workspace_id, handle)` — refuses when `locked_at IS NOT NULL` (`ValueError("handle_locked")` → HTTP 409 `workspace_handle.locked`), refuses reserved/ill-shaped (422 `workspace_handle.invalid`), UNIQUE conflict → 409 `workspace_handle.taken`.
- `lock_workspace_handle(conn, *, workspace_id)` — sets `locked_at = now()` if null. Called from `_publish_web` (`main.py:4260`) on every successful publish (idempotent).
- Routes: `GET /workspace/handle` → `{handle, locked, public_host}` (`public_host` = `f"{handle}.{suffix}"` or `null` in interim mode; the default is derived from the platform `workspace.name`, read via `SELECT name FROM workspace WHERE workspace_id=:w` in the DAL); `PUT /workspace/handle {handle}`.
- `public_site_address(...)` (Task 12) receives `handle` from `repo.ensure_workspace_handle(...)["handle"]` in the publish route, the batch, and the publish-state read.

- [ ] **Step 1: Failing tests** — DAL: ensure derives from name, `set` works, `lock` then `set` raises `handle_locked`, reserved `www` refused, UNIQUE conflict yields the suffixed default. API: `GET /workspace/handle` returns a handle for a fresh workspace; `PUT` changes it; publish locks it; `PUT` after publish → 409.
- [ ] **Step 2: Run** → red.
- [ ] **Step 3: Implement** (migration off the Task 10 head; `make db-smoke` on a throwaway DB; one head).
- [ ] **Step 4: Run** both test files → green.
- [ ] **Step 5: Commit** — `git commit -m "feat(design): workspace handle — DNS-label shaped, derived from the workspace name, locked at first publish (R-F5-5 default)"`

---

### Task 15: Host-matched public serving (`{handle}.pages.cluehq.ai`)

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/public_pages.py`
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` — mount at app build (near `app.add_middleware` `:704`), reuse `_serve_site_page` (Task 11) and the `p-assets`/`asset-store` handlers
- Modify: `.env.example` files (already carry the two keys from Task 12; add the DNS/TLS operator note), `DEV_STACK.md` (a "public pages host" row)
- Test: `apps/api/tests/test_public_pages_host.py`

**Interfaces:**
- `build_public_pages_app(*, resolve_workspace_for_handle, serve_site_page, serve_publish_asset, serve_asset_store) -> FastAPI` — a sub-app with routes:
  - `GET /{slug}` → site page `/`
  - `GET /{slug}/manifest.json` → manifest (declare before the catch-all)
  - `GET /{slug}/{route:path}` → site page `/{route}`
  - `GET /p-assets/{asset_name}` and `GET /asset-store/{digest}` → the existing handlers (published HTML references both root-relatively, so they must resolve on the public host)
  - The handle comes from `request.path_params["handle"]` (Starlette `Host` fills it); unknown handle → 404 page.
- Mount: `if suffix := os.environ.get("LUMEN_PUBLIC_PAGES_HOST_SUFFIX"): app.router.routes.insert(0, Host(f"{{handle}}.{suffix}", app=build_public_pages_app(...)))` (`from starlette.routing import Host`). Inserted FIRST so the host match wins over the path routes for those hosts; all other hosts fall through unchanged.
- `resolve_workspace_for_handle(handle) -> str | None` = DAL `get_workspace_by_handle` (add to `workspace_handles.py`). Resolution is a single indexed lookup on `design_workspace_handle.handle` — the seam a `design_custom_domain(host PK, workspace_id, verified_at)` table plugs into later: the resolver becomes "handle table, then custom-domain table"; nothing else changes. Write that sentence as the module docstring.
- CSP: `_delivery_csp(base)` receives the public origin (`site_address.origin`).
- **Infra (operator steps, outside the code, listed in DEV_STACK.md and the close-out):** wildcard DNS `*.pages.cluehq.ai` → the design API's public ingress; wildcard TLS (Cloudflare proxy or the ingress's ACME wildcard); the design API is today reached through a tunnel on 8060 per `_memory/2026-08-27-railway-frontend-deployment.md` — a public ingress for it is a prerequisite the founder owns. Until then `LUMEN_PUBLIC_PAGES_HOST_SUFFIX` stays blank and the interim path serves.

- [ ] **Step 1: Failing test**

```python
def test_public_host_serves_the_site_by_handle(client, workspace_id, monkeypatch):
    # client fixture builds the app; rebuild with the suffix set, or set the env BEFORE the fixture (module-scoped) —
    # follow conftest's app-construction hook for env-dependent tests.
    handle = client.get("/workspace/handle").json()["handle"]
    document = create_web_document(client)
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    client.post(f"/documents/{document['id']}/web/publish", json={"slug": "site"})
    public = TestClient(client.app, base_url=f"https://{handle}.pages.test")
    assert public.get("/site").status_code == 200
    assert public.get("/site/manifest.json").status_code == 200
    assert public.get("/nope").status_code == 404
    stranger = TestClient(client.app, base_url="https://nobody.pages.test")
    assert stranger.get("/site").status_code == 404
```

(with `LUMEN_PUBLIC_PAGES_HOST_SUFFIX=pages.test` set for the app under test.)

- [ ] **Step 2: Run** → 404 on the public host.
- [ ] **Step 3: Implement**; also assert the published HTML's canonical is `https://{handle}.pages.test/site` in host mode (Task 12 wiring).
- [ ] **Step 4: Run** the test + `test_web_export.py` + `test_asset_store_serving.py` → green.
- [ ] **Step 5: Commit** — `git commit -m "feat(design-api): Host-matched public pages app — {handle}.<suffix>/{slug}{route}; handle resolver is the custom-domain seam"`

---

### Task 16: The shell shows the real address everywhere

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/hooks/use-artifact-sharing-controller.ts` (copy-link uses `shareUrl` from state), `components/artifact-share-menu.tsx` (the URL row renders `shareUrl`; if `state.pages.length > 1` the advanced "page" tab lists each route with its `page_urls[route]`)
- Test: extend the Task 13 test file.

- [ ] **Step 1: Failing test** — controller state after `state()` on a two-page fixture exposes `pageUrls` with both routes.
- [ ] **Step 2–4:** implement, `npm test`, lint/build.
- [ ] **Step 5: Commit** — `git commit -m "feat(frontend): share menu shows the served site url and every page's route"`

---

## Lane F5.5 — Route editor + page switcher (platform shell, then dev-shell parity)

### Task 17: TypeScript op builders for pages

**Files:**
- Modify: `apps/frontend/src/features/design-editor/engine/webDocuments.ts:704` (`WebOperation` union), `:741-770` (builders)
- Test: `apps/frontend/src/features/design-editor/engine/webDocuments.test.ts`

**Interfaces:**
```ts
export function setPageMetaOp(pageId: string, meta: { name?: string; route?: string }): WebOperation; // kind "set_page_meta"
export function addPageOp(page: { id: string; name: string; route: string }, index?: number): WebOperation; // builds root `root_<id>`
export function removePageOp(pageId: string): WebOperation;
export function routeIsValid(route: string): boolean; // exact mirror of Task 1's grammar (same regex + reserved rule)
```

- [ ] **Step 1: Failing tests** — `setPageMetaOp("home", { route: "/x" })` serializes to `{kind:"set_page_meta", page_id:"home", route:"/x"}` (no `name` key); `addPageOp` produces `page.nodes[root_pricing]` with `kind:"container"`; `routeIsValid` mirrors the Rust cases from Task 1 (copy the same good/bad lists).
- [ ] **Step 2–4:** run, implement, run.
- [ ] **Step 5: Commit** — `git commit -m "feat(frontend): page operation builders + the route grammar mirror"`

---

### Task 18: Page switcher in the artifact header (FLAGGED slot)

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/artifact-stage.tsx:225-270` (own `activePageId` next to `previewDevice`; pass to `WebArtifactCanvas pageId` and to the header), `components/artifact-header.tsx` (a `pages` + `activePageId` + `onPageChange` trio, rendered ONLY for `kind === "web"` with ≥1 page — the same lift pattern as `device`/`onDeviceChange` from 2026-09-01), `hooks/use-artifact-toolbar-controller.ts` (liftable page state like `device`)
- Test: `apps/frontend/src/features/chat-shell/hooks/use-artifact-toolbar-controller.test.ts` (extend the device-lift test)

**Rules:**
- The pages list comes from the loaded web document (`LoadedWebDocument.webDoc.pages` via `use-scene-document`'s web branch); when the document reloads and the active page no longer exists, fall back to the first page.
- Visual: a plain `<select>`-style menu identical in styling to the device menu, labelled by page `name` with the route in a muted suffix. Code comment: `// FLAGGED F5 T18: no designed slot in the dummy frontend for a page switcher — minimal neutral control pending founder/design ruling.`
- No add/remove here (Task 19 owns them in the inspector).

- [ ] **Step 1: Failing test** — controller with `pages=[home, pricing]` and `onPageChange` spy: selecting `pricing` calls the spy; uncontrolled fallback keeps local state.
- [ ] **Step 2–4:** run red, implement, `npm test`, lint/build, browser check: switching pages re-renders the canvas with the other page.
- [ ] **Step 5: Commit** — `git commit -m "feat(frontend): page switcher drives the web canvas page (flagged neutral control)"`

---

### Task 19: Route editor + add/remove page in the web inspector (FLAGGED slot)

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/web-inspector.tsx` (a `PageSection` rendered when no node is selected: page name field, route field with inline validation via `routeIsValid`, "Add page" (id derived from the name, route from the name via `slugifyArtifactTitle`-style slug → `/<slug>`), "Remove page" disabled when it is the only page or is the active `/` page)
- Modify: `apps/frontend/src/features/design-editor/hooks/use-inspector-writes.ts` (expose `setPageMeta(pageId, meta)`, `addPage(page)`, `removePage(pageId)` — each a one-op `applyOps` with intents `"rename_route"`, `"add_page"`, `"remove_page"`)
- Test: `apps/frontend/src/features/chat-shell/components/inspector-field-draft.test.ts` pattern — test the route field's draft/commit rules: commit on blur/Enter only when `routeIsValid`, refuse with the same sentence the agent tool uses.

**Rules:**
- Route field commits `setPageMetaOp(pageId, { route })`; a 422 from the server (duplicate route) surfaces as the field's error text; the doc reload after apply refreshes the switcher (Task 18).
- After `addPage`, set the stage's `activePageId` to the new page (the inspector calls `onPageChange`).
- Code comment flag as in Task 18.

- [ ] **Step 1: Failing test** (draft rules) → **Step 2–4** implement, tests, lint/build, browser check: rename `/pricing` → `/plans`, publish, the served URL follows.
- [ ] **Step 5: Commit** — `git commit -m "feat(frontend): page section in the web inspector — route editor, add/remove page (flagged neutral controls)"`

---

### Task 20: In-editor navigation between pages

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/web_bridge.py:375-390` (the anchor click handler that `preventDefault`s): when the anchor's `href` equals a document route (the bridge script receives `routes: {route: page_id}` from `_bridge_page_capabilities`), post `{type: "lumen:navigate", pageId}` to the parent
- Modify: `apps/frontend/src/features/design-editor/components/web-artifact-canvas.tsx` (message listener validates the nonce like the selection listener does, then calls `onNavigate(pageId)`), `artifact-stage.tsx` (sets `activePageId`)
- Test: `apps/api/tests/test_web_bridge.py` (if absent, add beside the bridge tests in `test_web_documents.py`): the bridge script text contains the routes map; frontend: the listener ignores a message with the wrong nonce.

- [ ] **Steps:** red → green → commit `git commit -m "feat(design): clicking a site link in the editor switches the active page"`

---

### Task 21: Dev-shell parity (subsystem editor)

**Files:**
- Modify: `subsystems/clue-design/apps/editor/src/components/web/WebEditorApp.tsx:151-180` (an `activePageId` state replacing `defaultPageId`'s first-page fallback for the render fetch; a page `<select>` in the existing top bar), `WebInspectorPanel.tsx:100-125` (route field on the page card), `apps/editor/src/engine/webDocuments.ts:743` (the same builders as Task 17 — copy verbatim; the two editor copies are maintained in parallel by repo precedent)
- Test: `apps/editor/src/components/web/__tests__/` (vitest) — builder serialization + route validation.

- [ ] **Steps:** red → green → `npm test` in `apps/editor` → commit `git commit -m "feat(editor): dev shell page switcher + route field (parity with the platform shell)"`

---

## Close

### Task 22: CP3 acceptance walk, docs, memory

**Walk (live, dev stack per `DEV_STACK.md`, istanbul DB; no seeded fixtures; fixes are analysed, not defended):**
1. In a project chat, ask for a **three-page ABM microsite** for one real target account (landing `/`, `/pricing-for-<account>`, `/security`), site-internal nav in the campaign header, one CTA.
2. Watch the run: pages created first; one author delegation per page; `render_web_preview` per page; the review gate per page; finalize lists three pages.
3. In the shell: switch pages; rename one route in the inspector; click a site link in the canvas → page switches.
4. Share → Publish. The URL opens; every route serves; site links resolve; every page carries `noindex`; unpublish takes all pages down; rollback restores the previous set.
5. If `LUMEN_PUBLIC_PAGES_HOST_SUFFIX` + DNS exist on the host: repeat step 4 on `{handle}.pages.cluehq.ai`; otherwise record the interim URL and the infra prerequisite as OPEN.
6. Export ZIP: `index.html` + `<route>/index.html` present.

**Records:** master plan status header (F5 CLOSED / open items), `_memory/2026-09-0X-f5-close.md` (verification commands + results, defects found, founder queue: R-F5-5 confirmation, the two FLAGGED UI slots, description/customHtml backend contract, custom-domain follow-on), `DEV_STACK.md` public-host row, `apps/frontend/docs/api-contracts/` note for the publish contract (per the frontend charter: resolved contract decisions are written back).

- [ ] Commit — `git commit -m "docs(design): F5 close-out — CP3 walk record, open items, publish contract note"`

---

## Self-review against the spec

- **R-F5-1 URL shape** → T12 (address), T14 (handle), T15 (host app). **R-F5-2 site publish** → T10/T11 (all pages under one slug; one revision). **R-F5-3 slug/route** → T11 (route `/` at the bare slug), T13 (dialog slug = site slug). **R-F5-4 indexing** → T11 (noindex on every page), T13 (toggle; server ORs the durable flag). **R-F5-5 handle default** → T14 (derive, edit until lock, lock at publish). **R-F5-6 microsite target** → T8 prompt law + T22 walk. **R-F5-7 no capture** → no capture task exists; T8 skill text says pages come from the library + composed sections. **R-F5-8 links free** → T9 (gates advisory), T8 (guidance text), T11 (link rewrite touches only routes; nothing refused).
- **Six lanes:** F5.0 T1–T3; F5.1 T4–T5; F5.2 T10–T12; F5.3 T13–T16; F5.4 T6–T9; F5.5 T17–T21. Custom domains: T15 docstring names the seam; no task builds it (deferred by ruling).
- **Type consistency:** `resolve_web_page_id` (T4) used by T11 only for the fallback; `web_doc_all_fragment_ids` (T7) used by T11; `PublicSiteAddress.page_url(route)` (T12) used by T13's server payload (`url`, `page_urls`) and T15's canonical; `routeIsValid` (T17) used by T19; `WebPublishRepository.state/publish/unpublish` (T13) used by T16; `addPageOp/removePageOp/setPageMetaOp` (T17) used by T19 and T21; tool names `list_pages/add_page/remove_page/switch_page` (T6) used by T8.
- **Placeholders:** none intended; every code step carries its code. Where a real key name could not be confirmed from the tree (T3's operations response keys), the step says to read the route and adjust the TEST, never the route.
