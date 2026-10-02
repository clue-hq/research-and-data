# Custom-domain publishing — S0 (infrastructure) + S1 (system hostnames live) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every workspace gets a permanent `<label>.pages.cluehq.ai` hostname, a new Railway
page-origin service serves published web pages by hostname through the Cloudflare edge, and
publishing becomes host-independent (no `request.base_url` baked into HTML, interim `/w/` routes
deleted). S0 delivers the founder-operated infrastructure runbook and the edge Worker.

**Architecture:** One registry table (`workspace_hostname`, owned by `clue_spine`) maps a public
hostname to a workspace; system rows are allocated idempotently by one function that every
workspace creator calls. A new FastAPI service `clue_page_origin` (in `platform/page_origin/`)
resolves `X-Clue-Public-Host` → workspace → active publish and serves HTML/manifest/assets with
fixed headers; it trusts only requests carrying the edge secret. The design API stops minting
absolute `/w/{ws}` URLs: assets are root-relative, canonical/`og:url` are dropped, `og:image` is the
one absolute URL on the system hostname, and publish responses return absolute `url`/`custom_url`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async + asyncpg, Alembic (hash ids), pydantic-settings
(`clue_config`), `clue_storage` (fs/S3-R2), uv workspace, import-linter, mypy strict; Next.js/TS
frontend (`node --test` via tsx); Cloudflare Workers (wrangler); Railway (Dockerfile).

**Spec:** `docs/superpowers/specs/2026-09-17-custom-domain-publishing-design.md` (v1 design, founder-approved
2026-09-17). Research record: `_memory/2026-09-17-custom-domain-publishing-research.md`.

## Global Constraints

- Migration ids are Alembic random hashes (`uv run alembic revision -m "<slug>"`), chained off the
  current head `e8fdb29cd532`; hand-written, reversible, named constraints; `uv run alembic heads` must
  print exactly one head; `make db-smoke` runs only on a scratch/throwaway database.
- Every env flag the code reads appears in `.env.example` with its default the moment it is introduced,
  and the local `.env` mirrors it (founder parity rule 2026-08-31). Secrets stay blank in the example.
- Seam discipline (spec §2.2): `clue_spine` imports only `clue_core` + `clue_db`; `clue_design` never
  imports `clue_spine`; the page origin imports `clue_spine`, `clue_design` (DAL only), `clue_storage`,
  `clue_db`, `clue_config`, `clue_core` — never `lumen_api` or `clue_api`; the design API (`lumen_api`)
  gains a dependency on `clue_spine` and never imports `clue_api`.
- Slug pattern served by the origin: `^[a-z0-9][a-z0-9-]{0,71}$`. Reserved labels (never allocated):
  `app, api, www, pages, page-origin, mail, admin, share, static, assets, cdn, status, help, docs, dev,
  staging, test, clue, cluehq, login, auth, mcp`. Label length 3–40.
- CSP (spec §6.2), byte-exact: `default-src 'none'; script-src 'self' 'unsafe-inline' data:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'none'; object-src 'none'; worker-src 'none'; frame-src 'self' data: blob:; base-uri 'none'; form-action 'none'` (+ `; frame-ancestors 'self'` in the header form only).
- Response headers (spec §5.2): HTML/manifest `Cache-Control: public, max-age=60, must-revalidate`,
  `ETag: "sha256-<digest>"`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
  `X-Robots-Tag: noindex` on noindex pages; assets `Cache-Control: public, max-age=31536000, immutable`,
  `ETag: "sha256-<digest>"`, no `Access-Control-Allow-Origin`.
- Local page origin runs on port **8040** (`uvicorn --factory clue_page_origin.main:build_application`); dev values `CLUE_PAGES_SYSTEM_SUFFIX=pages.localhost`,
  `CLUE_PAGES_PUBLIC_SCHEME=http`, `CLUE_PAGES_PUBLIC_PORT=8040`, `CLUE_PAGES_TRUST_HOST_HEADER=true`
  are passed by `scripts/dev_stack.sh`, never hand-exported.
- Commits: one per task, no AI attribution trailer, never push. Do not commit on `main`.
- **Test-running rules.** Root Python suites: `( set -a; source .env; set +a; uv run pytest <path> -q )`.
  Before any DB test, confirm `grep '^CLUE_DATABASE_URL=' .env` names THIS lane's throwaway database
  (a `clue_<lane>` name); if it names a shared database, stop and ask. Never run `make check` or a broad
  `pytest` with real provider keys in the environment (live tests spend money); scope to the files named
  in each task and add `--ignore-glob='*_live.py'` when running a directory. Design API suites run from
  `subsystems/clue-design/apps/api` with `( set -a; source ../../../../.env; set +a; ../../../../.venv/bin/python -m pytest tests/<file> -q )`
  and need `node` on PATH and the built `lumen-api-helper` named by `LUMEN_CORE_HELPER`; run one
  pre-existing test first as a baseline before trusting a red. Never run the full design suite inline
  (it takes over an hour) — focused files only. Frontend: `cd apps/frontend && npm test && npm run lint`;
  `npm run build` only with the dev stack stopped.
- Every task ends with `uv run ruff format <changed paths> && uv run ruff check <changed paths>` and
  `uv run mypy` on Python changes (mypy is configured repo-wide; new packages are added to its file list in Task 8).

---

## Decisions this plan makes beyond the spec (flagged for the founder; each is reversible)

1. **`kind`/`status` are `text` + `CHECK`, not Postgres `ENUM` types.** Every migration since the object
   spine (`provider_incident`, `workspace`) uses `text CHECK (... IN (...))`; a Postgres enum would also
   require a mirror in `core.enums` and the enum-parity tests. Same values as spec §4.1, one less moving part.
2. **One idempotent allocator, three callers.** Spec §4.1 puts allocation inside `clue_spine.create_workspace`.
   The design API's `_ensure_workspace` (`lumen_api/design_store.py`) inserts `workspace` rows with raw SQL
   and never calls `create_workspace`, so dev/test workspaces would have no system hostname and every publish
   would fail. The plan adds `clue_spine.hostnames.ensure_system_hostname` and calls it from
   `create_workspace`, the backfill command, and `_ensure_workspace`.
3. **The system suffix reaches `clue_spine` as a parameter with a production default.** `clue_spine` may not
   import `clue_config` (import-linter Rule 2c). `create_workspace(..., pages_system_suffix=DEFAULT_PAGES_SYSTEM_SUFFIX)`
   defaults to `pages.cluehq.ai`; composition roots pass `settings.pages_system_suffix`. A row under the
   wrong suffix is exactly the configuration error the spec's startup warning reports.
4. **`X-Robots-Tag` comes from the immutable publish manifest** (`manifest["robots"] == "noindex"`, which
   `build_publish_package` already stamps), not a second `design_document` read — the header then always
   agrees with the bytes served.
5. **Both tables of spec §4 ship in S1's single migration**; `workspace_pages_settings` has no S1 reader.
   In S1 the origin's fallback-URL and favicon reads are a seam that returns `None` (documented for S2).
6. **The publish-state responses also carry `public_origin` and `custom_origin`** (spec §6.3 lists `url` and
   `custom_url`). The share menu shows the host before the first publish, and there is no S1 settings read
   to get it from. `custom_url`/`custom_origin` are `null` in S1 (no control plane yet), but the DAL read
   (`active_custom_hostname`) exists so S2 changes nothing on the design API.
7. **`/asset-store/{sha}` on the origin serves the recorded media type as-is** (no `sniff_mime` fallback for
   `application/octet-stream`); `sniff_mime` lives in `lumen_ingestion`, which the origin must not import.
8. **Share menu for non-web artifacts (ads):** the menu had a fake host for every kind. With no ad publish
   backend, the host segment is hidden for `kind !== "web"` and Publish stays inert — no new element is
   invented. Founder to confirm.
9. **Second link line for `custom_url`** (spec §8.1) is deferred to S2 with the co-founder's frame, since
   no custom hostname can be active in S1 and the dummy has one link row (UI-ceiling ruling).

---

## File structure

| Path | Responsibility |
| --- | --- |
| `libs/clue-config/clue_config/settings.py`, `secrets.py` | `pages_*` settings + `pages_edge_secret` |
| `.env.example`, `.env` | parity for the new keys |
| `alembic/versions/<rev>_workspace_hostnames_and_pages_settings.py` | the two tables |
| `libs/clue-spine/clue_spine/hostnames.py` (new) | label allocation, hostname helpers, registry DAL |
| `libs/clue-spine/clue_spine/spine.py`, `__init__.py` | `create_workspace` allocates a system row; exports |
| `platform/auth/clue_auth/provisioning.py` | threads `pages_system_suffix` into `create_workspace` |
| `scripts/backfill_workspace_hostnames.py` (new), `Makefile` | `make pages-backfill-hostnames` |
| `subsystems/design/clue_design/publishes.py` | `delivery_csp`, `check_publish_asset` (shared by origin + design API) |
| `platform/page_origin/` (new package `clue_page_origin`) | `reads.py`, `edge.py`, `routes.py`, `app.py`, `main.py`, `Dockerfile.railway` |
| `pyproject.toml` (root) | import-linter root package + contract, mypy files, ruff first-party |
| `scripts/dev_stack.sh`, `DEV_STACK.md` | the 8040 process |
| `subsystems/clue-design/apps/api/pyproject.toml` | `clue-spine` dependency |
| `subsystems/clue-design/apps/api/lumen_api/web_export.py` | host-independent package |
| `subsystems/clue-design/apps/api/lumen_api/public_pages.py` (new) | `system_public_origin`, `public_publish_url`, `custom_publish_url` |
| `subsystems/clue-design/apps/api/lumen_api/toolbelt/publishes.py`, `design_store.py`, `main.py` | tool input, repository reads, routes, deletions |
| `subsystems/clue-design/apps/api/tests/conftest.py` + 7 test files | `published_html` helper replaces `/w/` GETs |
| `apps/frontend/src/features/design-editor/engine/webDocuments.ts` | new publish-state fields |
| `apps/frontend/src/features/chat-shell/{hooks/use-artifact-sharing-controller.ts, components/artifact-header.tsx, components/artifact-share-menu.tsx, components/artifact-stage.tsx, model/artifact-sharing.ts}` | real publish wiring, host from backend |
| `infra/cloudflare/pages-edge/{worker.js, routing.js, routing.test.js, wrangler.toml}` (new) | the edge Worker |
| `docs/specs/pages-hosting-runbook.md` (new) | S0 operator runbook |
| `_memory/2026-09-17-custom-domain-publishing-s1.md` (new) | session record |

---

### Task 1: Settings, secrets and env parity for `CLUE_PAGES_*`

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (add fields after `self_serve_provisioning_enabled`, ~line 737)
- Modify: `libs/clue-config/clue_config/secrets.py` (add field after `gemini_api_key`)
- Modify: `.env.example` (new block after the `LUMEN_API_CORS_ORIGINS=` line, ~line 476), `.env` (same block)
- Test: `tests/test_pages_settings.py` (new)

**Interfaces:**
- Produces: `Settings.pages_system_suffix: str`, `Settings.pages_public_scheme: Literal["http","https"]`,
  `Settings.pages_public_port: int | None`, `Settings.pages_trust_host_header: bool`,
  `Settings.pages_origin_port: int`, `Secrets.pages_edge_secret: SecretStr | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pages_settings.py
"""Custom-domain publishing S1 Task 1: the public-pages settings ship their defaults and are documented."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Secrets, Settings

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

PAGES_SETTING_DEFAULTS: dict[str, object] = {
    "pages_system_suffix": "pages.cluehq.ai",
    "pages_public_scheme": "https",
    "pages_public_port": None,
    "pages_trust_host_header": False,
    "pages_origin_port": 8040,
}
PAGES_SECRET_FIELDS = ("pages_edge_secret",)


def _env_name(field_name: str) -> str:
    return f"CLUE_{field_name.upper()}"


@pytest.fixture
def unset_pages_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [*PAGES_SETTING_DEFAULTS, *PAGES_SECRET_FIELDS]:
        monkeypatch.delenv(_env_name(name), raising=False)


def test_every_pages_setting_ships_its_default(unset_pages_env: None) -> None:
    settings = Settings(_env_file=None)
    for field_name, default in PAGES_SETTING_DEFAULTS.items():
        assert getattr(settings, field_name) == default, field_name


def test_the_edge_secret_is_optional(unset_pages_env: None) -> None:
    secrets = Secrets(_env_file=None)  # type: ignore[call-arg]
    for field_name in PAGES_SECRET_FIELDS:
        assert field_name in Secrets.model_fields
        assert getattr(secrets, field_name) is None


def test_every_pages_env_name_is_documented_with_its_default() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for field_name, default in PAGES_SETTING_DEFAULTS.items():
        documented = re.search(rf"^{_env_name(field_name)}=(.*)$", text, re.MULTILINE)
        assert documented is not None, f"absent from .env.example: {_env_name(field_name)}"
        value = documented.group(1).strip()
        shipped = (
            ""
            if default is None
            else (str(default).lower() if isinstance(default, bool) else str(default))
        )
        assert value == shipped, field_name
    for field_name in PAGES_SECRET_FIELDS:
        assert re.search(rf"^{_env_name(field_name)}=$", text, re.MULTILINE), field_name


def test_an_empty_public_port_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """``source .env`` exports ``CLUE_PAGES_PUBLIC_PORT=`` as the empty string; it must load as None."""
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_PORT", "")
    assert Settings(_env_file=None).pages_public_port is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_pages_settings.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'pages_system_suffix'`.

- [ ] **Step 3: Add the settings fields**

In `libs/clue-config/clue_config/settings.py`, directly after the `self_serve_provisioning_enabled: bool = False` line, add:

```python
    # --- Public pages: hostnames and delivery (custom-domain publishing spec 2026-09-17 §9) ---
    # The suffix every workspace's permanent system hostname ends in (`<label>.<suffix>`). The
    # registry rows are written under it, so it must match the rows a database holds; the page
    # origin and the backfill warn loudly when they do not. Dev stack: `pages.localhost`.
    # Env: ``CLUE_PAGES_SYSTEM_SUFFIX``.
    pages_system_suffix: str = "pages.cluehq.ai"
    # Scheme and optional port for public page URLs the design API mints (og:image, publish `url`).
    # Production: https and no port; dev stack: http + 8040. Env: ``CLUE_PAGES_PUBLIC_SCHEME`` /
    # ``CLUE_PAGES_PUBLIC_PORT`` (empty string = unset).
    pages_public_scheme: Literal["http", "https"] = "https"
    pages_public_port: int | None = None
    # Local development only: the page origin skips the edge-secret gate and reads the public
    # hostname from the Host header. The origin refuses to start with this on while
    # CLUE_PAGES_EDGE_SECRET is set, so the two can never both be live in a deployment.
    # Env: ``CLUE_PAGES_TRUST_HOST_HEADER``.
    pages_trust_host_header: bool = False
    # The port `python -m clue_page_origin.main` listens on when Railway's PORT is absent.
    # Env: ``CLUE_PAGES_ORIGIN_PORT``.
    pages_origin_port: int = Field(default=8040, gt=0, lt=65536)
```

`Literal` and `Field` are already imported in that module (check the import block; add `from typing import Literal` if absent). For the empty-string port, add a validator next to the existing `field_validator`s in the class (search for `@field_validator(` to find the block; if the class has none, place it right after the fields above):

```python
    @field_validator("pages_public_port", mode="before")
    @classmethod
    def _empty_port_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and value.strip() == "" else value
```

In `libs/clue-config/clue_config/secrets.py`, after `gemini_api_key`, add:

```python
    # Env: CLUE_PAGES_EDGE_SECRET. Shared with the Cloudflare Worker `pages-edge`; the page origin
    # refuses page traffic that does not carry it in X-Clue-Edge-Auth (spec §5.2). Empty only in dev,
    # together with CLUE_PAGES_TRUST_HOST_HEADER=true.
    pages_edge_secret: SecretStr | None = None
```

- [ ] **Step 4: Document the keys**

In `.env.example`, after the `LUMEN_API_CORS_ORIGINS=...` line (inside the design API block), insert:

```dotenv

# --- Public pages: hostnames and delivery (custom-domain publishing spec 2026-09-17 §9) ---------
# Values here are the production defaults. The dev stack (scripts/dev_stack.sh) overrides four of
# them per process: suffix pages.localhost, scheme http, port 8040, trust-host-header true.
CLUE_PAGES_SYSTEM_SUFFIX=pages.cluehq.ai
CLUE_PAGES_PUBLIC_SCHEME=https
CLUE_PAGES_PUBLIC_PORT=
CLUE_PAGES_EDGE_SECRET=
CLUE_PAGES_TRUST_HOST_HEADER=false
CLUE_PAGES_ORIGIN_PORT=8040
```

Append the same six lines (same values, secret blank) to the local `.env` so the two stay at key parity.

The spec's remaining §9 keys (`CLUE_PAGES_CNAME_TARGET`, `CLUE_CLOUDFLARE_API_TOKEN`, `CLUE_CLOUDFLARE_ZONE_ID`) are introduced by S2 with the code that first reads them, per the parity rule; S1 reads none of them.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_pages_settings.py tests/test_telemetry_settings.py -q`
Expected: PASS (5 + the telemetry tests).

- [ ] **Step 6: Lint, typecheck, commit**

```bash
uv run ruff format libs/clue-config tests/test_pages_settings.py && uv run ruff check libs/clue-config tests/test_pages_settings.py && uv run mypy
git add libs/clue-config .env.example tests/test_pages_settings.py
git commit -m "config: CLUE_PAGES_* settings and the edge secret for public-page delivery"
```

---

### Task 2: Migration — `workspace_hostname` and `workspace_pages_settings`

**Files:**
- Create: `alembic/versions/<rev>_workspace_hostnames_and_pages_settings.py` (generated id)
- Test: `tests/db/test_workspace_hostname_schema_db.py` (new)

**Interfaces:**
- Produces: tables `workspace_hostname` (PK `hostname`) and `workspace_pages_settings` (PK `workspace_id`),
  partial unique indexes `workspace_hostname_one_system_per_workspace` / `workspace_hostname_one_custom_per_workspace`.

- [ ] **Step 1: Write the failing DB test**

```python
# tests/db/test_workspace_hostname_schema_db.py
"""Custom-domain publishing S1 Task 2: the hostname registry's invariants live in the schema."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.clue_spine.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")

_SYSTEM = (
    "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status) "
    "VALUES (:h, :w, 'system', 'active')"
)
_CUSTOM = (
    "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, cname_target, "
    "ownership_txt_name, ownership_txt_value) VALUES (:h, :w, 'custom', 'pending_dns', "
    "'pages.cluehq.ai', '_cf-custom-hostname.' || :h, 'token')"
)


async def _workspace(conn) -> str:
    workspace_id = "ws_" + uuid4().hex
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": workspace_id}
    )
    return workspace_id


def test_one_system_and_one_custom_row_per_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _workspace(conn)
            await conn.execute(text(_SYSTEM), {"h": f"{uuid4().hex[:8]}.pages.cluehq.ai", "w": ws})
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(_SYSTEM), {"h": f"{uuid4().hex[:8]}.pages.cluehq.ai", "w": ws}
                    )
            await conn.execute(text(_CUSTOM), {"h": f"go.{uuid4().hex[:6]}.example", "w": ws})
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(_CUSTOM), {"h": f"go2.{uuid4().hex[:6]}.example", "w": ws}
                    )

    run_async(scenario())


def test_a_hostname_belongs_to_exactly_one_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            first, second = await _workspace(conn), await _workspace(conn)
            hostname = f"go.{uuid4().hex[:6]}.example"
            await conn.execute(text(_CUSTOM), {"h": hostname, "w": first})
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(text(_CUSTOM), {"h": hostname, "w": second})

    run_async(scenario())


def test_system_rows_are_always_active_and_carry_no_custom_columns() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _workspace(conn)
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status) "
                            "VALUES (:h, :w, 'system', 'pending_dns')"
                        ),
                        {"h": f"{uuid4().hex[:8]}.pages.cluehq.ai", "w": ws},
                    )
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, "
                            "cname_target) VALUES (:h, :w, 'system', 'active', 'pages.cluehq.ai')"
                        ),
                        {"h": f"{uuid4().hex[:8]}.pages.cluehq.ai", "w": ws},
                    )

    run_async(scenario())


def test_hostnames_are_lowercase_without_trailing_dot_and_custom_rows_carry_ownership() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _workspace(conn)
            for bad in (f"Go.{uuid4().hex[:6]}.example", f"go.{uuid4().hex[:6]}.example."):
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(text(_CUSTOM), {"h": bad, "w": ws})
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status) "
                            "VALUES (:h, :w, 'custom', 'pending_dns')"
                        ),
                        {"h": f"go.{uuid4().hex[:6]}.example", "w": ws},
                    )

    run_async(scenario())


def test_pages_settings_fallback_must_be_https() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _workspace(conn)
            await conn.execute(
                text(
                    "INSERT INTO workspace_pages_settings (workspace_id, fallback_url) "
                    "VALUES (:w, 'https://www.example.com')"
                ),
                {"w": ws},
            )
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE workspace_pages_settings SET fallback_url = 'http://x.example' "
                            "WHERE workspace_id = :w"
                        ),
                        {"w": ws},
                    )

    run_async(scenario())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `( set -a; source .env; set +a; uv run pytest tests/db/test_workspace_hostname_schema_db.py -q )`
Expected: FAIL with `relation "workspace_hostname" does not exist` (the `migrated_db` fixture upgrades to head first, so a skip means the DSN is unset — fix that before continuing).

- [ ] **Step 3: Generate and write the migration**

Run: `uv run alembic revision -m "workspace hostnames and pages settings"` — note the printed revision id (`<rev>` below). Replace the generated file body with:

```python
"""workspace hostnames and pages settings

Revision ID: <rev>
Revises: e8fdb29cd532
Create Date: <keep the generated timestamp>

Custom-domain publishing (design 2026-09-17 §4). ``workspace_hostname`` is the registry every
public page request begins with: hostname → workspace. System rows (``<label>.pages.cluehq.ai``)
double as the workspace-slug registry (Part IV piece 1); custom rows carry the Cloudflare
custom-hostname lifecycle. ``kind``/``status`` are text + CHECK like every migration since the
object spine (no Postgres enum, no core-enum mirror). ``workspace_pages_settings`` is one row per
workspace of page defaults; a missing row means all defaults. The migration creates no rows —
system hostnames are backfilled by ``make pages-backfill-hostnames``.

Reversible: the downgrade drops both tables.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<rev>"
down_revision: str | None = "e8fdb29cd532"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE workspace_hostname (
            hostname              text NOT NULL,
            workspace_id          text NOT NULL,
            kind                  text NOT NULL,
            status                text NOT NULL,
            cf_custom_hostname_id text,
            cname_target          text,
            ownership_txt_name    text,
            ownership_txt_value   text,
            observed_cname        text,
            observed_txt_present  boolean,
            last_checked_at       timestamptz,
            last_error_code       text,
            last_error_detail     text,
            created_at            timestamptz NOT NULL DEFAULT now(),
            updated_at            timestamptz NOT NULL DEFAULT now(),
            activated_at          timestamptz,
            CONSTRAINT workspace_hostname_pkey PRIMARY KEY (hostname),
            CONSTRAINT workspace_hostname_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_hostname_kind CHECK (kind IN ('system', 'custom')),
            CONSTRAINT workspace_hostname_status CHECK (status IN (
                'pending_dns', 'verifying_ownership', 'issuing_certificate',
                'active', 'error', 'disconnecting')),
            CONSTRAINT workspace_hostname_lowercase
                CHECK (hostname = lower(hostname) AND hostname !~ '\\.$'),
            CONSTRAINT workspace_hostname_system_is_active
                CHECK (kind <> 'system' OR status = 'active'),
            CONSTRAINT workspace_hostname_custom_columns CHECK (
                kind <> 'custom' OR (cname_target IS NOT NULL AND ownership_txt_name IS NOT NULL
                                     AND ownership_txt_value IS NOT NULL)),
            CONSTRAINT workspace_hostname_system_columns CHECK (
                kind <> 'system' OR (cf_custom_hostname_id IS NULL AND cname_target IS NULL))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX workspace_hostname_one_system_per_workspace "
        "ON workspace_hostname (workspace_id) WHERE kind = 'system'"
    )
    op.execute(
        "CREATE UNIQUE INDEX workspace_hostname_one_custom_per_workspace "
        "ON workspace_hostname (workspace_id) WHERE kind = 'custom'"
    )
    op.execute("CREATE INDEX workspace_hostname_workspace_idx ON workspace_hostname (workspace_id)")
    op.execute(
        """
        CREATE TABLE workspace_pages_settings (
            workspace_id          text NOT NULL,
            fallback_url          text,
            page_title            text,
            page_description      text,
            favicon_sha256        text,
            social_preview_sha256 text,
            updated_at            timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT workspace_pages_settings_pkey PRIMARY KEY (workspace_id),
            CONSTRAINT workspace_pages_settings_workspace_fk
                FOREIGN KEY (workspace_id) REFERENCES workspace (workspace_id),
            CONSTRAINT workspace_pages_settings_fallback_https
                CHECK (fallback_url IS NULL OR fallback_url ~ '^https://')
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE workspace_pages_settings")
    op.execute("DROP TABLE workspace_hostname")
```

- [ ] **Step 4: Run the migration tests and smoke**

Run: `( set -a; source .env; set +a; uv run alembic heads && uv run pytest tests/db/test_workspace_hostname_schema_db.py tests/db/test_db_migrations.py -q )`
Expected: one head (`<rev>`), all PASS.

Then, on a scratch database only (create one: `createdb clue_pages_smoke` or the lane's throwaway copy), run:
`( set -a; source .env; set +a; CLUE_DATABASE_URL=postgresql+asyncpg://<user>@localhost/clue_pages_smoke make db-smoke )` — expected: up, down, up with no error. Drop the scratch DB afterwards.

- [ ] **Step 5: Commit**

```bash
uv run ruff format alembic/versions tests/db && uv run ruff check alembic/versions tests/db
git add alembic/versions tests/db/test_workspace_hostname_schema_db.py
git commit -m "db: workspace_hostname registry and workspace_pages_settings (custom-domain publishing S1)"
```

---

### Task 3: `clue_spine.hostnames` — pure label allocation and hostname helpers

**Files:**
- Create: `libs/clue-spine/clue_spine/hostnames.py`
- Test: `tests/clue_spine/test_hostnames_pure.py` (new, no DB)

**Interfaces:**
- Produces: `DEFAULT_PAGES_SYSTEM_SUFFIX = "pages.cluehq.ai"`, `RESERVED_LABELS: frozenset[str]`,
  `slugify_label(name: str) -> str`, `label_candidates(name: str, workspace_id: str) -> Iterator[str]`,
  `allocate_label(name: str, taken: Collection[str], *, workspace_id: str) -> str`,
  `normalize_hostname(value: str) -> str` (raises `ValueError`), `is_valid_hostname(value: str) -> bool`,
  `public_origin(hostname: str, *, scheme: str, port: int | None) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/clue_spine/test_hostnames_pure.py
"""Custom-domain publishing S1 Task 3: label allocation and hostname helpers (no DB)."""

from __future__ import annotations

from itertools import islice

import pytest

from clue_spine.hostnames import (
    RESERVED_LABELS,
    allocate_label,
    is_valid_hostname,
    label_candidates,
    normalize_hostname,
    public_origin,
    slugify_label,
)

WS = "ws_0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("Acme", "acme"),
        ("Acme Corp.", "acme-corp"),
        ("Crème Brûlée & Co", "creme-brulee-co"),
        ("  --Weird__Name--  ", "weird-name"),
        ("日本語", ""),
    ],
)
def test_slugify_label(name: str, label: str) -> None:
    assert slugify_label(name) == label


def test_short_or_empty_names_fall_back_to_the_workspace_id() -> None:
    assert next(label_candidates("", WS)) == "ws-01234567"
    assert next(label_candidates("ab", WS)) == "ws-01234567"
    assert next(label_candidates("日本語", WS)) == "ws-01234567"


def test_long_names_are_cut_at_forty_on_a_hyphen_boundary() -> None:
    name = "the-quick-brown-fox-jumps-over-the-lazy-dog-again-and-again"
    first = next(label_candidates(name, WS))
    assert len(first) <= 40
    assert first == "the-quick-brown-fox-jumps-over-the-lazy"
    solid = "a" * 50
    assert next(label_candidates(solid, WS)) == "a" * 40


def test_reserved_labels_are_never_offered() -> None:
    for reserved in ("app", "api", "www", "pages", "page-origin", "admin", "mcp"):
        assert reserved in RESERVED_LABELS
        assert next(label_candidates(reserved, WS)) == f"{reserved}-2"
    assert "acme" not in RESERVED_LABELS


def test_candidates_suffix_from_two_and_keep_the_length_cap() -> None:
    assert list(islice(label_candidates("acme", WS), 3)) == ["acme", "acme-2", "acme-3"]
    long = "b" * 40
    second = list(islice(label_candidates(long, WS), 2))[1]
    assert second == "b" * 38 + "-2"
    assert len(second) <= 40


def test_allocate_label_skips_taken_and_reserved() -> None:
    assert allocate_label("Acme", set(), workspace_id=WS) == "acme"
    assert allocate_label("Acme", {"acme"}, workspace_id=WS) == "acme-2"
    assert allocate_label("Acme", {"acme", "acme-2"}, workspace_id=WS) == "acme-3"
    assert allocate_label("www", set(), workspace_id=WS) == "www-2"


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("Go.Acme.COM", "go.acme.com"),
        ("go.acme.com.", "go.acme.com"),
        ("  go.acme.com ", "go.acme.com"),
        ("bücher.example", "xn--bcher-kva.example"),
    ],
)
def test_normalize_hostname(raw: str, normalized: str) -> None:
    assert normalize_hostname(raw) == normalized
    assert is_valid_hostname(normalized)


@pytest.mark.parametrize(
    "bad",
    ["", "-go.acme.com", "go-.acme.com", "go..acme.com", "a" * 64 + ".example", "go.acme.com:443", "go acme.com"],
)
def test_invalid_hostnames_are_refused(bad: str) -> None:
    assert not is_valid_hostname(bad)
    with pytest.raises(ValueError):
        normalize_hostname(bad)


def test_public_origin() -> None:
    assert public_origin("acme.pages.cluehq.ai", scheme="https", port=None) == "https://acme.pages.cluehq.ai"
    assert public_origin("acme.pages.localhost", scheme="http", port=8040) == "http://acme.pages.localhost:8040"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/clue_spine/test_hostnames_pure.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'clue_spine.hostnames'`.

- [ ] **Step 3: Write the module (pure part)**

```python
# libs/clue-spine/clue_spine/hostnames.py
"""Workspace hostnames — the registry that turns a public hostname into a workspace.

Custom-domain publishing (design 2026-09-17 §4.1). Two kinds of row live in ``workspace_hostname``:
``system`` rows (``<label>.<suffix>``, one per workspace, always active — they ARE the workspace-slug
registry) and ``custom`` rows (one customer-owned subdomain per workspace, with a Cloudflare
lifecycle owned by the S2 control plane). Everything public begins with :func:`resolve_active_hostname`.

The pure helpers (label allocation, hostname normalisation, public origin) have no I/O so the
control plane, the backfill and the design API share one validator. The DAL follows the spine's
raw-SQL style: functions over ``AsyncConnection``, the caller owns the transaction.

Import discipline (Rule 2c): only ``clue_core`` + ``clue_db``-level dependencies — the system suffix
therefore arrives as a parameter (default :data:`DEFAULT_PAGES_SYSTEM_SUFFIX`), never from settings.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Iterator
from itertools import count
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import UtcDatetime

DEFAULT_PAGES_SYSTEM_SUFFIX = "pages.cluehq.ai"

HostnameKind = Literal["system", "custom"]
HostnameStatus = Literal[
    "pending_dns", "verifying_ownership", "issuing_certificate", "active", "error", "disconnecting"
]

LABEL_MIN = 3
LABEL_MAX = 40
RESERVED_LABELS: frozenset[str] = frozenset(
    {
        "app", "api", "www", "pages", "page-origin", "mail", "admin", "share", "static", "assets",
        "cdn", "status", "help", "docs", "dev", "staging", "test", "clue", "cluehq", "login",
        "auth", "mcp",
    }
)

_HOSTNAME_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOSTNAME_SHAPE = re.compile(rf"^{_HOSTNAME_LABEL}(?:\.{_HOSTNAME_LABEL})*$")


class WorkspaceHostname(BaseModel):
    """A ``workspace_hostname`` row (the columns S1 reads; S2 widens for the custom lifecycle)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hostname: str
    workspace_id: str
    kind: HostnameKind
    status: HostnameStatus
    created_at: UtcDatetime
    activated_at: UtcDatetime | None = None


# --- pure helpers -----------------------------------------------------------
def slugify_label(name: str) -> str:
    """NFKD-fold to ASCII, lowercase, runs of non ``[a-z0-9]`` → one hyphen, hyphens trimmed."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


def _workspace_fragment(workspace_id: str) -> str:
    digits = re.sub(r"[^a-z0-9]", "", workspace_id.lower().removeprefix("ws_"))
    return f"ws-{digits[:8]:0<8}"


def _cut(label: str, limit: int) -> str:
    if len(label) <= limit:
        return label
    cut = label[:limit]
    hyphen = cut.rfind("-")
    if hyphen > 0:
        cut = cut[:hyphen]
    return cut.strip("-")


def label_candidates(name: str, workspace_id: str) -> Iterator[str]:
    """The ordered, infinite candidate list for a workspace's system label (spec §4.1)."""
    base = slugify_label(name)
    if len(base) < LABEL_MIN:
        base = _workspace_fragment(workspace_id)
    base = _cut(base, LABEL_MAX)
    if base not in RESERVED_LABELS:
        yield base
    for n in count(2):
        suffix = f"-{n}"
        yield f"{_cut(base, LABEL_MAX - len(suffix))}{suffix}"


def allocate_label(name: str, taken: Collection[str], *, workspace_id: str) -> str:
    """The first candidate not in ``taken`` (pure; the DAL loop is the DB-backed twin)."""
    for candidate in label_candidates(name, workspace_id):
        if candidate not in taken:
            return candidate
    raise AssertionError("unreachable: label_candidates is infinite")


def normalize_hostname(value: str) -> str:
    """Lowercase, trailing dot stripped, IDNA-encoded; raises ``ValueError`` when not a hostname."""
    stripped = value.strip().rstrip(".").lower()
    if not stripped:
        raise ValueError("hostname is empty")
    try:
        encoded = stripped.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError(f"hostname {value!r} is not IDNA-encodable") from error
    if len(encoded) > 253 or not _HOSTNAME_SHAPE.fullmatch(encoded):
        raise ValueError(f"hostname {value!r} is not a valid hostname")
    return encoded


def is_valid_hostname(value: str) -> bool:
    try:
        normalize_hostname(value)
    except ValueError:
        return False
    return True


def public_origin(hostname: str, *, scheme: str, port: int | None) -> str:
    """``https://acme.pages.cluehq.ai`` or, in dev, ``http://acme.pages.localhost:8040``."""
    return f"{scheme}://{hostname}" + (f":{port}" if port else "")
```

(The DAL functions are added in Task 4; leave the module ending here for now.)

- [ ] **Step 4: Export from the package**

In `libs/clue-spine/clue_spine/__init__.py`, add to the imports and `__all__`:
`DEFAULT_PAGES_SYSTEM_SUFFIX`, `RESERVED_LABELS`, `WorkspaceHostname`, `allocate_label`,
`label_candidates`, `normalize_hostname`, `is_valid_hostname`, `public_origin`, `slugify_label`
(from `clue_spine.hostnames`). Keep the existing exports untouched.

- [ ] **Step 5: Run tests, lint, commit**

Run: `uv run pytest tests/clue_spine/test_hostnames_pure.py -q` — expected PASS.

```bash
uv run ruff format libs/clue-spine tests/clue_spine && uv run ruff check libs/clue-spine tests/clue_spine && uv run mypy
git add libs/clue-spine tests/clue_spine/test_hostnames_pure.py
git commit -m "spine: hostname label allocation and hostname helpers (custom-domain publishing S1)"
```

---

### Task 4: `clue_spine.hostnames` DAL, `create_workspace` allocation, provisioning thread-through

**Files:**
- Modify: `libs/clue-spine/clue_spine/hostnames.py` (append DAL), `libs/clue-spine/clue_spine/spine.py:105-116`, `libs/clue-spine/clue_spine/__init__.py`
- Modify: `platform/auth/clue_auth/provisioning.py` (`provision_workspace_owner` ~line 178, `provision_self_serve_workspace` ~line 234), and their call sites in `platform/api/clue_api/auth_wiring.py`
- Test: `tests/clue_spine/test_hostnames_db.py` (new), `tests/clue_spine/test_spine.py` (one added test)

**Interfaces:**
- Produces (all `async`, first arg `conn: AsyncConnection`):
  `ensure_system_hostname(conn, *, workspace_id: str, name: str, suffix: str) -> WorkspaceHostname`,
  `system_hostname(conn, workspace_id: str) -> str | None`,
  `active_custom_hostname(conn, workspace_id: str) -> str | None`,
  `resolve_active_hostname(conn, hostname: str) -> str | None`,
  `workspaces_without_system_hostname(conn) -> list[tuple[str, str]]`,
  `system_hostnames_off_suffix(conn, suffix: str) -> list[str]`.
- `create_workspace(conn, *, name, workspace_id=None, pages_system_suffix: str = DEFAULT_PAGES_SYSTEM_SUFFIX) -> Workspace`.

- [ ] **Step 1: Write the failing DB tests**

```python
# tests/clue_spine/test_hostnames_db.py
"""Custom-domain publishing S1 Task 4: the hostname registry DAL."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_spine import create_workspace
from clue_spine.hostnames import (
    active_custom_hostname,
    ensure_system_hostname,
    resolve_active_hostname,
    system_hostname,
    system_hostnames_off_suffix,
    workspaces_without_system_hostname,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")
SUFFIX = "pages.test"


def _name() -> str:
    return "Acme " + uuid4().hex[:6]


def test_create_workspace_allocates_a_system_hostname_in_the_same_transaction() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            name = _name()
            ws = await create_workspace(conn, name=name, pages_system_suffix=SUFFIX)
            hostname = await system_hostname(conn, ws.workspace_id)
            assert hostname == f"{name.lower().replace(' ', '-')}.{SUFFIX}"
            assert await resolve_active_hostname(conn, hostname) == ws.workspace_id

    run_async(scenario())


def test_ensure_is_idempotent_and_collisions_get_a_numeric_suffix() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            name = _name()
            first = await create_workspace(conn, name=name, pages_system_suffix=SUFFIX)
            second = await create_workspace(conn, name=name, pages_system_suffix=SUFFIX)
            base = await system_hostname(conn, first.workspace_id)
            assert base is not None
            assert await system_hostname(conn, second.workspace_id) == base.replace(
                f".{SUFFIX}", f"-2.{SUFFIX}"
            )
            again = await ensure_system_hostname(
                conn, workspace_id=first.workspace_id, name="Renamed", suffix=SUFFIX
            )
            assert again.hostname == base  # an existing row is returned, never re-allocated

    run_async(scenario())


def test_reserved_labels_and_short_names() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            www = await create_workspace(conn, name="www", pages_system_suffix=SUFFIX)
            assert await system_hostname(conn, www.workspace_id) == f"www-2.{SUFFIX}"
            short = await create_workspace(conn, name="ab", pages_system_suffix=SUFFIX)
            got = await system_hostname(conn, short.workspace_id)
            assert got is not None and got.startswith("ws-") and got.endswith(f".{SUFFIX}")

    run_async(scenario())


def test_resolve_only_returns_active_rows() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(conn, name=_name(), pages_system_suffix=SUFFIX)
            hostname = f"go.{uuid4().hex[:6]}.example"
            await conn.execute(
                text(
                    "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, "
                    "cname_target, ownership_txt_name, ownership_txt_value) VALUES "
                    "(:h, :w, 'custom', 'pending_dns', 'pages.test', 'n', 'v')"
                ),
                {"h": hostname, "w": ws.workspace_id},
            )
            assert await resolve_active_hostname(conn, hostname) is None
            assert await active_custom_hostname(conn, ws.workspace_id) is None
            await conn.execute(
                text("UPDATE workspace_hostname SET status = 'active' WHERE hostname = :h"),
                {"h": hostname},
            )
            assert await resolve_active_hostname(conn, hostname) == ws.workspace_id
            assert await active_custom_hostname(conn, ws.workspace_id) == hostname
            assert await resolve_active_hostname(conn, "nobody.example") is None

    run_async(scenario())


def test_backfill_queries() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            bare = "ws_" + uuid4().hex
            await conn.execute(
                text("INSERT INTO workspace (workspace_id, name) VALUES (:w, 'Bare')"), {"w": bare}
            )
            missing = await workspaces_without_system_hostname(conn)
            assert (bare, "Bare") in missing
            await ensure_system_hostname(conn, workspace_id=bare, name="Bare", suffix=SUFFIX)
            assert (bare, "Bare") not in await workspaces_without_system_hostname(conn)
            off = await system_hostnames_off_suffix(conn, "pages.other")
            assert any(h.endswith(f".{SUFFIX}") for h in off)
            assert not [h for h in await system_hostnames_off_suffix(conn, SUFFIX) if h.endswith(f".{SUFFIX}")]

    run_async(scenario())
```

- [ ] **Step 2: Run to verify failure**

Run: `( set -a; source .env; set +a; uv run pytest tests/clue_spine/test_hostnames_db.py -q )`
Expected: FAIL — `ImportError: cannot import name 'ensure_system_hostname'`.

- [ ] **Step 3: Append the DAL to `hostnames.py`**

```python
# --- DAL (append to libs/clue-spine/clue_spine/hostnames.py) ---------------
_ROW = "hostname, workspace_id, kind, status, created_at, activated_at"


async def _system_row(conn: AsyncConnection, workspace_id: str) -> WorkspaceHostname | None:
    result = await conn.execute(
        text(
            f"SELECT {_ROW} FROM workspace_hostname "
            "WHERE workspace_id = :w AND kind = 'system'"
        ),
        {"w": workspace_id},
    )
    row = result.mappings().first()
    return WorkspaceHostname(**dict(row)) if row is not None else None


async def ensure_system_hostname(
    conn: AsyncConnection, *, workspace_id: str, name: str, suffix: str
) -> WorkspaceHostname:
    """The ONE allocator. Returns the workspace's system row, inserting it on first call.

    Idempotent and race-safe: an existing row wins outright; a hostname collision moves to the
    next candidate (``ON CONFLICT (hostname) DO NOTHING``); losing the one-system-per-workspace
    race re-reads the winner. Each attempt runs in a savepoint so a conflict never poisons the
    caller's transaction. Called by :func:`clue_spine.create_workspace`, the backfill command and
    the design API's dev workspace scaffolding, so every creator gets a row without knowing about it.
    """
    existing = await _system_row(conn, workspace_id)
    if existing is not None:
        return existing
    for label in label_candidates(name, workspace_id):
        hostname = f"{label}.{suffix}"
        try:
            async with conn.begin_nested():
                result = await conn.execute(
                    text(
                        "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, "
                        "activated_at) VALUES (:h, :w, 'system', 'active', now()) "
                        f"ON CONFLICT (hostname) DO NOTHING RETURNING {_ROW}"
                    ),
                    {"h": hostname, "w": workspace_id},
                )
                row = result.mappings().first()
        except IntegrityError:
            winner = await _system_row(conn, workspace_id)
            if winner is not None:
                return winner
            raise
        if row is not None:
            return WorkspaceHostname(**dict(row))
    raise AssertionError("unreachable: label_candidates is infinite")


async def system_hostname(conn: AsyncConnection, workspace_id: str) -> str | None:
    row = await _system_row(conn, workspace_id)
    return row.hostname if row is not None else None


async def active_custom_hostname(conn: AsyncConnection, workspace_id: str) -> str | None:
    result = await conn.execute(
        text(
            "SELECT hostname FROM workspace_hostname "
            "WHERE workspace_id = :w AND kind = 'custom' AND status = 'active'"
        ),
        {"w": workspace_id},
    )
    row = result.first()
    return str(row[0]) if row is not None else None


async def resolve_active_hostname(conn: AsyncConnection, hostname: str) -> str | None:
    """hostname → workspace_id, for ACTIVE rows only (a provisioning custom hostname is 404)."""
    result = await conn.execute(
        text("SELECT workspace_id FROM workspace_hostname WHERE hostname = :h AND status = 'active'"),
        {"h": hostname},
    )
    row = result.first()
    return str(row[0]) if row is not None else None


async def workspaces_without_system_hostname(conn: AsyncConnection) -> list[tuple[str, str]]:
    result = await conn.execute(
        text(
            "SELECT w.workspace_id, w.name FROM workspace w "
            "WHERE NOT EXISTS (SELECT 1 FROM workspace_hostname h "
            "WHERE h.workspace_id = w.workspace_id AND h.kind = 'system') "
            "ORDER BY w.created_at, w.workspace_id"
        )
    )
    return [(str(r[0]), str(r[1])) for r in result.all()]


async def system_hostnames_off_suffix(conn: AsyncConnection, suffix: str) -> list[str]:
    """System rows that do not end in ``.<suffix>`` — a configuration error to warn about at startup."""
    result = await conn.execute(
        text(
            "SELECT hostname FROM workspace_hostname WHERE kind = 'system' "
            "AND hostname NOT LIKE :pattern ORDER BY hostname"
        ),
        {"pattern": f"%.{suffix}"},
    )
    return [str(r[0]) for r in result.all()]
```

- [ ] **Step 4: Allocate inside `create_workspace`**

In `libs/clue-spine/clue_spine/spine.py`, replace `create_workspace` with:

```python
async def create_workspace(
    conn: AsyncConnection,
    *,
    name: str,
    workspace_id: str | None = None,
    pages_system_suffix: str = DEFAULT_PAGES_SYSTEM_SUFFIX,
) -> Workspace:
    """Insert a workspace and return it (id minted unless a legacy one is supplied).

    Also allocates the workspace's permanent system hostname (``<label>.<pages_system_suffix>``) in
    the SAME transaction (custom-domain publishing §4.1), so every creator — owner provisioning,
    self-serve provisioning, scripts, tests — gets one without knowing about it. Composition roots
    pass ``settings.pages_system_suffix``; the default is the production suffix.
    """
    result = await conn.execute(
        text(
            "INSERT INTO workspace (workspace_id, name) VALUES (:workspace_id, :name) "
            "RETURNING workspace_id, name, status, created_at"
        ),
        {"workspace_id": workspace_id or new_workspace_id(), "name": name},
    )
    workspace = Workspace(**dict(result.mappings().one()))
    await ensure_system_hostname(
        conn, workspace_id=workspace.workspace_id, name=name, suffix=pages_system_suffix
    )
    return workspace
```

Add `from clue_spine.hostnames import DEFAULT_PAGES_SYSTEM_SUFFIX, ensure_system_hostname` to `spine.py`'s imports (`hostnames.py` must not import `spine.py` — it does not). Export the six DAL functions from `clue_spine/__init__.py`.

- [ ] **Step 5: Thread the suffix through provisioning**

In `platform/auth/clue_auth/provisioning.py`: add a keyword parameter `pages_system_suffix: str = DEFAULT_PAGES_SYSTEM_SUFFIX` to `provision_workspace_owner` and `provision_self_serve_workspace`, and pass it to their `create_workspace(...)` calls (lines ~196 and ~303). Import `DEFAULT_PAGES_SYSTEM_SUFFIX` from `clue_spine`. Then `grep -n "provision_workspace_owner\|provision_self_serve_workspace" platform/api/clue_api/*.py` and pass `pages_system_suffix=settings.pages_system_suffix` at each production call site (they already have a `Settings` in scope or receive one; if a call site has none, resolve it with `load_settings()` from `clue_config` at that composition point, not inside `clue_auth`). Leave `stage0_trial.py`, `answer_key_loader.py`, `trial/*fixture.py` and `scripts/script_support.py` on the default.

- [ ] **Step 6: Add the spine round-trip test**

Append to `tests/clue_spine/test_spine.py`:

```python
def test_create_workspace_has_a_system_hostname_under_the_default_suffix() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(conn, name="Hostname Default")
            row = (
                await conn.execute(
                    text(
                        "SELECT hostname FROM workspace_hostname WHERE workspace_id = :w AND kind = 'system'"
                    ),
                    {"w": ws.workspace_id},
                )
            ).first()
            assert row is not None and row[0] == "hostname-default.pages.cluehq.ai"

    run_async(scenario())
```

- [ ] **Step 7: Run tests, gates, commit**

Run: `( set -a; source .env; set +a; uv run pytest tests/clue_spine tests/auth -q --ignore-glob='*_live.py' )` — expected PASS (auth tests exercise provisioning; any failure naming `pages_system_suffix` is a missed call site).

```bash
uv run ruff format libs/clue-spine platform/auth platform/api/clue_api/auth_wiring.py tests/clue_spine && uv run ruff check libs/clue-spine platform/auth platform/api tests/clue_spine && uv run mypy && uv run lint-imports
git add libs/clue-spine platform/auth platform/api/clue_api tests/clue_spine
git commit -m "spine: hostname registry DAL; create_workspace allocates the system hostname"
```

---

### Task 5: Backfill command `make pages-backfill-hostnames`

**Files:**
- Create: `scripts/backfill_workspace_hostnames.py`
- Modify: `Makefile` (new target after `cost-report`)
- Test: `tests/clue_spine/test_hostnames_backfill_db.py` (new)

**Interfaces:**
- Produces: `clue_spine.hostnames.backfill_system_hostnames(conn, *, suffix: str, dry_run: bool = False) -> dict[str, int]` returning `{"missing": n, "written": n, "off_suffix": n}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/clue_spine/test_hostnames_backfill_db.py
"""Custom-domain publishing S1 Task 5: the idempotent system-hostname backfill."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_spine.hostnames import backfill_system_hostnames, system_hostname

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")


def test_backfill_writes_missing_rows_once() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            bare = ["ws_" + uuid4().hex for _ in range(2)]
            for w in bare:
                await conn.execute(
                    text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :n)"),
                    {"w": w, "n": "Backfill " + w[-4:]},
                )
            preview = await backfill_system_hostnames(conn, suffix="pages.test", dry_run=True)
            assert preview["written"] == 0 and preview["missing"] >= 2
            assert await system_hostname(conn, bare[0]) is None
            first = await backfill_system_hostnames(conn, suffix="pages.test")
            assert first["written"] >= 2
            assert (await system_hostname(conn, bare[0]) or "").endswith(".pages.test")
            second = await backfill_system_hostnames(conn, suffix="pages.test")
            assert second["written"] == 0

    run_async(scenario())
```

- [ ] **Step 2: Run to verify failure** — `( set -a; source .env; set +a; uv run pytest tests/clue_spine/test_hostnames_backfill_db.py -q )` → `ImportError`.

- [ ] **Step 3: Implement**

Append to `hostnames.py`:

```python
async def backfill_system_hostnames(
    conn: AsyncConnection, *, suffix: str, dry_run: bool = False
) -> dict[str, int]:
    """Give every workspace without a system row one (idempotent; safe to re-run at deploy)."""
    missing = await workspaces_without_system_hostname(conn)
    written = 0
    if not dry_run:
        for workspace_id, name in missing:
            await ensure_system_hostname(conn, workspace_id=workspace_id, name=name, suffix=suffix)
            written += 1
    off_suffix = await system_hostnames_off_suffix(conn, suffix)
    return {"missing": len(missing), "written": written, "off_suffix": len(off_suffix)}
```

Create `scripts/backfill_workspace_hostnames.py`:

```python
#!/usr/bin/env python3
"""Backfill system hostnames for workspaces created before the registry existed (spec §4.1, §11).

    uv run python scripts/backfill_workspace_hostnames.py \
        --database-url postgresql+asyncpg://clue:clue@localhost:5432/clue [--suffix pages.localhost] [--dry-run]

The suffix defaults to CLUE_PAGES_SYSTEM_SUFFIX. Idempotent: a workspace that already has a system
row is skipped. Prints the counts as JSON and warns when existing rows sit under another suffix.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from clue_config import Settings
from clue_db import db_lifespan, transaction
from clue_spine.hostnames import backfill_system_hostnames


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Allocate missing <label>.<suffix> system hostnames.")
    parser.add_argument("--database-url", required=True, help="Async Postgres URL to repair (required; never falls through to CLUE_DATABASE_URL).")
    parser.add_argument("--suffix", default=None, help="System suffix (default: CLUE_PAGES_SYSTEM_SUFFIX).")
    parser.add_argument("--dry-run", action="store_true", help="Report without writing.")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, int]:
    suffix = args.suffix or Settings().pages_system_suffix
    async with db_lifespan(args.database_url):
        async with transaction() as conn:
            return await backfill_system_hostnames(conn, suffix=suffix, dry_run=args.dry_run)


def main() -> None:
    args = _args()
    counts = asyncio.run(_run(args))
    print(json.dumps(counts))
    if counts["off_suffix"]:
        print(
            f"WARNING: {counts['off_suffix']} system hostname(s) do not end in the configured suffix "
            "(a copied database under a different CLUE_PAGES_SYSTEM_SUFFIX?)",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
```

Add to the `Makefile` after the `cost-report` target:

```make
pages-backfill-hostnames: ## Allocate missing system hostnames. Usage: make pages-backfill-hostnames ARGS="--database-url postgresql+asyncpg://... [--suffix pages.localhost] [--dry-run]"
	uv run python scripts/backfill_workspace_hostnames.py $(ARGS)
```

- [ ] **Step 4: Run test + a real dry run on the lane DB**

`( set -a; source .env; set +a; uv run pytest tests/clue_spine/test_hostnames_backfill_db.py -q )` → PASS.
`( set -a; source .env; set +a; make pages-backfill-hostnames ARGS="--database-url $CLUE_DATABASE_URL --suffix pages.localhost --dry-run" )` → prints JSON with `"written": 0`. Then run without `--dry-run` once on the lane DB (this is the S1 backfill the spec asks for; record the counts in the memory note in Task 14).

- [ ] **Step 5: Commit**

```bash
uv run ruff format scripts/backfill_workspace_hostnames.py libs/clue-spine tests/clue_spine && uv run ruff check scripts libs/clue-spine tests/clue_spine
git add scripts/backfill_workspace_hostnames.py Makefile libs/clue-spine tests/clue_spine/test_hostnames_backfill_db.py
git commit -m "spine: make pages-backfill-hostnames (idempotent system-hostname backfill)"
```

---

### Task 6: Shared delivery constants in `clue_design.publishes`

**Files:**
- Modify: `subsystems/design/clue_design/publishes.py` (append)
- Test: `tests/design/test_publish_delivery.py` (new, no DB)

**Interfaces:**
- Produces: `DELIVERY_CSP_META: str`, `DELIVERY_CSP_HEADER: str`, `delivery_csp(*, meta: bool = False) -> str`,
  `PUBLISH_ASSET_MEDIA_TYPES: dict[str, str]`, `PUBLISH_ASSET_EXTENSIONS = ("js", "css", "html")`,
  `class PublishAssetMismatch(ValueError)`, `check_publish_asset(*, data: bytes, media_type: str, digest: str, extension: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/design/test_publish_delivery.py
"""Custom-domain publishing S1 Task 6: the delivery CSP and the publish-asset integrity check."""

from __future__ import annotations

import hashlib

import pytest

from clue_design.publishes import (
    DELIVERY_CSP_HEADER,
    DELIVERY_CSP_META,
    PublishAssetMismatch,
    check_publish_asset,
    delivery_csp,
)

EXPECTED_META = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' data:; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'none'; object-src 'none'; "
    "worker-src 'none'; frame-src 'self' data: blob:; base-uri 'none'; form-action 'none'"
)


def test_csp_is_byte_exact_and_only_the_header_names_frame_ancestors() -> None:
    assert DELIVERY_CSP_META == EXPECTED_META
    assert DELIVERY_CSP_HEADER == EXPECTED_META + "; frame-ancestors 'self'"
    assert delivery_csp(meta=True) == DELIVERY_CSP_META
    assert delivery_csp() == DELIVERY_CSP_HEADER
    assert "http" not in DELIVERY_CSP_HEADER


def test_check_publish_asset_accepts_matching_bytes() -> None:
    data = b"console.log(1)"
    digest = hashlib.sha256(data).hexdigest()
    assert (
        check_publish_asset(
            data=data, media_type="text/javascript; charset=utf-8", digest=digest, extension="js"
        )
        == "text/javascript; charset=utf-8"
    )


@pytest.mark.parametrize(
    ("media_type", "digest_ok", "extension"),
    [
        ("text/css; charset=utf-8", True, "js"),  # media type vs URL
        ("text/javascript; charset=utf-8", False, "js"),  # bytes vs digest
        ("text/javascript; charset=utf-8", True, "png"),  # unknown extension
    ],
)
def test_check_publish_asset_refuses(media_type: str, digest_ok: bool, extension: str) -> None:
    data = b"body{}"
    digest = hashlib.sha256(data).hexdigest() if digest_ok else "0" * 64
    with pytest.raises(PublishAssetMismatch):
        check_publish_asset(data=data, media_type=media_type, digest=digest, extension=extension)
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/design/test_publish_delivery.py -q` → `ImportError`.

- [ ] **Step 3: Implement (append to `subsystems/design/clue_design/publishes.py`)**

```python
# --- delivery constants shared by the page origin and the design API's publish package -------
# Custom-domain publishing (design 2026-09-17 §5.2, §6.2). One home so the served header and the
# embedded meta can never drift: the origin sends DELIVERY_CSP_HEADER; build_publish_package
# embeds DELIVERY_CSP_META (frame-ancestors is ignored inside a meta CSP by spec).

import hashlib as _hashlib

DELIVERY_CSP_META = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' data:; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'none'; object-src 'none'; "
    "worker-src 'none'; frame-src 'self' data: blob:; base-uri 'none'; form-action 'none'"
)
DELIVERY_CSP_HEADER = DELIVERY_CSP_META + "; frame-ancestors 'self'"


def delivery_csp(*, meta: bool = False) -> str:
    return DELIVERY_CSP_META if meta else DELIVERY_CSP_HEADER


PUBLISH_ASSET_EXTENSIONS: tuple[str, ...] = ("js", "css", "html")
PUBLISH_ASSET_MEDIA_TYPES: dict[str, str] = {
    "js": "text/javascript; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "html": "text/html; charset=utf-8",
}


class PublishAssetMismatch(ValueError):
    """The bytes behind a publish-asset URL do not match what the URL promises."""


def check_publish_asset(*, data: bytes, media_type: str, digest: str, extension: str) -> str:
    """Integrity-check one immutable publish asset; returns the media type to serve.

    The URL's extension must agree with the media type recorded on the blob's ``artifact`` row, and
    the bytes must hash to the digest in the URL — so ``/{digest}.css`` can never serve JavaScript.
    Re-homed from ``lumen_api.web_export.resolve_publish_asset`` so the page origin (which may not
    import ``lumen_api``) and the design API share one rule.
    """
    expected = PUBLISH_ASSET_MEDIA_TYPES.get(extension)
    if expected is None:
        raise PublishAssetMismatch("publish asset media type does not match its URL")
    if _hashlib.sha256(data).hexdigest() != digest:
        raise PublishAssetMismatch("publish asset failed its integrity check")
    if media_type != expected:
        raise PublishAssetMismatch("publish asset media type does not match its URL")
    return expected
```

(Move the `import hashlib as _hashlib` line up into the module's import block.)

- [ ] **Step 4: Run, gate, commit**

`uv run pytest tests/design/test_publish_delivery.py -q` → PASS.

```bash
uv run ruff format subsystems/design tests/design && uv run ruff check subsystems/design tests/design && uv run mypy
git add subsystems/design/clue_design/publishes.py tests/design/test_publish_delivery.py
git commit -m "design: shared delivery CSP and publish-asset integrity check for the page origin"
```

---

### Task 7: The page origin service — reads, edge gate, routes, app (tests with fakes)

**Files:**
- Create: `platform/page_origin/pyproject.toml`, `platform/page_origin/clue_page_origin/__init__.py`,
  `.../reads.py`, `.../edge.py`, `.../routes.py`, `.../app.py`, `.../py.typed`
- Test: `tests/page_origin/__init__.py` (empty), `tests/page_origin/conftest.py`, `tests/page_origin/test_edge_gate.py`, `tests/page_origin/test_routes.py`

**Interfaces:**
- Produces: `ServedPublish` (pydantic: `html, html_digest, manifest_json, manifest_digest, noindex`),
  `PageReads` protocol, `DbPageReads(storage, *, conn_factory=transaction)`,
  `EdgeGate(*, secret: str | None, trust_host_header: bool)` with `.public_host(request) -> str`,
  `create_page_origin_app(*, reads: PageReads, gate: EdgeGate, lifespan=None) -> FastAPI`.
- Consumes: `resolve_active_hostname`, `get_web_publish`, `read_design_blob`, `read_public_design_blob`,
  `delivery_csp`, `check_publish_asset`.

- [ ] **Step 1: Package scaffold**

`platform/page_origin/pyproject.toml`:

```toml
[project]
name = "clue-page-origin"
version = "0.0.0"
description = "Public page origin — serves published web pages by hostname behind the Cloudflare edge (custom-domain publishing S1)."
requires-python = ">=3.12"
license = { text = "Proprietary" }
dependencies = [
    "clue-core",
    "clue-config",
    "clue-db",
    "clue-spine",
    "clue-design",
    "clue-storage",
    "clue-obs",
    "fastapi>=0.138.0",
    "uvicorn>=0.35.0",
    "pydantic>=2.7",
    "sqlalchemy[asyncio]>=2.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["clue_page_origin"]

[tool.uv.sources]
clue-core = { workspace = true }
clue-config = { workspace = true }
clue-db = { workspace = true }
clue-spine = { workspace = true }
clue-design = { workspace = true }
clue-storage = { workspace = true }
clue-obs = { workspace = true }
```

`clue_page_origin/__init__.py`:

```python
"""The public page origin (custom-domain publishing S1, spec §5).

One small FastAPI service on Railway. Every request arrives through the Cloudflare Worker
``pages-edge`` carrying ``X-Clue-Public-Host`` (the hostname the visitor typed) and
``X-Clue-Edge-Auth`` (a shared secret); the origin resolves the hostname through the
``workspace_hostname`` registry, the path through ``design_web_publish``, and serves the immutable
publish package. It imports the spine, the design DAL and storage — never ``lumen_api`` or ``clue_api``.
"""

from clue_page_origin.app import create_page_origin_app
from clue_page_origin.edge import EdgeGate
from clue_page_origin.reads import DbPageReads, PageReads, ServedPublish

__all__ = ["create_page_origin_app", "EdgeGate", "DbPageReads", "PageReads", "ServedPublish"]
```

Run `uv sync --all-packages` so the new member is installed (the `platform/*` glob picks it up).

- [ ] **Step 2: Write the failing tests**

`tests/page_origin/conftest.py`:

```python
"""Fakes for the page origin: an in-memory registry + publish store, no database."""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from clue_page_origin import EdgeGate, ServedPublish, create_page_origin_app

SECRET = "edge-secret-for-tests"
HOST = "acme.pages.test"
WS = "ws_acme"


def _sha(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


class FakePageReads:
    def __init__(self) -> None:
        self.hostnames: dict[str, str] = {HOST: WS}
        self.publishes: dict[tuple[str, str], ServedPublish] = {}
        self.fallbacks: dict[str, str] = {}
        self.favicons: dict[str, tuple[str, bytes]] = {}
        self.assets: dict[tuple[str, str], tuple[str, bytes]] = {}
        self.public: dict[str, tuple[str, bytes]] = {}

    def publish(self, slug: str, html: str, *, noindex: bool = False, workspace_id: str = WS) -> None:
        manifest = {"slug": slug, **({"robots": "noindex"} if noindex else {})}
        manifest_json = json.dumps(manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        self.publishes[(workspace_id, slug)] = ServedPublish(
            html=html, html_digest=_sha(html), manifest_json=manifest_json,
            manifest_digest=_sha(manifest_json), noindex=noindex,
        )

    async def workspace_for_hostname(self, hostname: str) -> str | None:
        return self.hostnames.get(hostname)

    async def active_publish(self, workspace_id: str, slug: str) -> ServedPublish | None:
        return self.publishes.get((workspace_id, slug))

    async def fallback_url(self, workspace_id: str) -> str | None:
        return self.fallbacks.get(workspace_id)

    async def favicon(self, workspace_id: str) -> tuple[str, bytes] | None:
        return self.favicons.get(workspace_id)

    async def publish_asset(self, workspace_id: str, sha256: str) -> tuple[str, bytes] | None:
        return self.assets.get((workspace_id, sha256))

    async def public_blob(self, sha256: str) -> tuple[str, bytes] | None:
        return self.public.get(sha256)


@pytest.fixture
def reads() -> FakePageReads:
    return FakePageReads()


@pytest.fixture
def client(reads: FakePageReads) -> TestClient:
    app = create_page_origin_app(reads=reads, gate=EdgeGate(secret=SECRET, trust_host_header=False))
    return TestClient(app)


@pytest.fixture
def dev_client(reads: FakePageReads) -> TestClient:
    app = create_page_origin_app(reads=reads, gate=EdgeGate(secret=None, trust_host_header=True))
    return TestClient(app)


def edge(host: str = HOST, *, secret: str | None = SECRET) -> dict[str, str]:
    headers = {"X-Clue-Public-Host": host}
    if secret is not None:
        headers["X-Clue-Edge-Auth"] = secret
    return headers
```

`tests/page_origin/test_edge_gate.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from clue_page_origin import EdgeGate

from .conftest import HOST, FakePageReads, edge


def test_healthz_needs_no_secret(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_missing_or_wrong_secret_is_403_with_empty_body(client: TestClient, reads: FakePageReads) -> None:
    reads.publish("annual-report", "<html></html>")
    for headers in (edge(secret=None), edge(secret="wrong")):
        response = client.get("/annual-report", headers=headers)
        assert response.status_code == 403
        assert response.content == b""


def test_forged_public_host_without_secret_is_403(client: TestClient) -> None:
    response = client.get("/annual-report", headers={"X-Clue-Public-Host": HOST})
    assert response.status_code == 403


def test_malformed_public_host_is_400(client: TestClient) -> None:
    assert client.get("/annual-report", headers=edge("not a host")).status_code == 400
    assert client.get("/annual-report", headers=edge("")).status_code == 400


def test_dev_mode_reads_the_host_header(dev_client: TestClient, reads: FakePageReads) -> None:
    reads.publish("annual-report", "<html>dev</html>")
    response = dev_client.get("/annual-report", headers={"Host": f"{HOST}:8040"})
    assert response.status_code == 200 and response.text == "<html>dev</html>"


def test_trust_and_secret_cannot_both_be_live() -> None:
    with pytest.raises(ValueError):
        EdgeGate(secret="x", trust_host_header=True)
    with pytest.raises(ValueError):
        EdgeGate(secret=None, trust_host_header=False)
```

`tests/page_origin/test_routes.py`:

```python
from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from clue_design.publishes import DELIVERY_CSP_HEADER

from .conftest import HOST, WS, FakePageReads, edge


def test_serves_the_active_publish_with_the_exact_headers(client: TestClient, reads: FakePageReads) -> None:
    reads.publish("annual-report", "<html>hi</html>")
    response = client.get("/annual-report", headers=edge())
    assert response.status_code == 200
    assert response.text == "<html>hi</html>"
    digest = hashlib.sha256(b"<html>hi</html>").hexdigest()
    assert response.headers["cache-control"] == "public, max-age=60, must-revalidate"
    assert response.headers["etag"] == f'"sha256-{digest}"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["content-security-policy"] == DELIVERY_CSP_HEADER
    assert "x-robots-tag" not in response.headers
    assert "access-control-allow-origin" not in response.headers


def test_noindex_pages_carry_x_robots_tag(client: TestClient, reads: FakePageReads) -> None:
    reads.publish("abm-acme", "<html>x</html>", noindex=True)
    assert client.get("/abm-acme", headers=edge()).headers["x-robots-tag"] == "noindex"


def test_manifest(client: TestClient, reads: FakePageReads) -> None:
    reads.publish("annual-report", "<html>hi</html>")
    response = client.get("/annual-report/manifest.json", headers=edge())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["slug"] == "annual-report"
    assert response.headers["cache-control"] == "public, max-age=60, must-revalidate"


def test_unknown_hostname_pending_hostname_and_unknown_slug_are_404(
    client: TestClient, reads: FakePageReads
) -> None:
    reads.publish("annual-report", "<html>hi</html>")
    assert client.get("/annual-report", headers=edge("nobody.example")).status_code == 404
    assert client.get("/missing", headers=edge()).status_code == 404
    page = client.get("/missing", headers=edge())
    assert "<title>Not found</title>" in page.text
    assert WS not in page.text and HOST not in page.text
    assert page.headers["x-robots-tag"] == "noindex"


def test_root_and_unknown_slug_redirect_to_the_fallback_url(client: TestClient, reads: FakePageReads) -> None:
    reads.fallbacks[WS] = "https://www.acme.com"
    for path in ("/", "/missing"):
        response = client.get(path, headers=edge(), follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "https://www.acme.com"
    reads.fallbacks.clear()
    assert client.get("/", headers=edge()).status_code == 404


def test_slug_pattern_is_enforced_before_any_lookup(client: TestClient, reads: FakePageReads) -> None:
    reads.publish("annual-report", "<html>hi</html>")
    for bad in ("/Annual-Report", "/-lead", "/" + "a" * 73, "/annual_report"):
        assert client.get(bad, headers=edge()).status_code == 404


def test_favicon_404_when_none_and_served_when_set(client: TestClient, reads: FakePageReads) -> None:
    assert client.get("/favicon.ico", headers=edge()).status_code == 404
    reads.favicons[WS] = ("image/png", b"\x89PNG")
    response = client.get("/favicon.ico", headers=edge())
    assert response.status_code == 200 and response.content == b"\x89PNG"
    assert response.headers["cache-control"] == "public, max-age=300"


def test_publish_assets_are_integrity_checked_and_immutable(client: TestClient, reads: FakePageReads) -> None:
    data = b"console.log(1)"
    digest = hashlib.sha256(data).hexdigest()
    reads.assets[(WS, digest)] = ("text/javascript; charset=utf-8", data)
    response = client.get(f"/p-assets/{digest}.js", headers=edge())
    assert response.status_code == 200 and response.content == data
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["etag"] == f'"sha256-{digest}"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in response.headers
    assert client.get(f"/p-assets/{digest}.css", headers=edge()).status_code == 404  # ext mismatch
    assert client.get(f"/p-assets/{'0' * 64}.js", headers=edge()).status_code == 404
    assert client.get("/p-assets/not-a-digest.js", headers=edge()).status_code == 404


def test_asset_store_is_workspace_unscoped(client: TestClient, reads: FakePageReads) -> None:
    data = b"font-bytes"
    digest = hashlib.sha256(data).hexdigest()
    reads.public[digest] = ("font/woff2", data)
    response = client.get(f"/asset-store/{digest}", headers=edge())
    assert response.status_code == 200 and response.headers["content-type"] == "font/woff2"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/asset-store/zzz", headers=edge()).status_code == 404


def test_only_get_and_head(client: TestClient, reads: FakePageReads) -> None:
    reads.publish("annual-report", "<html>hi</html>")
    assert client.post("/annual-report", headers=edge()).status_code == 405
    head = client.head("/annual-report", headers=edge())
    assert head.status_code == 200 and head.content == b""
```

- [ ] **Step 3: Run to verify failure** — `uv run pytest tests/page_origin -q` → `ModuleNotFoundError` for `clue_page_origin.app`.

- [ ] **Step 4: Implement `reads.py`**

```python
"""What the origin reads, behind one protocol so route tests run on fakes (spec §10)."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from clue_db import ConnFactory, transaction
from clue_design.errors import DesignNotFoundError
from clue_design.publishes import get_web_publish
from clue_design.storage import read_design_blob, read_public_design_blob
from clue_spine.hostnames import resolve_active_hostname
from clue_storage import StorageBackend


class ServedPublish(BaseModel):
    """The slice of an active publish the origin serves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    html: str
    html_digest: str
    manifest_json: str
    manifest_digest: str
    noindex: bool


class PageReads(Protocol):
    async def workspace_for_hostname(self, hostname: str) -> str | None: ...
    async def active_publish(self, workspace_id: str, slug: str) -> ServedPublish | None: ...
    async def fallback_url(self, workspace_id: str) -> str | None: ...
    async def favicon(self, workspace_id: str) -> tuple[str, bytes] | None: ...
    async def publish_asset(self, workspace_id: str, sha256: str) -> tuple[str, bytes] | None: ...
    async def public_blob(self, sha256: str) -> tuple[str, bytes] | None: ...


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DbPageReads:
    """The production reads over the registry, the publish DAL and the blob store."""

    def __init__(self, storage: StorageBackend, *, conn_factory: ConnFactory = transaction) -> None:
        self._storage = storage
        self._conn_factory = conn_factory

    async def workspace_for_hostname(self, hostname: str) -> str | None:
        async with self._conn_factory() as conn:
            return await resolve_active_hostname(conn, hostname)

    async def active_publish(self, workspace_id: str, slug: str) -> ServedPublish | None:
        async with self._conn_factory() as conn:
            publish = await get_web_publish(conn, workspace_id=workspace_id, slug=slug)
        if publish is None or publish.get("status") != "active":
            return None
        manifest = publish.get("manifest")
        if not isinstance(manifest, dict):
            return None
        html = str(publish["html"])
        manifest_json = json.dumps(manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        return ServedPublish(
            html=html,
            html_digest=str(publish.get("html_digest") or _sha(html)),
            manifest_json=manifest_json,
            manifest_digest=str(publish.get("manifest_digest") or _sha(manifest_json)),
            noindex=manifest.get("robots") == "noindex",
        )

    async def fallback_url(self, workspace_id: str) -> str | None:
        # S2 reads workspace_pages_settings.fallback_url here; S1 has no writer, so no fallback.
        return None

    async def favicon(self, workspace_id: str) -> tuple[str, bytes] | None:
        # S2 reads workspace_pages_settings.favicon_sha256 → read_design_blob here.
        return None

    async def publish_asset(self, workspace_id: str, sha256: str) -> tuple[str, bytes] | None:
        async with self._conn_factory() as conn:
            try:
                return await read_design_blob(
                    conn, self._storage, workspace_id=workspace_id, sha256=sha256
                )
            except DesignNotFoundError:
                return None

    async def public_blob(self, sha256: str) -> tuple[str, bytes] | None:
        async with self._conn_factory() as conn:
            try:
                return await read_public_design_blob(conn, self._storage, sha256=sha256)
            except DesignNotFoundError:
                return None
```

- [ ] **Step 5: Implement `edge.py`**

```python
"""The edge gate: only the Cloudflare Worker may name the public hostname (spec §5.2)."""

from __future__ import annotations

import hmac

from fastapi import Request

from clue_obs import get_logger
from clue_spine.hostnames import is_valid_hostname

PUBLIC_HOST_HEADER = "x-clue-public-host"
EDGE_AUTH_HEADER = "x-clue-edge-auth"
log = get_logger("clue_page_origin.edge")


class EdgeRefused(Exception):
    """403 with an empty body (never echo the presented header value)."""


class BadPublicHost(Exception):
    """400: the claimed public host is not a hostname."""


class EdgeGate:
    def __init__(self, *, secret: str | None, trust_host_header: bool) -> None:
        if trust_host_header and secret:
            raise ValueError(
                "CLUE_PAGES_TRUST_HOST_HEADER=true cannot be combined with CLUE_PAGES_EDGE_SECRET"
            )
        if not trust_host_header and not secret:
            raise ValueError(
                "CLUE_PAGES_EDGE_SECRET is required unless CLUE_PAGES_TRUST_HOST_HEADER=true (dev only)"
            )
        self._secret = secret
        self._trust_host_header = trust_host_header

    def public_host(self, request: Request) -> str:
        if self._trust_host_header:
            raw = request.headers.get("host", "")
            host = raw.rsplit(":", 1)[0] if ":" in raw and not raw.endswith("]") else raw
        else:
            presented = request.headers.get(EDGE_AUTH_HEADER)
            assert self._secret is not None
            if presented is None or not hmac.compare_digest(
                presented.encode("utf-8"), self._secret.encode("utf-8")
            ):
                log.warning(
                    "pages.edge.refused",
                    client=request.client.host if request.client else None,
                    claimed_host=request.headers.get(PUBLIC_HOST_HEADER),
                )
                raise EdgeRefused()
            host = request.headers.get(PUBLIC_HOST_HEADER, "")
        host = host.strip().lower().rstrip(".")
        if not is_valid_hostname(host):
            raise BadPublicHost()
        return host
```

- [ ] **Step 6: Implement `routes.py` and `app.py`**

`routes.py`:

```python
"""The origin's routes (spec §5.2). GET/HEAD only; the edge gate runs before every route but /healthz."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from clue_design.publishes import PublishAssetMismatch, check_publish_asset, delivery_csp

from clue_page_origin.edge import EdgeGate
from clue_page_origin.reads import PageReads

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,71}$")
ASSET_NAME = re.compile(r"^([0-9a-f]{64})\.(js|css|html)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

NOT_FOUND_HTML = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<meta name=\"robots\" content=\"noindex\"><title>Not found</title></head>"
    "<body><h1>404</h1><p>No published page at this address.</p></body></html>"
)
_IMMUTABLE = "public, max-age=31536000, immutable"
_SHORT = "public, max-age=60, must-revalidate"


def _not_found() -> HTMLResponse:
    return HTMLResponse(
        NOT_FOUND_HTML,
        status_code=404,
        headers={"X-Robots-Tag": "noindex", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


def _page_headers(digest: str, *, noindex: bool) -> dict[str, str]:
    headers = {
        "Cache-Control": _SHORT,
        "ETag": f'"sha256-{digest}"',
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": delivery_csp(),
    }
    if noindex:
        headers["X-Robots-Tag"] = "noindex"
    return headers


def _asset_headers(digest: str) -> dict[str, str]:
    return {"Cache-Control": _IMMUTABLE, "ETag": f'"sha256-{digest}"', "X-Content-Type-Options": "nosniff"}


def build_router(reads: PageReads, gate: EdgeGate) -> APIRouter:
    router = APIRouter()

    async def workspace(request: Request) -> str | None:
        return await reads.workspace_for_hostname(gate.public_host(request))

    async def _miss(workspace_id: str) -> Response:
        fallback = await reads.fallback_url(workspace_id)
        if fallback:
            return RedirectResponse(fallback, status_code=302)
        return _not_found()

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/")
    async def root(workspace_id: str | None = Depends(workspace)) -> Response:
        if workspace_id is None:
            return _not_found()
        return await _miss(workspace_id)

    @router.get("/favicon.ico")
    async def favicon(workspace_id: str | None = Depends(workspace)) -> Response:
        if workspace_id is None:
            return Response(status_code=404)
        found = await reads.favicon(workspace_id)
        if found is None:
            return Response(status_code=404)
        media_type, data = found
        return Response(content=data, media_type=media_type, headers={"Cache-Control": "public, max-age=300"})

    @router.get("/p-assets/{asset_name}")
    async def publish_asset(asset_name: str, workspace_id: str | None = Depends(workspace)) -> Response:
        match = ASSET_NAME.fullmatch(asset_name)
        if workspace_id is None or match is None:
            return Response(status_code=404)
        digest, extension = match.groups()
        found = await reads.publish_asset(workspace_id, digest)
        if found is None:
            return Response(status_code=404)
        media_type, data = found
        try:
            served_type = check_publish_asset(data=data, media_type=media_type, digest=digest, extension=extension)
        except PublishAssetMismatch:
            return Response(status_code=404)
        return Response(content=data, media_type=served_type, headers=_asset_headers(digest))

    @router.get("/asset-store/{digest}")
    async def asset_store(digest: str, workspace_id: str | None = Depends(workspace)) -> Response:
        if workspace_id is None or not SHA256.fullmatch(digest):
            return Response(status_code=404)
        found = await reads.public_blob(digest)
        if found is None:
            return Response(status_code=404)
        media_type, data = found
        return Response(content=data, media_type=media_type, headers=_asset_headers(digest))

    @router.get("/{slug}/manifest.json")
    async def manifest(slug: str, workspace_id: str | None = Depends(workspace)) -> Response:
        if workspace_id is None or not SLUG.fullmatch(slug):
            return _not_found()
        publish = await reads.active_publish(workspace_id, slug)
        if publish is None:
            return await _miss(workspace_id)
        return Response(
            content=publish.manifest_json,
            media_type="application/json",
            headers=_page_headers(publish.manifest_digest, noindex=publish.noindex),
        )

    @router.get("/{slug}")
    async def page(slug: str, workspace_id: str | None = Depends(workspace)) -> Response:
        if workspace_id is None or not SLUG.fullmatch(slug):
            return _not_found()
        publish = await reads.active_publish(workspace_id, slug)
        if publish is None:
            return await _miss(workspace_id)
        return HTMLResponse(publish.html, headers=_page_headers(publish.html_digest, noindex=publish.noindex))

    return router
```

`app.py`:

```python
"""App factory. ``lifespan`` is injected so tests build the app with fakes and no database."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI, Request, Response

from clue_page_origin.edge import BadPublicHost, EdgeGate, EdgeRefused
from clue_page_origin.reads import PageReads
from clue_page_origin.routes import build_router

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_page_origin_app(*, reads: PageReads, gate: EdgeGate, lifespan: Lifespan | None = None) -> FastAPI:
    app = FastAPI(title="Clue public page origin", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    @app.middleware("http")
    async def _get_head_only(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method not in ("GET", "HEAD"):
            return Response(status_code=405, headers={"Allow": "GET, HEAD"})
        return await call_next(request)

    @app.exception_handler(EdgeRefused)
    async def _refused(_request: Request, _exc: EdgeRefused) -> Response:
        return Response(status_code=403)

    @app.exception_handler(BadPublicHost)
    async def _bad_host(_request: Request, _exc: BadPublicHost) -> Response:
        return Response(status_code=400)

    app.include_router(build_router(reads, gate))
    return app
```

FastAPI's `@app.get` also answers HEAD, so the `test_only_get_and_head` HEAD case passes without extra routes. If mypy complains about the middleware signature, type it as `Callable[[Request], Awaitable[Response]]` for `call_next` and drop the ignore.

- [ ] **Step 7: Run the tests**

`uv run pytest tests/page_origin -q` → all PASS. Iterate until green.

- [ ] **Step 8: Gates and commit**

```bash
uv run ruff format platform/page_origin tests/page_origin && uv run ruff check platform/page_origin tests/page_origin
git add platform/page_origin tests/page_origin uv.lock
git commit -m "page-origin: hostname-aware public page service with edge gate and route tests"
```

(mypy/import-linter registration of the new package happens in Task 8.)

---

### Task 8: Page origin entrypoint, Dockerfile, dev stack port 8040, static gates

**Files:**
- Create: `platform/page_origin/clue_page_origin/main.py`, `platform/page_origin/Dockerfile.railway`
- Modify: `pyproject.toml` (root: ruff `known-first-party`, mypy `files`/`mypy_path`, importlinter `root_packages` + new contract), `scripts/dev_stack.sh`, `DEV_STACK.md`, `platform/api/clue_api/projections_main.py` (startup suffix warning)
- Test: `tests/page_origin/test_main.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/page_origin/test_main.py
from __future__ import annotations

import pytest

from clue_config import Secrets, Settings
from clue_page_origin.main import build_gate


def test_build_gate_refuses_trust_with_a_secret() -> None:
    settings = Settings(_env_file=None, pages_trust_host_header=True)
    secrets = Secrets(_env_file=None, pages_edge_secret="s")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        build_gate(settings, secrets)


def test_build_gate_dev_and_prod_shapes() -> None:
    dev = build_gate(Settings(_env_file=None, pages_trust_host_header=True), Secrets(_env_file=None))  # type: ignore[call-arg]
    assert dev is not None
    prod = build_gate(Settings(_env_file=None), Secrets(_env_file=None, pages_edge_secret="s"))  # type: ignore[call-arg]
    assert prod is not None
```

Run: `uv run pytest tests/page_origin/test_main.py -q` → `ImportError`.

- [ ] **Step 2: Write `main.py`**

```python
"""Production entrypoint: ``python -m clue_page_origin.main`` (Railway) or
``uvicorn --factory clue_page_origin.main:build_application`` (dev stack). No app is built at import
time, so importing this module never reads settings or opens a database."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

import clue_obs
from clue_config import Secrets, Settings
from clue_db import db_lifespan, transaction
from clue_obs import get_logger
from clue_page_origin.app import create_page_origin_app
from clue_page_origin.edge import EdgeGate
from clue_page_origin.reads import DbPageReads
from clue_spine.hostnames import system_hostnames_off_suffix
from clue_storage import storage_from_settings

log = get_logger("clue_page_origin.main")


def build_gate(settings: Settings, secrets: Secrets) -> EdgeGate:
    secret = secrets.pages_edge_secret.get_secret_value() if secrets.pages_edge_secret else None
    return EdgeGate(secret=secret, trust_host_header=settings.pages_trust_host_header)


def build_application(settings: Settings | None = None, secrets: Secrets | None = None) -> FastAPI:
    resolved = settings if settings is not None else Settings()
    resolved_secrets = secrets if secrets is not None else Secrets()
    gate = build_gate(resolved, resolved_secrets)
    reads = DbPageReads(storage_from_settings(resolved, resolved_secrets))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        clue_obs.setup()
        async with db_lifespan():
            async with transaction() as conn:
                off = await system_hostnames_off_suffix(conn, resolved.pages_system_suffix)
            if off:
                log.warning(
                    "pages.system_hostnames_off_suffix",
                    suffix=resolved.pages_system_suffix,
                    count=len(off),
                    sample=off[:5],
                )
            log.info("page_origin.ready", suffix=resolved.pages_system_suffix, trust_host_header=resolved.pages_trust_host_header)
            yield

    return create_page_origin_app(reads=reads, gate=gate, lifespan=lifespan)


if __name__ == "__main__":
    port = int(os.environ.get("PORT") or Settings().pages_origin_port)
    uvicorn.run(
        "clue_page_origin.main:build_application", factory=True, host="0.0.0.0", port=port, log_level="info"
    )
```

Run the test again → PASS. Importing `main` builds nothing (factory pattern), so the test environment needs no `CLUE_PAGES_*` posture; a misconfigured deployment still fails loud at process start, inside `build_application`.

- [ ] **Step 3: Register the package in the static gates**

In root `pyproject.toml`: add `"clue_page_origin"` to ruff `known-first-party`; add `"platform/page_origin/clue_page_origin"` to `[tool.mypy] files` and `platform/page_origin` to `mypy_path`; add `"clue_page_origin"` to `[tool.importlinter] root_packages`; add the contract:

```toml
# Custom-domain publishing S1 — the page origin reads the spine, the design DAL and storage; never a
# capability plane, the research subsystem, or the two API apps.
[[tool.importlinter.contracts]]
name = "page origin imports only core + config + db + obs + spine + design + storage"
type = "forbidden"
source_modules = ["clue_page_origin"]
forbidden_modules = ["clue_research", "clue_api", "clue_auth", "clue_gateway", "clue_locks", "clue_memory", "clue_content", "clue_toolbelt", "clue_agents", "clue_execution", "clue_fleet", "clue_projections"]
```

Also the contract "libs never import the subsystem" and the design contract stay as they are (the origin is a `platform/*` package, not a lib). Run `uv run mypy && uv run lint-imports` → both clean.

- [ ] **Step 4: Dockerfile**

`platform/page_origin/Dockerfile.railway` (built from the repo root, `RAILWAY_DOCKERFILE_PATH=/platform/page_origin/Dockerfile.railway`):

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace

# The uv workspace manifest + every member the resolver must see (explicit members in the root
# pyproject must exist on disk). Python packages only; no frontend, crates or wasm.
COPY pyproject.toml uv.lock alembic.ini ./
COPY alembic ./alembic
COPY libs ./libs
COPY platform ./platform
COPY subsystems/research ./subsystems/research
COPY subsystems/memory ./subsystems/memory
COPY subsystems/content ./subsystems/content
COPY subsystems/design ./subsystems/design
COPY subsystems/clue-design/apps/api ./subsystems/clue-design/apps/api
COPY subsystems/clue-design/apps/agent_runtime ./subsystems/clue-design/apps/agent_runtime
COPY subsystems/clue-design/packages ./subsystems/clue-design/packages

RUN uv sync --frozen --no-dev --package clue-page-origin

EXPOSE 8040
CMD ["uv", "run", "--no-sync", "python", "-m", "clue_page_origin.main"]
```

Verify locally: `docker build -f platform/page_origin/Dockerfile.railway -t clue-page-origin .` must succeed (if the root pyproject names a README or other file the resolver needs, COPY it too). Then
`docker run --rm -e CLUE_DATABASE_URL=<lane DSN reachable from Docker> -e CLUE_PAGES_TRUST_HOST_HEADER=true -e CLUE_STORAGE_BACKEND=fs -e CLUE_STORAGE_FS_ROOT=/tmp/x -p 8041:8040 clue-page-origin` and `curl -s localhost:8041/healthz` → `{"status":"ok"}`. Record any COPY adjustments in the runbook (Task 14).

- [ ] **Step 5: Dev stack**

In `scripts/dev_stack.sh`: add `8040  page origin (clue_page_origin)` to the port-map comment; add to `PLATFORM_ENV=( ... )`:

```bash
  CLUE_PAGES_SYSTEM_SUFFIX=pages.localhost
  CLUE_PAGES_PUBLIC_SCHEME=http
  CLUE_PAGES_PUBLIC_PORT=8040
  CLUE_PAGES_TRUST_HOST_HEADER=true
  CLUE_PAGES_EDGE_SECRET=
```

Add a `start_page_origin` function next to `start_platform_api`:

```bash
start_page_origin() {  # public page origin — serves http://<label>.pages.localhost:8040/<slug>
  ( cd "$ROOT" && env "${PLATFORM_ENV[@]}" \
      "$ROOT/.venv/bin/python" -m uvicorn --factory clue_page_origin.main:build_application --port 8040 \
      > "${LOG}_page_origin.log" 2>&1 & )
}
```

Call it in `up` right after `start_platform_api`; add `pkill -f "$ROOT/.venv/bin/python -m uvicorn --factory clue_page_origin.main:build_application" 2>/dev/null || true` to `down` and to `restart-api`; add it to `status`. In `DEV_STACK.md`, add the row `| 8040 | page origin (\`clue_page_origin.main:build_application\`, uvicorn factory) | Serves published pages at \`http://<label>.pages.localhost:8040/<slug>\`; browsers resolve \`*.localhost\` to loopback with no DNS setup. |` to the port map, and a sentence under the `.env` section that the stack passes `CLUE_PAGES_TRUST_HOST_HEADER=true` and the `pages.localhost` suffix per process (the `.env` keeps the production defaults).

Smoke: `./scripts/dev_stack_san_salvador.sh up` (or the wrapper for this lane), then `curl -s -H 'Host: x.pages.localhost' localhost:8040/nothing -o /dev/null -w '%{http_code}\n'` → `404`; `down`.

- [ ] **Step 6: Platform API startup warning**

In `platform/api/clue_api/projections_main.py`, find where `startup_check=` is composed for `create_projections_app` and wrap it so it also runs:

```python
async def _warn_on_hostname_suffix_drift() -> None:
    async with transaction() as conn:
        off = await system_hostnames_off_suffix(conn, settings.pages_system_suffix)
    if off:
        log.warning("pages.system_hostnames_off_suffix", suffix=settings.pages_system_suffix, count=len(off), sample=off[:5])
```

(import `system_hostnames_off_suffix` from `clue_spine.hostnames`; compose it as `async def startup(): await existing(); await _warn_on_hostname_suffix_drift()` if a check already exists, else pass it directly).

- [ ] **Step 7: Gates and commit**

```bash
uv run ruff format platform scripts tests/page_origin && uv run ruff check platform tests/page_origin && uv run mypy && uv run lint-imports && uv run pytest tests/page_origin -q
git add platform/page_origin pyproject.toml scripts/dev_stack.sh DEV_STACK.md platform/api/clue_api/projections_main.py tests/page_origin
git commit -m "page-origin: entrypoint, Railway Dockerfile, dev stack on 8040, static gates"
```

---

### Task 9: Design API — host-independent publish package (`web_export.py`)

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/web_export.py` (`_delivery_csp` ~1264, `build_publish_package` ~1487, `build_publish_html` ~1683, `resolve_publish_asset` ~238, constants ~63-75)
- Modify: `subsystems/clue-design/apps/api/pyproject.toml` (add `"clue-spine"`, `"clue-config"` to dependencies + `[tool.uv.sources]`)
- Test: `subsystems/clue-design/apps/api/tests/test_web_export.py` (new test `test_publish_package_is_host_independent`), `tests/test_web_fragment_export.py:905-920` (CSP test update)

**Interfaces:**
- Produces: `build_publish_package(core, repo, document, *, blobs, slug, public_origin: str, workspace_id: str, node_bin="node", noindex=False) -> PublishPackage`
  (`public_base` is gone); `build_publish_html(..., public_origin, ...)`; `_delivery_csp(*, meta: bool = False)`.
- Consumes: `clue_design.publishes.delivery_csp`, `check_publish_asset`, `PUBLISH_ASSET_MEDIA_TYPES`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_web_export.py`; reuse that file's `seed_document`/`client` fixtures and look at how existing tests obtain `app.state.core` — `client.app.state.core` — and a repository/blob store — `HybridRepository()` and `make_blob_store(client.app)` from `conftest`)

```python
def test_publish_package_is_host_independent(client: TestClient) -> None:
    from lumen_api.design_store import HybridRepository
    from lumen_api.web_export import build_publish_package

    from .conftest import make_blob_store

    document = get_document(client, seed_document(client)["id"])
    repo = HybridRepository()
    package = build_publish_package(
        client.app.state.core,
        repo,
        document,
        blobs=make_blob_store(client.app),
        slug="host-free",
        public_origin="https://acme.pages.test",
        workspace_id=repo.workspace_id,
        node_bin=client.app.state.web_export_node_bin,
    )
    html = package.html
    assert "/w/" not in html
    assert '<link rel="canonical"' not in html
    assert 'property="og:url"' not in html
    assert '<link rel="icon" href="/favicon.ico">' in html
    assert '<link rel="lumen-publish-manifest" href="/host-free/manifest.json">' in html
    # the only absolute URLs allowed are og:image on the system origin
    import re
    absolute = re.findall(r'(?:href|src|content)="(https?://[^"]+)"', html)
    assert all(url.startswith("https://acme.pages.test/asset-store/") for url in absolute), absolute
    assert package.manifest["canonical_url"] == "https://acme.pages.test/host-free"
    for asset_url in re.findall(r'"(/p-assets/[0-9a-f]{64}\.(?:js|css|html))"', html):
        assert asset_url.startswith("/p-assets/")
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html)
    assert csp is not None and "http" not in csp.group(1) and "frame-ancestors" not in csp.group(1)
```

Run: `( set -a; source ../../../../.env; set +a; ../../../../.venv/bin/python -m pytest tests/test_web_export.py -k host_independent -q )` (from `subsystems/clue-design/apps/api`) → FAIL with `TypeError: ... unexpected keyword argument 'public_origin'`.

- [ ] **Step 2: Change `web_export.py`**

1. Replace `_delivery_csp`:

```python
def _delivery_csp(*, meta: bool = False) -> str:
    """The published page's CSP — one home in ``clue_design.publishes`` (custom-domain publishing
    §6.2), shared with the page origin's header. Assets are same-origin by construction now, so
    there is no origin allow-list: ``'self'`` covers ``/p-assets`` and ``/asset-store`` on whichever
    hostname served the page."""
    return delivery_csp(meta=meta)
```

with `from clue_design.publishes import PUBLISH_ASSET_MEDIA_TYPES, check_publish_asset, delivery_csp` in the imports. Delete the module-level `PUBLISH_ASSET_MEDIA_TYPES` dict (use the imported one) and reduce `resolve_publish_asset` to:

```python
def resolve_publish_asset(blobs: DesignBlobStore, digest: str, extension: str) -> Tuple[bytes, str]:
    """Read and integrity-check one immutable publish asset (the check itself lives in
    ``clue_design.publishes.check_publish_asset``, shared with the page origin)."""
    if not PUBLISH_ASSET_PATTERN.fullmatch(digest):
        raise WebExportError("invalid publish asset digest")
    try:
        media_type, data = blobs.read_blob(digest)
    except (NotFoundError, ValueError) as error:
        raise WebExportError("publish asset is missing") from error
    try:
        served = check_publish_asset(data=data, media_type=media_type, digest=digest, extension=extension)
    except PublishAssetMismatch as error:
        raise WebExportError(str(error)) from error
    return data, served
```

(import `PublishAssetMismatch` too; if Task 11 leaves `resolve_publish_asset` with no callers, delete it there.)

2. In `build_publish_package`: rename the parameter `public_base: str` → `public_origin: str`; delete `base = public_base.rstrip("/")` and `public_prefix = ...`; set `origin = public_origin.rstrip("/")`;
   `asset_url_for=(lambda digest, extension: f"/p-assets/{digest}.{extension}")`;
   `og_image = f"{origin}/asset-store/{og_source.digest}" if og_source is not None else None`;
   `head = _seo_snippet(title=document["title"], description=_seo_description(web_doc, document["title"]), og_image=og_image)` (no `canonical`, no `og_url`);
   immediately after that line add `head += '<link rel="icon" href="/favicon.ico">\n'`;
   manifest `"canonical_url": f"{origin}/{slug}"`;
   CSP meta `_delivery_csp(meta=True)`;
   manifest link `href=f"/{slug}/manifest.json"`.
   Update the docstring paragraph about `/w/{workspace_id}` to say: every URL is root-relative except `og:image`, which unfurlers require absolute and which points at the always-live system hostname (custom-domain publishing §6.1).
3. `build_publish_html`: same rename, pass through.
4. In `pyproject.toml` of the API app add `"clue-spine",` and `"clue-config",` to `dependencies` and `clue-spine = { workspace = true }` / `clue-config = { workspace = true }` under `[tool.uv.sources]`; run `uv sync --all-packages`.

- [ ] **Step 3: Update the CSP test** in `tests/test_web_fragment_export.py` (~line 912): replace the two `_delivery_csp("https://pages.example"...)` calls with `_delivery_csp()` / `_delivery_csp(meta=True)` and change the assertions to: header contains `frame-ancestors 'self'`, meta does not, both contain `script-src 'self' 'unsafe-inline' data:`, neither contains `pages.example`.

- [ ] **Step 4: Run the two files**

`( set -a; source ../../../../.env; set +a; ../../../../.venv/bin/python -m pytest tests/test_web_export.py -k "host_independent" tests/test_web_fragment_export.py -k "csp" -q )` → PASS. (Other tests in these files still call the old signature through `main.py`; they go green in Task 10/11. Do not run the whole files yet.)

- [ ] **Step 5: Commit**

```bash
git add subsystems/clue-design/apps/api/lumen_api/web_export.py subsystems/clue-design/apps/api/pyproject.toml subsystems/clue-design/apps/api/tests/test_web_export.py subsystems/clue-design/apps/api/tests/test_web_fragment_export.py uv.lock
git commit -m "design-api: host-independent publish package (root-relative assets, no canonical/og:url, shared CSP)"
```

---

### Task 10: Design API — system-origin helper, tool input, repository reads, routes, response shape

**Files:**
- Create: `subsystems/clue-design/apps/api/lumen_api/public_pages.py`
- Modify: `lumen_api/design_store.py` (`_ensure_workspace` ~line 210; `HybridRepository` methods near `get_web_publish`), `lumen_api/toolbelt/publishes.py` (`publish_web_document` 91-135, `PublishWebDocumentInput` 175-192, `run` 266-278), `lumen_api/main.py` (`_publish_web` 4302, `publish_web_document` 4359-4398, `get_web_publish_state` 4400-4420, `_process_web_batch` + its two call sites 5424/5464 and row `url` 5286, `public_publish_path` 7387)
- Test: `tests/test_abm_batch_publish.py` and `tests/test_web_batches.py` (`row["url"]` assertions), `tests/test_web_export.py` (`body["url"]` at ~585), `tests/test_write_path_governance.py` / `tests/test_design_toolbelt.py` (any `public_base` in tool inputs), new `tests/test_public_pages.py`

**Interfaces:**
- Produces (`lumen_api/public_pages.py`): `system_public_origin(repository) -> str`, `custom_public_origin(repository) -> str | None`,
  `public_publish_url(repository, slug) -> str`, `custom_publish_url(repository, slug) -> str | None`.
- `HybridRepository.system_hostname() -> str | None`, `HybridRepository.active_custom_hostname() -> str | None`.
- `PublishWebDocumentInput` fields: `document_id, slug, noindex` (no `public_base`).
- Publish responses gain `custom_url`, `public_origin`, `custom_origin`; `url` becomes absolute.

- [ ] **Step 1: Write the failing tests**

`tests/test_public_pages.py`:

```python
"""Custom-domain publishing S1 Task 10: publish URLs come from the hostname registry, not the request."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lumen_api.design_store import HybridRepository
from lumen_api.public_pages import public_publish_url, system_public_origin

from .conftest import make_client
from .test_web_export import seed_document  # the existing seeding helper


@pytest.fixture
def client(tmp_path, design_storage):
    from lumen_api.main import create_app

    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def test_every_dev_workspace_gets_a_system_hostname(client: TestClient, workspace_id: str, monkeypatch) -> None:
    monkeypatch.setenv("CLUE_PAGES_SYSTEM_SUFFIX", "pages.test")
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_SCHEME", "http")
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_PORT", "8040")
    seed_document(client)  # any request scaffolds the workspace through _ensure_workspace
    repo = HybridRepository()
    hostname = repo.system_hostname()
    assert hostname == f"{workspace_id.replace('_', '-')}.pages.test"
    assert system_public_origin(repo) == f"http://{hostname}:8040"
    assert public_publish_url(repo, "annual-report") == f"http://{hostname}:8040/annual-report"
    assert repo.active_custom_hostname() is None


def test_publish_responses_carry_absolute_urls_and_origins(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("CLUE_PAGES_SYSTEM_SUFFIX", "pages.test")
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_SCHEME", "https")
    monkeypatch.delenv("CLUE_PAGES_PUBLIC_PORT", raising=False)
    document = seed_document(client)
    state = client.get(f"/documents/{document['id']}/web/publish").json()
    assert state["published"] is False
    assert state["public_origin"].endswith(".pages.test") and state["public_origin"].startswith("https://")
    assert state["custom_origin"] is None
    published = client.post(f"/documents/{document['id']}/web/publish", json={"slug": "hello"}).json()
    assert published["url"] == f"{state['public_origin']}/hello"
    assert published["custom_url"] is None
    assert published["public_origin"] == state["public_origin"]
    again = client.get(f"/documents/{document['id']}/web/publish").json()
    assert again["url"] == published["url"] and again["custom_url"] is None
```

Run (from the api dir): `( set -a; source ../../../../.env; set +a; ../../../../.venv/bin/python -m pytest tests/test_public_pages.py -q )` → FAIL (`ModuleNotFoundError: lumen_api.public_pages`).

- [ ] **Step 2: `public_pages.py`**

```python
"""Public page URLs for a workspace — from the hostname registry, never from ``request.base_url``.

Custom-domain publishing §6.1/§6.3. The system hostname is allocated with the workspace
(``clue_spine.hostnames``) and is always live; a custom hostname appears here only once the S2
control plane has walked it to ``active``. Scheme and port come from ``CLUE_PAGES_PUBLIC_SCHEME`` /
``CLUE_PAGES_PUBLIC_PORT`` (dev: http + 8040).
"""

from __future__ import annotations

from clue_config import Settings
from clue_spine.hostnames import public_origin

from .design_store import HybridRepository
from .web_export import WebExportError


def system_public_origin(repository: HybridRepository) -> str:
    hostname = repository.system_hostname()
    if hostname is None:
        raise WebExportError(
            f"workspace {repository.workspace_id!r} has no system hostname; "
            "run `make pages-backfill-hostnames`"
        )
    settings = Settings()
    return public_origin(hostname, scheme=settings.pages_public_scheme, port=settings.pages_public_port)


def custom_public_origin(repository: HybridRepository) -> str | None:
    hostname = repository.active_custom_hostname()
    if hostname is None:
        return None
    return public_origin(hostname, scheme="https", port=None)  # customer hostnames terminate at Cloudflare


def public_publish_url(repository: HybridRepository, slug: str) -> str:
    return f"{system_public_origin(repository)}/{slug}"


def custom_publish_url(repository: HybridRepository, slug: str) -> str | None:
    origin = custom_public_origin(repository)
    return None if origin is None else f"{origin}/{slug}"
```

- [ ] **Step 3: `design_store.py`**

In `_ensure_workspace`, after the `INSERT INTO workspace ... ON CONFLICT DO NOTHING` execute and before recording the id in `_ensured_workspaces`, add:

```python
    await ensure_system_hostname(
        conn, workspace_id=workspace_id, name=workspace_id, suffix=Settings().pages_system_suffix
    )
```

with `from clue_config import Settings` and `from clue_spine.hostnames import active_custom_hostname, ensure_system_hostname, system_hostname` (alias the DAL functions `as _system_hostname` / `as _active_custom_hostname` to avoid clashing with the method names). Update the docstring: "also allocates the workspace's system hostname (custom-domain publishing §4.1), the same allocator `clue_spine.create_workspace` uses".

On `HybridRepository`, next to `get_web_publish`, add:

```python
    def system_hostname(self) -> str | None:
        """The workspace's permanent ``<label>.<suffix>`` hostname (custom-domain publishing §4.1)."""
        return self._bridge._run(lambda conn: _system_hostname(conn, self.workspace_id))

    def active_custom_hostname(self) -> str | None:
        return self._bridge._run(lambda conn: _active_custom_hostname(conn, self.workspace_id))
```

- [ ] **Step 4: `toolbelt/publishes.py`**

- `publish_web_document`: remove the `public_base: str` parameter; at the top of the body add `from ..public_pages import system_public_origin` next to the existing lazy imports and compute `public_origin = system_public_origin(repository)`; pass `public_origin=public_origin` to `build_publish_package`.
- `PublishWebDocumentInput`: delete the `public_base` field and its comment; amend the `noindex` comment's "Like ``public_base``" sentence to "It is part of the rendered bytes, so it belongs in the idempotency body".
- `run`: drop `public_base=inputs.public_base`.

- [ ] **Step 5: `main.py`**

- `_publish_web`: remove `public_base` from the signature and from the tool body dict.
- `publish_web_document` route: drop `public_base=str(request.base_url)...`; response: `"url": public_publish_url(repo, slug), "custom_url": custom_publish_url(repo, slug), "public_origin": system_public_origin(repo), "custom_origin": custom_public_origin(repo)`. The `request: Request` parameter can stay if other code uses it; otherwise remove it.
- `get_web_publish_state`: unpublished → `{"schema_version": 1, "published": False, "public_origin": system_public_origin(repo), "custom_origin": custom_public_origin(repo)}`; published → add the same two keys plus `"custom_url": custom_publish_url(repo, publish["slug"])` and `"url": public_publish_url(repo, publish["slug"])`.
- `_process_web_batch(repo, batch, public_base)`: drop the third parameter and the `public_base=` it passes to `_publish_web`; fix both call sites (5424, 5464) and delete their `public_base = str(request.base_url)...` lines (keep `request` only if still used). Row: `row["url"] = public_publish_url(repo, slug)`.
- Delete `public_publish_path` (line 7387) and import `custom_public_origin, custom_publish_url, public_publish_url, system_public_origin` from `.public_pages` at the top of `main.py` (after the other `lumen_api` imports; `public_pages` imports `design_store` and `web_export`, both already imported by `main`, so there is no cycle).
- `grep -n "public_publish_path\|public_base" lumen_api/*.py lumen_api/toolbelt/*.py` must return nothing except `build_export_bundle`/editor-preview uses of `request.base_url` (which are not publish paths and stay).

- [ ] **Step 6: Fix the existing tests**

- `tests/test_web_export.py:585`: `assert body["url"].endswith(f"/{slug}") and body["url"].startswith("https://")`.
- `tests/test_web_batches.py:96`, `tests/test_abm_batch_publish.py:174`: `assert row["url"].endswith(f"/{row['slug']}")`.
- `grep -rn "public_base" tests/` — remove the key from any tool-input fixtures (`test_write_path_governance.py`, `test_design_toolbelt.py`, `test_abm_batch_publish.py`) and adjust any assertion that listed `public_base` among journal-safe fields.

- [ ] **Step 7: Run the focused files**

`( set -a; source ../../../../.env; set +a; ../../../../.venv/bin/python -m pytest tests/test_public_pages.py tests/test_write_path_governance.py tests/test_design_toolbelt.py -q )` → PASS. (`test_web_export.py`, `test_abm_batch_publish.py`, `test_web_batches.py` still GET `/w/` pages and go green in Task 11.)

- [ ] **Step 8: Commit**

```bash
git add subsystems/clue-design/apps/api
git commit -m "design-api: publish URLs from the hostname registry; dev workspaces get system hostnames"
```

---

### Task 11: Design API — delete the interim `/w/` routes; tests read publishes directly

**Files:**
- Modify: `lumen_api/main.py` (delete the three routes ~5470-5565, `public_blob_store` 1014-1019 and `public_repository` 1034-1041 if unreferenced, the `/w/` comment in `repository()`), `lumen_api/web_export.py` (delete `resolve_publish_asset` + `PUBLISH_ASSET_PATTERN` if unreferenced)
- Modify tests: `tests/conftest.py` (helpers), `tests/test_workspace_seam.py:95-110`, `tests/test_workspace_seam_route_table.py:49-51`, `tests/test_web_export.py`, `tests/test_custom_component_publish.py`, `tests/test_abm_batch_publish.py`, `tests/test_web_fragment_export.py:205-215`

- [ ] **Step 1: Prove nothing else consumes the routes (spec §6.5)**

Run from the repo root: `grep -rn '"/w/\|/w/\${\|/w/{' apps/frontend/src subsystems/clue-design/apps/editor/src subsystems/clue-design/apps/api/lumen_api platform | grep -v node_modules`. Expected: only the three route decorators, `public_publish_path` remnants (none after Task 10), and comments. Anything else is a consumer to migrate first — stop and report it.

- [ ] **Step 2: Add the test helpers** to `tests/conftest.py`:

```python
def published(workspace_id: str, slug: str) -> dict | None:
    """The publish row as the page origin would read it (custom-domain publishing S1 deleted the
    design API's interim `/w/{ws}/p/{slug}` serving routes; suites read the row instead)."""
    from lumen_api.design_store import HybridRepository

    return HybridRepository(workspace_id=workspace_id, ensure_workspace=False).get_web_publish(slug)


def is_served(workspace_id: str, slug: str) -> bool:
    row = published(workspace_id, slug)
    return row is not None and row["status"] == "active"


def published_html(workspace_id: str, slug: str) -> str:
    row = published(workspace_id, slug)
    assert row is not None and row["status"] == "active", f"no active publish at {slug!r}"
    return str(row["html"])


def published_manifest(workspace_id: str, slug: str) -> dict:
    row = published(workspace_id, slug)
    assert row is not None and row["status"] == "active", f"no active publish at {slug!r}"
    manifest = row.get("manifest")
    assert isinstance(manifest, dict)
    return manifest
```

- [ ] **Step 3: Rewrite the call sites** (mechanical rule; every line found by `grep -n "/w/" tests/*.py`):

| Old | New |
| --- | --- |
| `client.get(f"/w/{ws}/p/{slug}").text` | `published_html(ws, slug)` |
| `served = client.get(f"/w/{ws}/p/{slug}")` + `served.status_code == 200` + `served.text` | `html = published_html(ws, slug)` and assert on `html` |
| `client.get(f"/w/{ws}/p/{slug}").status_code == 404` | `not is_served(ws, slug)` |
| `client.get(f"/w/{ws}/p/{slug}/manifest.json").json()` | `published_manifest(ws, slug)` |
| `client.get(f"/w/{ws}/p-assets/…")` | delete the assertion (asset serving is covered by `tests/page_origin/test_routes.py`) |
| `test_workspace_seam.py:104-108` (the bare-client 404 probes on `/w/`) | replace with `assert bare.get(f"/w/{workspace_id}/p/seam-page").status_code == 404` kept as the proof the routes are GONE, and delete the manifest/p-assets lines |
| `test_workspace_seam_route_table.py:49-51` | delete the three rows |
| `test_web_export.py:593` (`'<link rel="canonical"' in served.text`) | `'<link rel="icon" href="/favicon.ico">' in html` and `'<link rel="canonical"' not in html` |
| `test_web_fragment_export.py:209-215` (`served` + `manifest` GETs) | `published_html` / `published_manifest` |

Import the helpers at the top of each file: `from .conftest import is_served, published_html, published_manifest`.

- [ ] **Step 4: Delete the routes and dead helpers**

In `main.py`: delete the block from the `# --- O6b interim public serving surface` comment through the end of `serve_published_page`; delete `public_blob_store` and `public_repository` if `grep -n "public_blob_store\|public_repository" lumen_api/main.py` shows no other use; trim the `repository()` docstring sentence that names the `/w/` group. In `web_export.py`: delete `resolve_publish_asset` and `PUBLISH_ASSET_PATTERN` if `grep -rn "resolve_publish_asset\|PUBLISH_ASSET_PATTERN" lumen_api tests` is empty after the test edits. Also delete the `/p/{slug}` 404 stub if one exists (`grep -n '"/p/{slug}"' lumen_api/main.py`).

- [ ] **Step 5: Run the affected files**

`( set -a; source ../../../../.env; set +a; ../../../../.venv/bin/python -m pytest tests/test_workspace_seam.py tests/test_workspace_seam_route_table.py tests/test_web_export.py tests/test_custom_component_publish.py tests/test_abm_batch_publish.py tests/test_web_batches.py tests/test_web_fragment_export.py tests/test_public_pages.py -q )` → PASS. Run `../../../../.venv/bin/python -m ruff check lumen_api` for unused imports.

- [ ] **Step 6: Commit**

```bash
git add subsystems/clue-design/apps/api
git commit -m "design-api: delete the O6b interim /w/ serving routes; suites read publishes directly"
```

---

### Task 12: Frontend — share menu shows the real public host and publishes for real

**Files:**
- Modify: `apps/frontend/src/features/design-editor/engine/webDocuments.ts` (`WebPublishState` ~1845, `fetchWebPublishInfo` ~1862-1899, `WebPublishResult` ~1902, `publishWebDocument` ~1918-1960), `.../engine/__tests__/webDocuments.test.ts`
- Modify: `apps/frontend/src/features/chat-shell/model/artifact-sharing.ts`, `hooks/use-artifact-sharing-controller.ts`, `components/artifact-header.tsx`, `components/artifact-share-menu.tsx:149`, `components/artifact-stage.tsx:290-302`
- Test: `apps/frontend/src/features/chat-shell/model/artifact-sharing.test.ts` (new)

**Interfaces:**
- `WebPublishState` + `WebPublishResult` gain `customUrl: string | null`, `publicOrigin: string | null`, `customOrigin: string | null`.
- `publicLinkHost(origin: string | null): string` in `model/artifact-sharing.ts`.
- `useArtifactSharingController({ kind, title, documentId })`; controller returns `shareHost` (string, may be `""`), `shareUrl: string | null`.

- [ ] **Step 1: Write the failing model test**

```ts
// apps/frontend/src/features/chat-shell/model/artifact-sharing.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { publicLinkHost } from "./artifact-sharing";

test("publicLinkHost strips the scheme and keeps a dev port", () => {
  assert.equal(publicLinkHost("https://acme.pages.cluehq.ai"), "acme.pages.cluehq.ai");
  assert.equal(publicLinkHost("http://acme.pages.localhost:8040"), "acme.pages.localhost:8040");
  assert.equal(publicLinkHost("https://go.acme.com/"), "go.acme.com");
  assert.equal(publicLinkHost(null), "");
});
```

Run: `cd apps/frontend && npm test` → fails on the missing export.

- [ ] **Step 2: Model helper**

Append to `model/artifact-sharing.ts`:

```ts
/** The host segment the share menu shows before the slug: the origin without its scheme
 * (`acme.pages.cluehq.ai`, or `acme.pages.localhost:8040` on the dev stack). */
export function publicLinkHost(origin: string | null): string {
  if (!origin) return "";
  return origin.replace(/^https?:\/\//, "").replace(/\/+$/, "");
}
```

- [ ] **Step 3: Engine types and mapping** — in `webDocuments.ts` add to `WebPublishState`: `customUrl: string | null; publicOrigin: string | null; customOrigin: string | null;` and to the payload type + return of `fetchWebPublishInfo`: `custom_url`, `public_origin`, `custom_origin` mapped with the same `typeof === "string" ? … : null` pattern. Same three fields on `WebPublishResult` and in `publishWebDocument`'s mapping. In `webDocuments.test.ts`, extend the existing publish-state and publish-result fixtures with `public_origin: "https://acme.pages.test"`, `custom_url: null`, `custom_origin: null` and assert the mapped `publicOrigin`/`customUrl`/`customOrigin`.

- [ ] **Step 4: Controller**

In `use-artifact-sharing-controller.ts`:
- Delete `const SHARE_HOST = …`.
- Imports: `import { designBffConfig } from "@/features/design-editor/data/design-bff";` and `import { fetchWebPublishInfo, publishWebDocument, type WebPublishState } from "@/features/design-editor/engine/webDocuments";` (use the same alias style the file's neighbours use for cross-feature imports — check `artifact-stage.tsx`'s `WebArtifactCanvas` import and copy its form), plus `publicLinkHost` from the model.
- Signature: `{ kind, title, documentId }: { kind: ChatShellArtifactKind; title: string; documentId?: string | null }`.
- State: `const [publishState, setPublishState] = useState<WebPublishState | null>(null);` and `const webDocumentId = kind === "web" ? (documentId ?? null) : null;`.
- Effect: when `menuOpen && webDocumentId`, call `fetchWebPublishInfo(designBffConfig(), webDocumentId)`; on success `setPublishState(state)`, and if `state.published && state.slug` also `setSlug(state.slug); setSlugDraft(state.slug); setPublishStatus("published");`. On error leave the local state (the publish action reports errors). Guard with a `cancelled` flag in the cleanup.
- Derived: `const shareHost = publicLinkHost(publishState?.customOrigin ?? publishState?.publicOrigin ?? null);`
  `const shareUrl = useMemo(() => publishState?.customUrl ?? publishState?.url ?? (publishState?.publicOrigin ? \`${publishState.publicOrigin}/${slug}\` : null), [publishState, slug]);`
- `publishAsset`: replace the `CustomEvent` dispatch and the fake timer with:

```ts
  const publishAsset = useCallback(() => {
    if (!webDocumentId) return; // ads have no publish backend; the button stays inert (decision 8)
    setPublishStatus("publishing");
    setStatusMessage("Publishing asset");
    void publishWebDocument(designBffConfig(), webDocumentId, slug)
      .then((result) => {
        setPublishState((current) => ({
          published: true,
          slug: result.slug,
          url: result.url,
          customUrl: result.customUrl,
          publicOrigin: result.publicOrigin ?? current?.publicOrigin ?? null,
          customOrigin: result.customOrigin ?? current?.customOrigin ?? null,
          docVersion: result.docVersion,
          status: "active",
          previousAvailable: result.previousAvailable,
          updatedAt: current?.updatedAt ?? null,
          publishId: result.publishId,
          manifestDigest: result.manifestDigest,
          packageDigest: result.packageDigest,
          htmlDigest: result.htmlDigest,
        }));
        setSlug(result.slug);
        setSlugDraft(result.slug);
        setPublishStatus("published");
        setStatusMessage("Asset published");
      })
      .catch((error: unknown) => {
        setPublishStatus("draft");
        setStatusMessage(error instanceof Error ? error.message : "Publishing failed");
      });
  }, [slug, webDocumentId]);
```

  Remove `publishTimerRef` and its cleanup if nothing else uses it.
- `copyLink`: when `shareUrl` is null, set `setStatusMessage("Publish to get a link")` and return; otherwise copy `shareUrl` as today.
- Return `shareHost` (the derived value) instead of `shareHost: SHARE_HOST`; keep `shareUrl` (now `string | null`) — update its consumers (`previewExternally` opens `shareUrl` only when non-null).

- [ ] **Step 5: Components**

- `artifact-header.tsx`: add prop `documentId?: string | null;` (doc comment: "the active web document, so the share menu reads and writes its real publish state") and pass `documentId` into `useArtifactSharingController({ kind, title, documentId })`.
- `artifact-stage.tsx` ~line 290: add `documentId={activeDocumentId}` to `<ArtifactHeader …>`.
- `artifact-share-menu.tsx:149`: `{shareHost ? <span className={styles.shareLinkHost}>{shareHost}/</span> : null}`.

- [ ] **Step 6: Gates**

`cd apps/frontend && npm test && npm run lint` → clean. With the dev stack stopped: `npm run design-system:build && npm run build` → success.

Manual check (dev stack up, this lane's wrapper): open a project with a web artifact, open the share menu — the host reads `<label>.pages.localhost:8040`; Publish → status "Asset published"; the copied link opens the page at the origin on 8040.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src
git commit -m "frontend: share menu shows the workspace's public host and publishes through the design API"
```

---

### Task 13: Cloudflare Worker `pages-edge`

**Files:**
- Create: `infra/cloudflare/pages-edge/routing.js`, `worker.js`, `routing.test.js`, `wrangler.toml`, `README.md`

- [ ] **Step 1: Write the failing test** (`node --test infra/cloudflare/pages-edge/`)

```js
// infra/cloudflare/pages-edge/routing.test.js
import assert from "node:assert/strict";
import { test } from "node:test";

import { decide } from "./routing.js";

const env = { SYSTEM_SUFFIX: "pages.cluehq.ai", ORIGIN_HOST: "page-origin.cluehq.ai", EDGE_SECRET: "s" };
const req = (url, method = "GET", headers = {}) => new Request(url, { method, headers });

test("system and customer hostnames are forwarded with the public host and the secret", () => {
  for (const url of ["https://acme.pages.cluehq.ai/annual-report?x=1", "https://go.acme.com/annual-report?x=1"]) {
    const decision = decide(req(url, "GET", { "x-clue-public-host": "spoofed", "x-clue-edge-auth": "spoofed" }), env);
    assert.equal(decision.kind, "forward");
    assert.equal(decision.target, "https://page-origin.cluehq.ai/annual-report?x=1");
    assert.equal(decision.headers.get("x-clue-public-host"), new URL(url).hostname);
    assert.equal(decision.headers.get("x-clue-edge-auth"), "s");
  }
});

test("the bare system suffix is ours; other cluehq.ai records pass through untouched", () => {
  assert.equal(decide(req("https://pages.cluehq.ai/"), env).kind, "forward");
  assert.equal(decide(req("https://app.cluehq.ai/login"), env).kind, "passthrough");
  assert.equal(decide(req("https://cluehq.ai/"), env).kind, "passthrough");
});

test("only GET and HEAD reach the origin", () => {
  assert.equal(decide(req("https://go.acme.com/x", "POST"), env).kind, "method_not_allowed");
  assert.equal(decide(req("https://go.acme.com/x", "HEAD"), env).kind, "forward");
});
```

Run: `node --test infra/cloudflare/pages-edge/` → fails (module missing).

- [ ] **Step 2: `routing.js` and `worker.js`**

```js
// infra/cloudflare/pages-edge/routing.js
// Pure routing decision for the pages-edge Worker (custom-domain publishing spec §5.1), kept
// separate from the fetch handler so it runs under `node --test` without a Workers runtime.
export function decide(request, env) {
  const url = new URL(request.url);
  const host = url.hostname.toLowerCase();
  const suffix = env.SYSTEM_SUFFIX.toLowerCase();
  const zoneApex = suffix.split(".").slice(-2).join(".");
  const ours = host === suffix || host.endsWith("." + suffix) || !host.endsWith(zoneApex);
  if (!ours) return { kind: "passthrough" };
  if (request.method !== "GET" && request.method !== "HEAD") return { kind: "method_not_allowed" };
  const headers = new Headers(request.headers);
  headers.delete("x-clue-public-host");
  headers.delete("x-clue-edge-auth");
  headers.set("x-clue-public-host", host);
  headers.set("x-clue-edge-auth", env.EDGE_SECRET);
  const target = new URL(url.pathname + url.search, "https://" + env.ORIGIN_HOST).toString();
  return { kind: "forward", host, target, headers, method: request.method };
}
```

```js
// infra/cloudflare/pages-edge/worker.js
import { decide } from "./routing.js";

export default {
  async fetch(request, env) {
    const decision = decide(request, env);
    if (decision.kind === "passthrough") return fetch(request);
    if (decision.kind === "method_not_allowed") return new Response(null, { status: 405, headers: { Allow: "GET, HEAD" } });
    // redirect: "manual" — the origin's fallback-URL 302 must reach the browser, not be followed here.
    return fetch(new Request(decision.target, { method: decision.method, headers: decision.headers, redirect: "manual" }));
  },
};
```

`wrangler.toml`:

```toml
name = "pages-edge"
main = "worker.js"
compatibility_date = "2026-09-01"

# Route: the zone-wide wildcard so the Worker runs for *.pages.cluehq.ai AND every Cloudflare for
# SaaS custom hostname (which resolve through the fallback origin pages.cluehq.ai). It never runs
# for DNS-only (grey-cloud) records such as app.cluehq.ai, and passes through any other proxied
# record in the zone (see routing.js). Verify in S0 with one real custom hostname (spec §3 item 6).
routes = [{ pattern = "*/*", zone_name = "cluehq.ai" }]

[vars]
SYSTEM_SUFFIX = "pages.cluehq.ai"
ORIGIN_HOST = "page-origin.cluehq.ai"
# EDGE_SECRET is a secret: `wrangler secret put EDGE_SECRET` — never in this file.
```

`README.md`: three lines — what it does, `npx wrangler deploy` from this directory, `wrangler secret put EDGE_SECRET` must equal `CLUE_PAGES_EDGE_SECRET` on the Railway service.

- [ ] **Step 3: Run and commit**

`node --test infra/cloudflare/pages-edge/` → PASS.

```bash
git add infra/cloudflare/pages-edge
git commit -m "infra: pages-edge Cloudflare Worker (public host + edge secret to the page origin)"
```

---

### Task 14: S0 runbook, memory note, spec status

**Files:**
- Create: `docs/specs/pages-hosting-runbook.md`, `_memory/2026-09-17-custom-domain-publishing-s1.md`
- Modify: `_memory/README.md` (topic-note line), `docs/superpowers/specs/2026-09-17-custom-domain-publishing-design.md` (status header: "S1 implemented on `<branch>`; S0 runbook at …")

- [ ] **Step 1: Write the runbook** — `docs/specs/pages-hosting-runbook.md`, with these sections, each ending in a "Recorded values" table the operator fills (angle-bracket placeholders are operator-supplied values, e.g. `<zone-id>`; secrets are never written here):

1. **Hosted Postgres (Railway).** Add a Postgres service in the existing Railway project; copy its async DSN into a scratch shell; `CLUE_DATABASE_URL=<railway-dsn> make db-smoke` against a *copy* first, then `uv run alembic upgrade head` against the real one; `make pages-backfill-hostnames ARGS="--database-url <railway-dsn>"` (expect `"written": 0` on an empty database); repoint the local platform API, design API and workers by setting `CLUE_DATABASE_URL` in `.env` (the lane's throwaway DB is NOT promoted).
2. **R2 bucket.** Create bucket `<bucket>`; create an S3 API token (Object Read & Write); set `CLUE_STORAGE_BACKEND=s3`, `CLUE_STORAGE_S3_BUCKET`, `CLUE_STORAGE_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com`, `CLUE_STORAGE_S3_REGION=auto`, the key pair in the Railway service variables AND in local `.env`; verify with a design-API image upload + `GET /asset-store/<sha>` locally.
3. **Railway service `page-origin`.** Source = repo, branch = `<branch>`, Root Directory unset, `RAILWAY_DOCKERFILE_PATH=/platform/page_origin/Dockerfile.railway`, health check path `/healthz`, variables: `CLUE_DATABASE_URL`, the `CLUE_STORAGE_*` block, `CLUE_PAGES_SYSTEM_SUFFIX=pages.cluehq.ai`, `CLUE_PAGES_PUBLIC_SCHEME=https`, `CLUE_PAGES_PUBLIC_PORT=`, `CLUE_PAGES_TRUST_HOST_HEADER=false`, `CLUE_PAGES_EDGE_SECRET=<generated: openssl rand -hex 32>`. Public Networking → add `page-origin.cluehq.ai`; create Railway's CNAME + `_railway-verify` TXT as **DNS-only (grey cloud)** records in the cluehq.ai zone. Verify: `curl -s https://page-origin.cluehq.ai/healthz` → `{"status":"ok"}`; `curl -s -o /dev/null -w '%{http_code}' https://page-origin.cluehq.ai/anything` → `403`; with `-H 'X-Clue-Public-Host: x.pages.cluehq.ai'` and no secret → `403`.
4. **Cloudflare for SaaS.** Zone → SSL/TLS → Custom Hostnames: enable; fallback origin `pages.cluehq.ai`; create DNS record `pages.cluehq.ai` CNAME → `page-origin.cluehq.ai`, **proxied (orange cloud)**. Record the zone id. (Custom hostnames themselves are created by S2's control plane; S0 creates ONE by hand for the acceptance walk, HTTP validation, and deletes it afterwards.)
5. **System hostnames.** DNS record `*.pages.cluehq.ai` CNAME → `page-origin.cluehq.ai`, proxied. SSL/TLS → Edge Certificates → order an **Advanced certificate** covering `*.pages.cluehq.ai` and `pages.cluehq.ai` (record the price shown; Universal SSL does not cover a second-level wildcard). Wait for "Active".
6. **Worker.** `cd infra/cloudflare/pages-edge && npx wrangler login && npx wrangler secret put EDGE_SECRET` (same value as `CLUE_PAGES_EDGE_SECRET`) `&& npx wrangler deploy`. Confirm the route `*/*` on cluehq.ai in the dashboard. Verify the Worker does not run for `app.cluehq.ai` (DNS-only) — `curl -sI https://app.cluehq.ai` shows no `cf-worker`-related change and the app still loads.
7. **Acceptance (spec §3 item 7).** On the hosted DB: `psql` insert a `workspace_hostname` system row for a workspace that has a published page (or publish one from the app, which allocates it); `curl -s https://<label>.pages.cluehq.ai/<slug>` → 200 with the page HTML and a valid certificate; create one founder-owned custom hostname by hand in the dashboard, add its CNAME to `pages.cluehq.ai` + the ownership TXT, wait for Active, insert its `custom` row with `status='active'`, `curl -s https://<custom>/<slug>` → 200; direct `curl https://page-origin.cluehq.ai/<slug>` → 403; forged host without secret → 403. Then delete the hand-made custom hostname and its row.

Also a "Values recorded" table at the top (zone id, bucket, hostnames, Railway service name, certificate order id, Worker name/version), and a "Not done yet" list: platform API / design API / workers still local (Option C stage two).

- [ ] **Step 2: Memory note** — `_memory/2026-09-17-custom-domain-publishing-s1.md`: what landed per task (commits), the nine decisions above, the backfill counts from Task 5 step 4, the test commands actually run and their results, the owed live acceptance (§3 item 7, founder-triggered), and follow-ups: S2 (control plane, settings screen, label change, fallback/favicon reads in `DbPageReads`), the design subsystem's own editor copy of `webDocuments.ts` still typing `url` as a path, `sniff_mime` fallback dropped on the origin's `/asset-store`, reserved slugs `p-assets`/`asset-store`/`favicon.ico`/`healthz` not refused at publish time (a page published under one of those slugs is unreachable on the origin — S2 or a follow-up adds them to the design API's slug refusals). Add the one-line pointer to `_memory/README.md` under "Topic notes".

- [ ] **Step 3: Commit**

```bash
git add docs/specs/pages-hosting-runbook.md _memory/2026-09-17-custom-domain-publishing-s1.md _memory/README.md docs/superpowers/specs/2026-09-17-custom-domain-publishing-design.md
git commit -m "docs: pages hosting runbook (S0) and the custom-domain publishing S1 session record"
```

---

## S1 exit gate (spec §11)

1. `( set -a; source .env; set +a; uv run pytest tests/test_pages_settings.py tests/db/test_workspace_hostname_schema_db.py tests/clue_spine tests/design/test_publish_delivery.py tests/page_origin tests/auth -q --ignore-glob='*_live.py' )` — green.
2. Design API focused files from Tasks 9–11 — green.
3. `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run lint-imports && uv run alembic heads` — clean, one head.
4. `cd apps/frontend && npm test && npm run lint && npm run build` — green (stack stopped for build).
5. `node --test infra/cloudflare/pages-edge/` — green.
6. Dev-stack walk: stack up, publish a web page from the app, open `http://<label>.pages.localhost:8040/<slug>` — renders with JS/CSS from `/p-assets/…` and images from `/asset-store/…` (browser console: no CSP errors); `curl -sI` shows the exact headers of the Global Constraints.
7. Hosted walk (spec §3 item 7) — founder-operated per the runbook; recorded in `_memory/` when done.
