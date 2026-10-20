# Custom-domain publishing × F5 multipage — reconciliation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Task 0 (the merge) is run by the controller in the shared tree, not by a subagent.**

**Goal:** Merge `origin/codex/ai-ark-committee-discovery-spec-v1` into `website/custom-domain` so that ONE
hosting design survives: the S1/S2 `workspace_hostname` registry and the deployable `clue_page_origin`
service (with custom domains), extended with F5's multi-page routes (`/{slug}{route}`) and F5's rule that
the workspace label locks at the first publish; F5's `design_workspace_handle` table and the Host-routed
app inside the design API are removed and existing handles become our labels.

**Architecture:** The merge commit takes the other branch wholesale for everything it owns (the settings
slice, the F5 design API with multipage, the real-publish share menu, 44 migrations) and keeps ours for
everything only we own (spine registry, page origin, control plane, Worker, runbook). Six follow-up tasks
then re-apply our design onto F5's code: an Alembic join + one migration (lock column, handle backfill,
handle table drop), the design API re-homed on the registry (address = system origin, no interim routes,
no handle endpoints, lock at first publish), the page origin gaining per-route serving, the share menu and
Settings → Pages rebound onto the settings slice's shell, env/docs, and the exit gate.

**Tech Stack:** unchanged (Python 3.12 / FastAPI / SQLAlchemy / Alembic; Next.js / Zod 4 / node --test).

**Spec:** `docs/superpowers/specs/archive/2026-09-17-custom-domain-publishing-design.md` (binding for our side) +
the founder ruling of 2026-09-28 recorded in `_memory/2026-09-28-custom-domain-f5-reconciliation.md`
(Task 5 writes it) and the memory `custom-domain-vs-f5-handle-ruling`. F5's own record:
`_memory/2026-09-03-f5-multipage-build-close.md` on the other branch (present after the merge).

## Global Constraints

- **Ruling 2026-09-28 (founder):** ours for storage (`workspace_hostname`) and serving (`clue_page_origin`
  behind the Worker); adopt F5's multi-page routes and lock-at-first-publish; remove `design_workspace_handle`,
  `lumen_api/public_address.py`, the Host app in `lumen_api/public_pages.py`, `GET/PUT /workspace/handle`,
  `LUMEN_PUBLIC_PAGES_HOST_SUFFIX` / `LUMEN_PUBLIC_PAGES_SCHEME`; handles become labels. This supersedes
  spec assumption A1 (label change with warning): after the first publish the label is **locked**.
- Spec A6 stands: published HTML carries no `canonical` and no `og:url` (pages are `noindex`); F5's per-page
  canonical assertions are updated, not restored. `og:image` remains the one absolute URL, on the system origin.
- One Alembic head after the join; `make db-smoke` only on a scratch DB. The join revision is created with
  `alembic merge`, never hand-numbered. Our `aaff3d831895` and their head `97427f8eb3d6` are the two parents.
- Seams unchanged: `clue_spine` imports only core+db(+tldextract); `clue_design` never imports `clue_spine`;
  the page origin never imports `lumen_api`/`clue_api`; `lumen_api` imports `clue_spine` but never `clue_api`.
- Env parity: `.env.example` and `.env` at key parity; `LUMEN_PUBLIC_PAGES_*` removed from both; every
  `CLUE_PAGES_*` / `CLUE_CLOUDFLARE_*` key kept.
- Commits: plain messages, no AI attribution trailer, never push, never bare `git stash`. The merge commit
  is one commit; each task is one commit.
- Test rules as in the S2 plan (source `.env`; lane DB only — **note the lane DB `clue_addis-ababa` no
  longer exists on :55040; Task 0 recreates it empty and migrates it**; design API suites from
  `subsystems/clue-design/apps/api` with the env sourced; `-k` once per invocation; never the full design
  suite inline; frontend `npm test && npm run lint`, build only with port 3020 free).
- Gates: `uv run ruff format/check` on touched Python, `uv run mypy` (baseline: re-measure on the merged
  tree in Task 0 and record it in the ledger), `uv run lint-imports` (re-measure the kept count).

---

## Decisions this plan makes beyond the ruling (flagged; reversible)

1. **Lock lives on `workspace_hostname` as `locked_at timestamptz`**, set by the design API at first publish
   through a spine DAL (`lock_system_hostname`), mirroring F5's nullable-timestamp design (auditable unlock).
   The spine never reads design tables.
2. **The merge commit takes THEIR design API and share menu wholesale**; our S1/S2 changes to those files
   are re-applied by Tasks 2 and 4 from this plan's exact rules. This keeps the merge commit compiling and
   puts the hard reconciliation in reviewable tasks. Our `lumen_api/public_pages.py` (registry URL helpers)
   is therefore recreated by Task 2 under the same name once their host app at that path is deleted.
3. **`PublicSiteAddress` survives; `public_site_address()` does not.** The dataclass is F5's one answer to
   "where is this site"; Task 2 builds it from the registry (`origin = system origin, site_path = /{slug},
   asset_origin = origin, host_mode = True`) and deletes the env-driven interim-mode constructor.
4. **Custom hostnames get `custom_page_urls`** alongside `page_urls` on the publish responses (one map per
   origin) so the share menu can show per-route links on the customer domain without client-side URL
   building (R-F5-1 in spirit).
5. **Settings → Pages plugs into their `readSettingsSection` seam** (a new `"pages"` case) rather than a
   parallel loader, so the recovery screen and the shell's section switch stay theirs.
6. **Autosave convergence:** if the settings slice ships an input built on `useAutosaveField`, Pages uses
   it and our `SettingsAutosaveInput` is deleted; otherwise ours stays. Task 4 decides and records which.
7. **`.context/attachments` stays tracked** as their branch made it; our untracked copies are restored
   only where a path is absent after the merge.

---

### Task 0 (controller): the merge

**Pre-flight**
- [ ] `git rev-parse --short HEAD` = `8ab2780d4`; tree clean; `git fetch origin`.
- [ ] `mv .context/attachments /tmp/addis-attachments-backup` (the other branch tracks the same paths).
- [ ] Recreate the lane DB: `createdb -h localhost -p 55040 -U clue clue_addis-ababa` (password from
  `.env`), confirm `.env` `CLUE_DATABASE_URL` names it. Migration to head happens after the join (Task 1).
- [ ] `git merge --no-ff origin/codex/ai-ark-committee-discovery-spec-v1` → 43 conflicts.

**Resolution table** (`T` = take theirs verbatim; `O` = take ours; `U` = union by hand)

| File | Rule | Notes |
| --- | --- | --- |
| `.env.example` | U | their block + our `CLUE_PAGES_*` + `CLUE_CLOUDFLARE_*`; delete `LUMEN_PUBLIC_PAGES_HOST_SUFFIX` / `LUMEN_PUBLIC_PAGES_SCHEME` and their comment block. Mirror `.env`. |
| `DEV_STACK.md` | U | theirs + our 8040 row; drop their `LUMEN_PUBLIC_PAGES_*` paragraph/table rows. |
| `Makefile` | U | theirs + our `pages-backfill-hostnames` target. |
| `_memory/README.md` | U | both topic-note lines. |
| `apps/frontend/docs/api-contracts/settings.md` | U | theirs + our Pages section appended (heading "Pages"). |
| `apps/frontend/src/app/(protected)/settings/[[...section]]/page.tsx` | T | Task 4 rebinds Pages. |
| `apps/frontend/src/components/ui/confirmation-card.tsx` | T | their API `(message, error?)`. |
| `apps/frontend/src/features/accounts/data/frontend-mutation.ts` | T | they have `fetchMutationVoid`; Task 4 switches `removeCustomHostname` to it. |
| `apps/frontend/src/features/chat-shell/{components/artifact-header,components/artifact-share-menu,components/artifact-stage}.tsx`, `hooks/use-artifact-sharing-controller.ts` | T | Task 4 adds the custom-URL fields. |
| `apps/frontend/src/features/settings/components/*` (11 lifted files), `config/settings-navigation.ts`, `model/settings.ts`, `components/settings.module.css` | T | their slice owns the shell. Keep OUR new files (`custom-domain-card.tsx`, `pages-settings.tsx`, `settings-autosave-input.tsx`, `hooks/use-pages-settings.ts`, `model/pages*.ts`, `data/pages.*`) — `pages-settings.tsx` is add/add: take **ours**. Delete our `data/settings.fixture.ts` + `data/settings.repository.ts` only if theirs has no file at those paths (check; theirs uses `data/static-sections.ts` + `settings-read.ts`). |
| `libs/clue-config/clue_config/secrets.py` | U | both field blocks. |
| `libs/clue-spine/clue_spine/__init__.py` | U | both export sets (theirs adds `ProjectKind`, `UNTITLED_PROJECT_NAME`, …; ours adds the hostname/pages-settings names). |
| `platform/api/clue_api/auth_wiring.py` | U | theirs + our `pages_system_suffix` parameter thread (`build_auth_router` / `install_auth_wiring` / the provision call). |
| `platform/api/clue_api/frontend_read/app.py` | U | theirs + our `register_settings_pages_routes(...)` call after `register_artifact_routes` and our `retryable` envelope change (`error_envelope` / `_envelope_parts` / handler). |
| `platform/api/clue_api/projections_app.py` | U | theirs + our `pages_system_suffix=resolved.pages_system_suffix` on `install_auth_wiring`. |
| `platform/auth/clue_auth/policy.py` | T | already revision 3 with `manage_settings`. |
| `platform/auth/clue_auth/provisioning.py` | U | theirs + our `pages_system_suffix` parameter on both provisioners and their `create_workspace(...)` calls. |
| `pyproject.toml` | U | theirs + our ruff first-party `clue_page_origin`, mypy `files`/`mypy_path` entries, importlinter root package + contract. |
| `scripts/dev_stack.sh` | U | theirs + our `CLUE_PAGES_*` PLATFORM_ENV lines, `start_page_origin`, its `up`/`down`/`restart-api`/`status` hooks. |
| `subsystems/clue-design/apps/api/lumen_api/{main.py, public_pages.py, toolbelt/publishes.py, web_export.py}` | T | Task 2 re-applies ours. |
| `subsystems/clue-design/apps/api/pyproject.toml` | U | theirs + our `clue-spine`, `clue-config` deps/sources. |
| `subsystems/clue-design/apps/api/tests/{test_abm_batch_publish,test_web_batches,test_web_export,test_workspace_seam_route_table}.py` | T | Task 2 rewrites the `/w/` GETs. Our `tests/conftest.py` helpers (`published_html` …) — non-conflicting, keep. |
| `uv.lock` | T then `uv sync --all-packages` | regenerates with our packages. |

- [ ] After resolving: `uv sync --all-packages`; `python -c "import clue_api.projections_main"` under the env;
  `cd apps/frontend && npm install && npm run lint` (build check deferred to Task 4).
- [ ] Restore attachments: `cp -Rn /tmp/addis-attachments-backup/. .context/attachments/`.
- [ ] Commit: `merge: codex/ai-ark-committee-discovery-spec-v1 into website/custom-domain (F5 multipage + settings slice; hosting reconciliation follows)`.
- [ ] Record in the ledger: the merged mypy baseline count, the lint-imports kept count, and
  `uv run alembic heads` (expected: two heads until Task 1).

---

### Task 1: Alembic join; `locked_at` on the registry; handles → labels; drop `design_workspace_handle`

**Files:**
- Create: `alembic/versions/<join>_merge_custom_domain_and_ai_ark.py` (via `alembic merge`), `alembic/versions/<rev>_hostname_lock_and_handle_backfill.py`
- Modify: `libs/clue-spine/clue_spine/hostnames.py` (`WorkspaceHostname.locked_at`, `lock_system_hostname`, `replace_system_label` refusal), `clue_spine/__init__.py`
- Modify: `subsystems/design/clue_design/workspace_handles.py` → **delete**; `subsystems/design/clue_design/__init__.py` if it re-exports it
- Test: `tests/db/test_hostname_lock_migration_db.py` (new), `tests/clue_spine/test_hostnames_custom_db.py` (extend)

**Interfaces:**
- `lock_system_hostname(conn, *, workspace_id: str) -> WorkspaceHostname` (idempotent; sets `locked_at = now()` once).
- `replace_system_label` raises `HostnameRefused("label_locked", …)` when `locked_at IS NOT NULL`.
- `WorkspaceHostname.locked_at: UtcDatetime | None`.

- [ ] **Step 1: Join.** `uv run alembic merge -m "merge custom-domain and ai-ark lineages" aaff3d831895 97427f8eb3d6`; `uv run alembic heads` → one head.

- [ ] **Step 2: Write the failing tests**

```python
# tests/clue_spine/test_hostnames_custom_db.py (append)
def test_label_locks_at_first_publish() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(conn, name="Lock " + uuid4().hex[:4], pages_system_suffix=SUFFIX)
            first = await lock_system_hostname(conn, workspace_id=ws.workspace_id)
            assert first.locked_at is not None
            again = await lock_system_hostname(conn, workspace_id=ws.workspace_id)
            assert again.locked_at == first.locked_at  # idempotent, never moves forward
            with pytest.raises(HostnameRefused) as caught:
                await replace_system_label(conn, workspace_id=ws.workspace_id, label="acme-new-" + uuid4().hex[:4], suffix=SUFFIX)
            assert caught.value.code == "label_locked"

    run_async(scenario())
```

```python
# tests/db/test_hostname_lock_migration_db.py
"""The handle → label backfill (ruling 2026-09-28): a workspace's F5 handle becomes its system label."""

from __future__ import annotations

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text

from tests.clue_spine.conftest import _alembic_config, rollback_conn, run_async  # noqa: F401
from tests.clue_spine.conftest import migrated_db, require_spine_db  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_spine_db")
LOCK_REV = "<rev>"  # the backfill revision id, filled in by the implementer


def test_handle_becomes_label_and_lock_carries_over() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            # The table must be gone at head …
            exists = (await conn.execute(text("SELECT to_regclass('design_workspace_handle')"))).scalar()
            assert exists is None
            # … and the registry has the lock column.
            cols = (await conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'workspace_hostname'"
            ))).scalars().all()
            assert "locked_at" in cols

    run_async(scenario())
```

The up/down/up smoke (`make db-smoke` on a scratch DB seeded with one `design_workspace_handle` row before
the backfill revision) is the executable proof of the backfill itself: seed at `<join>`, upgrade to head,
assert the `workspace_hostname` system row carries the handle as label and the same `locked_at`, downgrade
one step, assert the handle row is back. Script it in the test as a second function using
`command.upgrade(cfg, "<join>")`, raw inserts, `command.upgrade(cfg, "head")`, asserts, `command.downgrade(cfg, "-1")`
— run only when `CLUE_DATABASE_URL` names a scratch DB (`assert "smoke" in url`), else skip.

- [ ] **Step 3: Migration** (`uv run alembic revision -m "hostname lock and handle backfill"`):

```python
def upgrade() -> None:
    op.execute("ALTER TABLE workspace_hostname ADD COLUMN locked_at timestamptz")
    # Existing F5 handles become system labels (ruling 2026-09-28). A workspace that already has a
    # system row keeps it (S1 allocated from the workspace name); its handle row is dropped unread —
    # the two were derived from the same name and the S1 row is the one publish URLs were minted from.
    op.execute(
        """
        INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, activated_at, locked_at)
        SELECT h.handle || '.' || current_setting('clue.pages_system_suffix', true), h.workspace_id,
               'system', 'active', now(), h.locked_at
        FROM design_workspace_handle h
        WHERE current_setting('clue.pages_system_suffix', true) IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM workspace_hostname w WHERE w.workspace_id = h.workspace_id AND w.kind = 'system')
        ON CONFLICT (hostname) DO NOTHING
        """
    )
    op.execute("DROP TABLE design_workspace_handle")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE design_workspace_handle (
            workspace_id text NOT NULL, handle text NOT NULL, locked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT design_workspace_handle_pkey PRIMARY KEY (workspace_id),
            CONSTRAINT design_workspace_handle_handle_key UNIQUE (handle),
            CONSTRAINT design_workspace_handle_workspace_fk FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT design_workspace_handle_shape CHECK (handle ~ '^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$')
        )
        """
    )
    op.execute(
        """
        INSERT INTO design_workspace_handle (workspace_id, handle, locked_at)
        SELECT workspace_id, split_part(hostname, '.', 1), locked_at FROM workspace_hostname
        WHERE kind = 'system' AND locked_at IS NOT NULL
        """
    )
    op.execute("ALTER TABLE workspace_hostname DROP COLUMN locked_at")
```

The suffix reaches SQL as the session setting `clue.pages_system_suffix`: `alembic/env.py` sets it from
`Settings().pages_system_suffix` (`SET clue.pages_system_suffix = :s` right after connecting) — add that
to `env.py`'s online runner; copy the original F5 CREATE TABLE from `5456c0770de8` verbatim into the
downgrade (the shape above is from that file; verify against it).

- [ ] **Step 4: DAL.** In `hostnames.py`: add `locked_at: UtcDatetime | None = None` to `WorkspaceHostname`;
  extend `_ROW` with `locked_at`; add:

```python
async def lock_system_hostname(conn: AsyncConnection, *, workspace_id: str) -> WorkspaceHostname:
    """First publish freezes the label (F5 R-F5-5, adopted 2026-09-28). Idempotent: an already-locked
    row keeps its original ``locked_at``."""
    result = await conn.execute(
        text(
            "UPDATE workspace_hostname SET locked_at = COALESCE(locked_at, now()), updated_at = now() "
            f"WHERE workspace_id = :w AND kind = 'system' RETURNING {_ROW}"
        ),
        {"w": workspace_id},
    )
    row = result.mappings().first()
    if row is None:
        raise HostnameRefused("system_hostname_missing", "run `make pages-backfill-hostnames`")
    return WorkspaceHostname(**dict(row))
```

and in `replace_system_label`, before the delete: read the current row; if `locked_at is not None`, raise
`HostnameRefused("label_locked", "This address has already published a site, so its label is fixed.")`.
Delete `subsystems/design/clue_design/workspace_handles.py` and any re-export. Export `lock_system_hostname`.

- [ ] **Step 5: Run** `tests/clue_spine`, the new DB test, `make db-smoke` on a scratch DB; gates; commit
  `db+spine: alembic join; label lock at first publish; F5 handles become system labels`.

---

### Task 2: Design API re-homed on the registry (their F5 code + our design)

**Files:**
- Delete: `lumen_api/public_address.py`, `lumen_api/public_pages.py` (host app), `tests/test_public_address.py`, `tests/test_public_pages_host.py`, `tests/test_workspace_handle.py`
- Create: `lumen_api/public_pages.py` (ours, from the S2 tree: `system_public_origin`, `custom_public_origin`, `public_publish_url`, `custom_publish_url` — plus `site_address(repository, slug) -> PublicSiteAddress` and `custom_site_address(repository, slug) -> PublicSiteAddress | None`), `lumen_api/public_address.py` reduced to the `PublicSiteAddress` dataclass only (no env, no `public_site_address`)
- Modify: `lumen_api/main.py`, `lumen_api/design_store.py`, `lumen_api/toolbelt/publishes.py`, `lumen_api/web_export.py`, tests listed in the S1 Task 11 rewrite table + `test_web_export.py`'s F5 multipage tests
- Test: `tests/test_public_pages.py` (ours; extend for routes)

**Rules (apply exactly):**
1. `design_store.py`: `_ensure_workspace` calls `ensure_system_hostname` (S2); `HybridRepository` gets
   `system_hostname()`, `active_custom_hostname()`, `pages_defaults()`, `lock_system_hostname()` (bridged
   to the spine DAL); delete the four handle methods and the `workspace_handles` import.
2. `public_address.py`: keep `PublicSiteAddress` (fields + `page_url`, `link_path`); `asset_base` returns
   `self.asset_origin` unconditionally; delete `host_mode`, `HOST_SUFFIX_ENV`, `SCHEME_ENV`, `public_site_address`.
3. `public_pages.py` (ours): `site_address(repo, slug) = PublicSiteAddress(origin=system_public_origin(repo), site_path=f"/{slug}", asset_origin=<same>)`;
   `custom_site_address` likewise over `custom_public_origin` or `None`.
4. `web_export.build_publish_package(..., site_address: PublicSiteAddress, ...)` — required, no `public_base`,
   no `public_site_address` fallback; per page: `_seo_snippet(... og_image=..., canonical=None, og_url=None)`;
   `head += '<link rel="icon" href="/favicon.ico">\n'` once per page; `rewrite_site_links(html, routes, address.link_path)`
   stays (links become `/{slug}{route}`); asset URLs `f"/p-assets/{digest}.{ext}"` (i.e. `asset_prefix = ""`
   semantics — verify `_custom_component_package`'s `asset_url_for` receives a root-relative prefix);
   manifest link `f"{address.site_path}/manifest.json"` (root-relative); `canonical_url` in the manifest =
   `address.page_url("/")`; `og:image` absolute on `address.origin`; the S2 defaults (`default_description`,
   `default_social_preview_sha256`) re-applied. `_delivery_csp(*, meta=False, static_bundle=False)`: base from
   `clue_design.publishes.delivery_csp(meta=meta)`; when `static_bundle`, append ` file:` to the
   `script-src`/`style-src`/`img-src`/`font-src` directives (their zip rule; `'self'` is already present).
5. `toolbelt/publishes.py`: `PublishWebDocumentInput` drops `public_base`; `publish_web_document` builds
   `site_address(repository, slug)`, passes the defaults, and **locks the label** (`repository.lock_system_hostname()`)
   right after the revision is registered (replacing `lock_workspace_handle`).
6. `main.py`: delete the four `/w/` routes, `/p/{slug}` stub, `public_repository`, `public_blob_store`,
   `resolve_workspace_for_handle`, `host_serve_site_page`, the `Host(...)` mount, `workspace_handle_dto`,
   `GET/PUT /workspace/handle`, `SetWorkspaceHandleRequest` (models.py), `publish_site_address`,
   `_serve_site_page` (its body moves to the page origin in Task 3). Publish responses: `url = address.page_url("/")`,
   `custom_url`, `public_origin`, `custom_origin`, `routes`, `pages`, `page_urls`, `custom_page_urls`
   (`{route: custom.page_url(route)}` or `{}`). The batch path uses `site_address(repo, slug)`.
7. Tests: `tests/conftest.py` keeps `published_html`/`published_manifest`/`is_served`; add
   `published_page_html(ws, slug, route)` over `HybridRepository(...).get_web_publish_page(slug, route)`.
   Rewrite every `/w/` GET (their 23 in `test_web_export.py`, plus `test_abm_batch_publish.py`,
   `test_web_batches.py`, `test_custom_component_publish.py`, `test_web_fragment_export.py`,
   `test_workspace_seam*.py`) per the S1 rule table; multipage assertions become: home links carry
   `href="/multi/pricing"`, each page has NO canonical, the manifest link is `/multi/manifest.json`, and
   `page_urls` in the publish response maps `/pricing` to `<system origin>/multi/pricing`. Delete the four
   `/w/` rows from the route table test. Delete the three F5 host/handle test files.
8. `grep -rn "public_base\|public_site_address\|workspace_handle\|LUMEN_PUBLIC_PAGES\|HOST_SUFFIX_ENV" lumen_api tests` → empty.

- [ ] Run: `tests/test_public_pages.py tests/test_web_export.py tests/test_abm_batch_publish.py tests/test_web_batches.py tests/test_web_fragment_export.py tests/test_workspace_seam.py tests/test_workspace_seam_route_table.py tests/test_write_path_governance.py tests/test_design_toolbelt.py tests/test_custom_component_publish.py` — green (the last needs the compiler's `node_modules`; report if absent). Commit `design-api: publish addresses from the hostname registry; multipage routes root-relative; F5 host app and handle endpoints removed`.

---

### Task 3: Page origin serves per-route pages

**Files:**
- Modify: `platform/page_origin/clue_page_origin/reads.py` (`PageReads.active_page(workspace_id, slug, route) -> ServedPage | None`), `routes.py` (`/{slug}/{route:path}`), `tests/page_origin/{conftest,test_routes}.py`

**Interfaces:**
- `ServedPage(html, html_digest, noindex)`; `DbPageReads.active_page` = publish row active AND (`get_web_publish_page` row, or for `/` the publish's own html when no page rows exist — F5's pre-F5 fallback).
- Route `/{slug}/{route:path}` (declared after `/{slug}/manifest.json`, before nothing else): normalises `"/" + route.strip("/")`, serves with `_page_headers`; unknown route on a live site → the fallback URL redirect or 404 exactly like an unknown slug.
- `/{slug}` keeps serving `active_publish` (root), unchanged.

- [ ] Fake: `FakePageReads.publish(slug, html, *, routes: dict[str, str] | None = None)`; tests: pricing route
  served with the same headers; unknown route 404; a site with no page rows serves `/` from the publish html
  and 404s `/anything`; `/{slug}/manifest.json` still wins over the catch-all. Commit
  `page-origin: serve F5 multi-page routes under a slug`.

---

### Task 4: Frontend — share menu custom URLs; Settings → Pages on the settings slice's shell

**Files:**
- Modify: `features/design-editor/engine/webDocuments.ts` (+`customUrl`, `publicOrigin`, `customOrigin`, `customPageUrls` on `WebPublishState`/`WebPublishResult`, mapped with the existing `parseStringMap`), `data/web-publish.repository.ts` (`WebPublishOutcome.customUrl`, `customPageUrls`), `chat-shell/hooks/use-artifact-sharing-controller.ts` (share URL = `customUrl ?? url`; `pageLinkRows(customPageUrls if non-empty else pageUrls)`; `shareHostOf` unchanged), tests in `engine/__tests__/webDocuments.test.ts` + `web-publish.repository.test.ts`
- Modify: `features/settings/data/settings-read.ts` (`case "pages": return { section: "pages", data: await getPagesSettings() } as const`), `app/(protected)/settings/[[...section]]/page.tsx` (`case "pages": content = <PagesSettings initial={result.data} canManage={canManageSettings} />`), `features/settings/data/static-sections.ts` (drop `pages`), delete their dummy Pages usage; `hooks/use-pages-settings.ts` → `useConfirmation()` signature `(message, error?)`; `data/pages.actions.ts` → `removeCustomHostname` uses `fetchMutationVoid`; autosave convergence per decision 6; delete our `data/settings.fixture.ts` / `data/settings.repository.ts` and `components/settings-autosave-input.tsx` if superseded; delete our `components/ui/confirmation-card.tsx` remnants (theirs won in the merge).
- [ ] `npm test && npm run lint`; `npm run build` if port 3020 is free; commit
  `frontend: custom-domain URLs in the share menu; Settings → Pages on the settings slice's shell`.

---

### Task 5: Env, docs, memory

- [ ] `.env.example`/`.env`: `LUMEN_PUBLIC_PAGES_*` gone (Task 0 did it; verify), `CLUE_PAGES_*` intact; `DEV_STACK.md` reflects one serving path (8040) and no host-suffix mode.
- [ ] `docs/specs/pages-hosting-runbook.md`: note that `design_workspace_handle` no longer exists and labels lock at first publish.
- [ ] Spec status header: add the 2026-09-28 reconciliation line; spec §4.1 A1 marked superseded (lock rule).
- [ ] `_memory/2026-09-28-custom-domain-f5-reconciliation.md` (what merged, the seven decisions, rulings, tests run, owed items) + `_memory/README.md` pointer; the S2 note's "merge reconciliation" section marked done.
- [ ] Commit `docs: custom-domain × F5 reconciliation record`.

---

### Task 6: Exit gate

1. `( set -a; source .env; set +a; uv run pytest tests/test_pages_settings.py tests/clue_spine tests/auth tests/page_origin tests/db/test_hostname_lock_migration_db.py tests/api/test_cloudflare_custom_hostnames.py tests/api/test_dns_observe.py tests/api/test_pages_hostname_status.py tests/api/test_frontend_read_settings_pages_db.py tests/api/test_frontend_read_artifacts_db.py -q -p no:warnings --ignore-glob='*_live.py' )` green.
2. Design API: the Task 2 file list green.
3. `uv run ruff format --check <touched> && uv run ruff check <touched> && uv run mypy && uv run lint-imports && uv run alembic heads` (one head; mypy/contract counts at the merged baseline).
4. `cd apps/frontend && npm test && npm run lint && npm run build` (stack stopped).
5. `node --test 'infra/cloudflare/pages-edge/*.test.js'`.
6. Dev-stack walk (founder-triggered): publish a two-page site, open both routes at `http://<label>.pages.localhost:8040/<slug>[/route]`, share menu shows the host + per-page links, `/settings/pages` works, label change refused after publish with the lock message.
