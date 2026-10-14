# Additional Workspace for an Existing User — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an operator give an existing Clue user (first case: `shank@cluehq.ai`) one more workspace that they own, and run that workspace's normal onboarding and brand ingestion from the product in production.

**Architecture:** A library operation in `clue_auth.provisioning` creates the workspace, its one brand, and an active owner membership for an existing user found by email. A thin script runs it from a production worker (dry run by default) and prints an operator link. The link opens the existing onboarding setting-up screen with the workspace and website in the query string; the screen selects that workspace through the existing membership-checked server action, then starts onboarding through the existing `POST /onboarding` path, so brand-kit ingestion fires from the platform API exactly as on a fresh signup. A Settings read gets a fallback so a workspace without a self-serve signup record still shows its website and logo.

**Tech Stack:** Python 3.12, SQLAlchemy async, FastAPI, pytest (real Postgres, rollback transactions); Next.js App Router, TypeScript, `node:test` via `tsx`.

**Spec:** No separate spec. The design is the "Background and decisions" section below, agreed with the founder in conversation on 2026-10-14. Executors read that section first.

## Background and decisions

- **Why not the self-serve signup path.** `provision_self_serve_workspace` refuses any user who already holds an active membership ("first-time setup, never a second-workspace factory"), and `self_serve_provisioning` is `UNIQUE (user_id)`. `shank@cluehq.ai` already owns Clue HQ through that path. Both rules stay untouched.
- **Why no migration.** An earlier proposal (made against an older branch) relaxed `self_serve_provisioning` to one row per workspace, because the old Stage-0 setup (`POST /stage0/setup`) needs that row. On `main` the setting-up screen starts onboarding through `POST /onboarding` (`platform/api/clue_api/onboarding_routes.py:250`), which needs only: the selected workspace, exactly one brand in it, and a company domain. It never reads `self_serve_provisioning`. So the operator workspace needs no signup record and no schema change.
- **Why onboarding starts from the browser, not the script.** `POST /onboarding` also calls `brand_kit_ingestion.ensure`, which posts to the design API. The design API is private to Railway (`design-api.railway.internal`) and unreachable from the OVH worker VM where operator scripts run. Starting from the product screen runs the start on the platform API inside Railway, so brand-kit ingestion happens exactly as it does for a signup.
- **Why the link carries the workspace id.** The BFF stamps whichever workspace the cookie selects. A link that only carried the website could start onboarding for the wrong workspace (for example re-onboarding Clue HQ with Acme's domain). The setting-up screen therefore selects the linked workspace first, through `selectWorkspace` (`apps/frontend/src/features/session/data/session-actions.ts:12`), which re-checks membership server-side. This is the same sequence the signup controller performs after provisioning (`use-onboarding-controller.ts:175-183`).
- **Settings read.** `read_workspace` (`platform/api/clue_api/frontend_read/settings.py:93`) takes the website and the brand-kit brand from `self_serve_provisioning`. Without a row, Settings would show no website and no logo. Fallback: website from the workspace's latest full onboarding run's domain; brand kit from any approved kit in the workspace when no signup record names a brand. `workspace_logo_urls` in `auth_wiring.py:348` already uses the same onboarding-run fallback for the switcher logo.

## Global Constraints

- Branch `platform/admin-additional-workspace`, cut from `origin/main` at `baafd4e3a`, in the nashville worktree. Never push or open a PR without the founder's explicit instruction.
- Commits carry no AI attribution trailer or footer (repo `CLAUDE.md`, which takes precedence).
- No Alembic migration. No new environment flag.
- DB tests run only against a throwaway database `clue_nashville_addws` on the lane Postgres (`localhost:55040`), never `clue_nashville` (the nashville stack is running on it).
- No live provider calls and no spend in any test. Never run `make check` or broad pytest with real keys; use `--ignore-glob='*_live.py'`.
- The frontend's local `npm run build` is not run while the nashville `next dev` server owns `apps/frontend/.next`; CI's "Editor (lint + unit + build)" job is the build gate. Locally run `npm run lint`, `npx tsc --noEmit`, and the unit tests.
- New user-facing copy is limited to one refusal line on the operator screen. No new screens, controls, or layout.

## Review Focus

1. **Operator link naming a workspace the signed-in user does not belong to.** Expected: refused by `selectWorkspace`'s membership check, and onboarding never starts for whatever workspace is currently selected. Pinned by the Task 4 rule that the live screen mounts only after selection succeeds, and checked in the production walk.
2. **Running the script twice for the same user and company.** Expected: the second run is refused before any write, with no duplicate workspace. Pinned in Task 1.
3. **An email that matches no user, several users, or a suspended user.** Expected: refused before any write. Pinned in Task 1.
4. **A website without a scheme, without a dot, or with spaces.** Expected: refused by the operation and ignored by the link parser, so the normal "website missing" path applies. Pinned in Tasks 1 and 4.
5. **Settings opened on the operator workspace before onboarding ran.** Expected: website `null`, no error; after a run exists, the run's domain. Pinned in Task 2.

---

## File map

| File | Responsibility |
|---|---|
| `platform/auth/clue_auth/provisioning.py` | New `provision_additional_workspace` operation and its result model. |
| `platform/auth/clue_auth/__init__.py` | Export the new operation and model. |
| `tests/auth/test_additional_workspace_provisioning.py` | DB tests for the operation. |
| `platform/api/clue_api/frontend_read/settings.py` | `read_workspace` fallback for website and brand kit. |
| `tests/auth/test_settings_integration.py` | One new test for the fallback. |
| `scripts/provision_additional_workspace.py` | Operator script: dry run by default, `--apply` commits, prints the operator link. |
| `tests/scripts/test_provision_additional_workspace.py` | Unit test for the link builder. |
| `apps/frontend/src/features/onboarding/model/operator-setup.ts` | Pure parser for the link's query parameters. |
| `apps/frontend/src/features/onboarding/model/operator-setup.test.ts` | Unit tests for the parser. |
| `apps/frontend/src/features/onboarding/components/operator-setup-screen.tsx` | Selects the linked workspace, then mounts `LiveSetupScreen`. |
| `apps/frontend/src/features/onboarding/components/onboarding-screen.tsx` | Route the setting-up step to the operator screen when a target is present. |
| `apps/frontend/src/app/onboarding/[step]/page.tsx` | Read `workspace` and `website` query parameters. |
| `_memory/2026-10-14-additional-workspace-for-existing-user.md` | Session record and production runbook. |

---

### Task 0: Throwaway test database

**Files:** none committed.

- [ ] **Step 1: Create and migrate `clue_nashville_addws`**

```bash
cd /Users/aryankeshri/conductor/workspaces/research-and-data/nashville
set -a; source .env; set +a
ADMIN_URL="${CLUE_DATABASE_URL%/*}/postgres"
.venv/bin/python - "$ADMIN_URL" <<'EOF'
import asyncio, sys
from sqlalchemy.ext.asyncio import create_async_engine
async def main():
    engine = create_async_engine(sys.argv[1], isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        exists = (await conn.exec_driver_sql("SELECT 1 FROM pg_database WHERE datname='clue_nashville_addws'")).scalar()
        if not exists:
            await conn.exec_driver_sql("CREATE DATABASE clue_nashville_addws")
    await engine.dispose()
asyncio.run(main())
EOF
export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/*}/clue_nashville_addws"
.venv/bin/alembic upgrade head 2>&1 | tail -1
.venv/bin/alembic current 2>&1 | tail -1
```

Expected: `alembic current` prints `ecc5f641c0d9 (head)`.

Every later test command in this plan is run with `export CLUE_DATABASE_URL=".../clue_nashville_addws"` as above.

---

### Task 1: `provision_additional_workspace`

**Files:**
- Modify: `platform/auth/clue_auth/provisioning.py` (new model after `ProvisionedSelfServeWorkspace`, new function after `provision_self_serve_workspace`)
- Modify: `platform/auth/clue_auth/__init__.py` (import and `__all__`)
- Create: `tests/auth/test_additional_workspace_provisioning.py`

**Interfaces:**
- Produces:
  - `class ProvisionedAdditionalWorkspace(BaseModel)`: fields `workspace: Workspace`, `brand: Brand`, `user: PlatformUser`, `membership: WorkspaceMembership`, `company_website: str`.
  - `async def provision_additional_workspace(conn: AsyncConnection, *, email: str, company_website: str, company_name: str | None = None, now: datetime | None = None, pages_system_suffix: str = DEFAULT_PAGES_SYSTEM_SUFFIX) -> ProvisionedAdditionalWorkspace`
  - Raises `ProvisioningValidationError("COMPANY_WEBSITE_REQUIRED", …)`, `ProvisioningValidationError("COMPANY_NAME_REQUIRED", …)`, `IdentityConflictError(…)`.

- [ ] **Step 1: Write the failing tests**

`tests/auth/test_additional_workspace_provisioning.py`:

```python
"""An operator gives an existing user one more workspace they own (2026-10-14).

Self-serve signup is first-time setup only, so a user who already has a workspace gets a second
one through this operator path instead: the workspace, its one brand (``POST /onboarding`` needs
exactly one), and an active owner membership, for a user found by email. No signup record is
written; nothing about the user's existing workspaces changes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_auth import (
    list_user_memberships,
    provision_additional_workspace,
    provision_self_serve_workspace,
)
from clue_auth.errors import IdentityConflictError, ProvisioningValidationError
from clue_auth.store import suspend_platform_user, update_platform_user_email
from clue_spine import list_brands_for_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_auth_db")


async def _existing_user(conn, *, subject: str, email: str):
    first = await provision_self_serve_workspace(
        conn,
        provider_key="clerk",
        provider_subject=subject,
        first_name="Shank",
        last_name="Keshri",
        job_role="Founder",
        company_name="Clue HQ",
        company_website="https://cluehq.example",
    )
    await update_platform_user_email(conn, first.user.user_id, email)
    return first


def test_creates_an_owned_workspace_with_one_brand_for_an_existing_user() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            first = await _existing_user(conn, subject="addws-1", email="addws1@example.com")
            result = await provision_additional_workspace(
                conn,
                email="  AddWS1@Example.com ",
                company_website="https://acme.example",
                company_name="Acme",
            )
            assert result.user.user_id == first.user.user_id
            assert result.workspace.name == "Acme"
            assert result.workspace.workspace_id != first.workspace.workspace_id
            assert result.membership.role_key == "owner"
            assert result.membership.status == "active"
            assert result.company_website == "https://acme.example"
            brands = await list_brands_for_workspace(conn, result.workspace.workspace_id)
            assert [b.brand_id for b in brands] == [result.brand.brand_id]
            memberships = await list_user_memberships(conn, first.user.user_id)
            assert {m.workspace_id for m in memberships if m.status == "active"} == {
                first.workspace.workspace_id,
                result.workspace.workspace_id,
            }
            signup_rows = (
                await conn.execute(
                    text("SELECT count(*) FROM self_serve_provisioning WHERE user_id = :u"),
                    {"u": first.user.user_id},
                )
            ).scalar_one()
            assert signup_rows == 1

    run_async(scenario())


def test_a_blank_name_is_derived_from_the_website() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _existing_user(conn, subject="addws-2", email="addws2@example.com")
            result = await provision_additional_workspace(
                conn, email="addws2@example.com", company_website="https://www.acme.example/"
            )
            assert result.workspace.name == "Acme"

    run_async(scenario())


def test_a_second_run_for_the_same_company_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _existing_user(conn, subject="addws-3", email="addws3@example.com")
            await provision_additional_workspace(
                conn, email="addws3@example.com", company_website="https://acme.example"
            )
            with pytest.raises(IdentityConflictError, match="already owns"):
                await provision_additional_workspace(
                    conn, email="addws3@example.com", company_website="https://acme.example"
                )

    run_async(scenario())


@pytest.mark.parametrize(
    "website", ["acme.example", "https://acme", "https://acme .example", "", "   "]
)
def test_a_website_that_is_not_an_http_url_is_refused(website: str) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _existing_user(conn, subject="addws-4", email="addws4@example.com")
            with pytest.raises(ProvisioningValidationError) as refused:
                await provision_additional_workspace(
                    conn, email="addws4@example.com", company_website=website
                )
            assert refused.value.code == "COMPANY_WEBSITE_REQUIRED"

    run_async(scenario())


def test_an_unknown_email_is_refused_before_any_write() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            before = (await conn.execute(text("SELECT count(*) FROM workspace"))).scalar_one()
            with pytest.raises(IdentityConflictError, match="no Clue user"):
                await provision_additional_workspace(
                    conn, email="nobody@example.com", company_website="https://acme.example"
                )
            after = (await conn.execute(text("SELECT count(*) FROM workspace"))).scalar_one()
            assert after == before

    run_async(scenario())


def test_an_email_shared_by_two_users_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _existing_user(conn, subject="addws-5a", email="shared@example.com")
            await _existing_user(conn, subject="addws-5b", email="Shared@Example.com")
            with pytest.raises(IdentityConflictError, match="more than one"):
                await provision_additional_workspace(
                    conn, email="shared@example.com", company_website="https://acme.example"
                )

    run_async(scenario())


def test_a_suspended_user_is_refused() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            first = await _existing_user(conn, subject="addws-6", email="addws6@example.com")
            await suspend_platform_user(conn, first.user.user_id)
            with pytest.raises(IdentityConflictError, match="not active"):
                await provision_additional_workspace(
                    conn, email="addws6@example.com", company_website="https://acme.example"
                )

    run_async(scenario())
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `.venv/bin/pytest tests/auth/test_additional_workspace_provisioning.py -q`
Expected: collection error, `ImportError: cannot import name 'provision_additional_workspace' from 'clue_auth'`.

If `list_brands_for_workspace`, `list_user_memberships`, `suspend_platform_user` or `update_platform_user_email` are not importable from the named modules, find their real home with `grep -rn "def <name>" platform` and correct the import; record it as a ruling.

- [ ] **Step 3: Implement**

In `platform/auth/clue_auth/provisioning.py`, add `import re` to the imports, then after `class ProvisionedSelfServeWorkspace` add the model, and after `provision_self_serve_workspace` add the function:

```python
_HTTP_WEBSITE = re.compile(r"https?://[^\s/?#]+\.[^\s/?#]+(?:[/?#]\S*)?", re.IGNORECASE)


class ProvisionedAdditionalWorkspace(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace: Workspace
    brand: Brand
    user: PlatformUser
    membership: WorkspaceMembership
    company_website: str


async def provision_additional_workspace(
    conn: AsyncConnection,
    *,
    email: str,
    company_website: str,
    company_name: str | None = None,
    now: datetime | None = None,
    pages_system_suffix: str = DEFAULT_PAGES_SYSTEM_SUFFIX,
) -> ProvisionedAdditionalWorkspace:
    """Give an EXISTING user one more workspace they own — an operator action, not signup.

    Self-serve provisioning is first-time setup only (it refuses a user with an active
    membership, and ``self_serve_provisioning`` is one row per user), so a second workspace for
    someone who already has one is created here instead: the workspace, its single brand
    (``POST /onboarding`` starts a run only for a workspace with exactly one brand), and an
    active owner membership. No signup record is written and the user's other workspaces are
    untouched. Onboarding then starts from the product's setting-up screen, so brand-kit
    ingestion runs on the platform API exactly as it does for a signup.

    Refuses, before any write: a website that is not an http(s) URL with a dotted host; an email
    that matches no user or more than one; a user who is not active; and a user who already owns
    an active workspace with the same name (a re-run of the same operator command). The user row
    is locked first so two concurrent runs for one user cannot both pass the duplicate check.
    """
    at = now or datetime.now(UTC)
    website = company_website.strip()
    if not _HTTP_WEBSITE.fullmatch(website):
        raise ProvisioningValidationError(
            "COMPANY_WEBSITE_REQUIRED", "an http(s) company website with a domain is required"
        )
    typed = company_name.strip() if company_name and company_name.strip() else None
    name = typed or canonical_workspace_name(website)
    if name is None:
        raise ProvisioningValidationError(
            "COMPANY_NAME_REQUIRED",
            "a company name or a website with a nameable domain is required",
        )
    address = email.strip().casefold()
    user_ids = (
        (
            await conn.execute(
                text(
                    "SELECT user_id FROM platform_user WHERE lower(email) = :email "
                    "ORDER BY user_id FOR UPDATE"
                ),
                {"email": address},
            )
        )
        .scalars()
        .all()
    )
    if not user_ids:
        raise IdentityConflictError(f"no Clue user has the email {address}")
    if len(user_ids) > 1:
        raise IdentityConflictError(f"more than one Clue user has the email {address}")
    user = await get_platform_user(conn, user_ids[0])
    if user is None or user.status != "active":
        raise IdentityConflictError(f"the Clue user {address} is not active")
    duplicate = (
        await conn.execute(
            text(
                "SELECT w.workspace_id FROM workspace_membership m "
                "JOIN workspace w USING (workspace_id) "
                "WHERE m.user_id = :user_id AND m.role_key = 'owner' AND m.status = 'active' "
                "AND lower(w.name) = lower(:name) LIMIT 1"
            ),
            {"user_id": user.user_id, "name": name},
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise IdentityConflictError(
            f"{address} already owns a workspace named {name!r} ({duplicate})"
        )
    workspace = await create_workspace(conn, name=name, pages_system_suffix=pages_system_suffix)
    brand = await create_brand(conn, workspace_id=workspace.workspace_id, name=name)
    membership = await create_workspace_membership(
        conn,
        workspace_id=workspace.workspace_id,
        user_id=user.user_id,
        role_key="owner",
        status="active",
        now=at,
    )
    return ProvisionedAdditionalWorkspace(
        workspace=workspace,
        brand=brand,
        user=user,
        membership=membership,
        company_website=website,
    )
```

In `platform/auth/clue_auth/__init__.py`, add `ProvisionedAdditionalWorkspace` and `provision_additional_workspace` to the `from clue_auth.provisioning import (...)` block and to `__all__`, next to `provision_workspace_owner`.

- [ ] **Step 4: Run the tests to watch them pass**

Run: `.venv/bin/pytest tests/auth/test_additional_workspace_provisioning.py -q`
Expected: `11 passed` (seven tests, one parametrized over five websites).

Then the neighbours, to prove signup is unchanged:
Run: `.venv/bin/pytest tests/auth/test_self_serve_provisioning.py -q`
Expected: all pass, none skipped for a missing DB.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check platform/auth/clue_auth tests/auth/test_additional_workspace_provisioning.py
.venv/bin/ruff format --check platform/auth/clue_auth tests/auth/test_additional_workspace_provisioning.py
git add platform/auth/clue_auth/provisioning.py platform/auth/clue_auth/__init__.py tests/auth/test_additional_workspace_provisioning.py
git commit -m "Auth: an operator can give an existing user one more workspace they own

Self-serve signup is first-time setup only, so a user who already has a
workspace had no way to get a second one. provision_additional_workspace
creates the workspace, its single brand (POST /onboarding needs exactly one)
and an active owner membership for a user found by email, writes no signup
record, and refuses a bad website, an unknown/ambiguous/inactive user and a
re-run for the same company before any write."
```

---

### Task 2: Settings shows website and logo without a signup record

**Files:**
- Modify: `platform/api/clue_api/frontend_read/settings.py:93-117` (`read_workspace`)
- Test: `tests/auth/test_settings_integration.py` (one new test at the end)

**Interfaces:**
- Consumes: `provision_additional_workspace` from Task 1; `create_run` from `clue_api.arv2.onboarding_store`.
- Produces: no new names. `GET /frontend/v1/settings/workspace` returns `website` and `logo_url` for a workspace with no `self_serve_provisioning` row.

- [ ] **Step 1: Write the failing test**

Append to `tests/auth/test_settings_integration.py` (add `from uuid import uuid4`, `from clue_api.arv2.onboarding_store import create_run`, and `provision_additional_workspace` to the `clue_auth.provisioning` import):

```python
def test_operator_workspace_reads_its_website_from_onboarding_and_its_kit_logo() -> None:
    """A workspace an operator added has no signup record, so Settings falls back to the
    latest full onboarding run's domain and to the workspace's approved brand kit."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            owner = await seed(conn)
            added = await provision_additional_workspace(
                conn, email="owner@example.com", company_website="https://acme.example"
            )
            ws = added.workspace.workspace_id
            app = build_app(conn, [])
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers=headers(ws),
            ) as client:
                before = (await client.get(f"{PREFIX}/workspace")).json()
                assert before["website"] is None
                assert before["logo_url"] is None
                await create_run(
                    conn,
                    run_id=uuid4(),
                    workspace_id=ws,
                    brand_id=added.brand.brand_id,
                    company_domain="acme.example",
                    requested_by_user_id=owner.user.user_id,
                )
                await conn.execute(
                    text(
                        "INSERT INTO design_brand_kit (brand_kit_id, version, workspace_id, "
                        "brand_id, name, approval_status, source, brand_kit_json, "
                        "brand_summary_json, diagnostics_json) "
                        "VALUES ('bk_operator_test', 1, :ws, :brand, 'Acme kit', 'approved', "
                        "'uploaded', CAST(:kit AS jsonb), '{}', '[]')"
                    ),
                    {
                        "ws": ws,
                        "brand": added.brand.brand_id,
                        "kit": json.dumps(
                            {
                                "assets": {
                                    "logos": {
                                        "primary": {"variants": [{"asset_id": "asset_acme_logo"}]}
                                    }
                                }
                            }
                        ),
                    },
                )
                after = (await client.get(f"{PREFIX}/workspace")).json()
                assert after["website"] == "https://acme.example"
                assert after["logo_url"] == "/api/clue/design/assets/asset_acme_logo/bytes"

    run_async(scenario())
```

- [ ] **Step 2: Run it to watch it fail**

Run: `.venv/bin/pytest tests/auth/test_settings_integration.py -q -k operator_workspace`
Expected: FAIL at `assert after["website"] == "https://acme.example"` with `None`.

If the `before` assertions fail instead (for example the session refuses the operator workspace), stop and debug with superpowers:systematic-debugging; do not loosen the test.

- [ ] **Step 3: Implement**

Replace the SQL in `read_workspace` with:

```python
                text(
                    "SELECT w.workspace_id, w.name, "
                    "COALESCE(p.company_website, 'https://' || r.company_domain) "
                    "AS company_website, k.brand_kit_json "
                    "FROM workspace w LEFT JOIN self_serve_provisioning p USING (workspace_id) "
                    # A workspace an operator added has no signup record: its website is the
                    # domain its latest full onboarding run was started for (the switcher logo
                    # uses the same fallback, auth_wiring.workspace_logo_urls).
                    "LEFT JOIN LATERAL (SELECT company_domain FROM onboarding_run "
                    "WHERE workspace_id = w.workspace_id AND kind = 'full' "
                    "ORDER BY requested_at DESC LIMIT 1) r ON true "
                    "LEFT JOIN LATERAL (SELECT brand_kit_json FROM design_brand_kit "
                    "WHERE workspace_id = w.workspace_id "
                    "AND (p.brand_id IS NULL OR brand_id = p.brand_id) "
                    "AND approval_status = 'approved' "
                    "ORDER BY updated_at DESC, version DESC, brand_kit_id "
                    "LIMIT 1) k ON true WHERE w.workspace_id = :ws"
                ),
```

- [ ] **Step 4: Run the settings suite**

Run: `.venv/bin/pytest tests/auth/test_settings_integration.py tests/api/test_frontend_read_settings_pages_db.py -q`
Expected: all pass, including the new test and the existing `test_workspace_and_members_permissions` (website `https://example.com` from the signup record still wins).

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check platform/api/clue_api/frontend_read/settings.py tests/auth/test_settings_integration.py
.venv/bin/ruff format --check platform/api/clue_api/frontend_read/settings.py tests/auth/test_settings_integration.py
git add platform/api/clue_api/frontend_read/settings.py tests/auth/test_settings_integration.py
git commit -m "Settings: show website and logo for a workspace with no signup record

A workspace an operator added has no self_serve_provisioning row, so the
workspace settings read returned no website and no logo. Fall back to the
latest full onboarding run's domain and to the workspace's approved brand kit."
```

---

### Task 3: Operator script

**Files:**
- Create: `scripts/provision_additional_workspace.py`
- Create: `tests/scripts/test_provision_additional_workspace.py`

**Interfaces:**
- Consumes: `provision_additional_workspace`, `ProvisionedAdditionalWorkspace` from Task 1.
- Produces: `operator_setup_url(app_origin: str, workspace_id: str, website: str) -> str`, and the CLI `--email`, `--website`, `--company-name`, `--app-origin`, `--apply`.

- [ ] **Step 1: Write the failing test**

`tests/scripts/test_provision_additional_workspace.py`:

```python
"""The operator link opens the setting-up screen for exactly the new workspace."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from scripts.provision_additional_workspace import operator_setup_url


def test_link_names_the_workspace_and_the_website() -> None:
    url = operator_setup_url(
        "https://app.cluehq.ai/", "ws_0123abcd", "https://acme.example/?ref=x&y=1"
    )
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        "https://app.cluehq.ai/onboarding/setting-up"
    )
    assert parse_qs(parts.query) == {
        "workspace": ["ws_0123abcd"],
        "website": ["https://acme.example/?ref=x&y=1"],
    }
```

- [ ] **Step 2: Run it to watch it fail**

Run: `.venv/bin/pytest tests/scripts/test_provision_additional_workspace.py -q`
Expected: `ModuleNotFoundError: No module named 'scripts.provision_additional_workspace'`.

- [ ] **Step 3: Implement**

`scripts/provision_additional_workspace.py`:

```python
#!/usr/bin/env python3
"""Give an existing Clue user one more workspace they own, then print the link that onboards it.

    python scripts/provision_additional_workspace.py --email shank@cluehq.ai \
        --website https://acme.com [--company-name "Acme"] [--app-origin https://app.cluehq.ai] \
        [--apply]

**Dry run by default.** Without ``--apply`` it creates everything inside a transaction, prints
what it would create, and rolls back. With ``--apply`` it commits.

Run it where the app settings point at the target database (a production worker container has
them). It creates the workspace, its one brand and an owner membership
(``clue_auth.provision_additional_workspace``); it starts nothing and spends nothing. Onboarding
starts when the user, signed in, opens the printed link: the setting-up screen selects the new
workspace (membership re-checked server-side) and starts the normal onboarding run, which also
starts brand-kit ingestion on the platform API.
"""

from __future__ import annotations

import argparse
import asyncio
from urllib.parse import urlencode

from clue_auth import provision_additional_workspace
from clue_config import Settings
from clue_db import db_lifespan, transaction


class _DryRun(Exception):
    """Raised inside the transaction so a dry run rolls everything back."""


def operator_setup_url(app_origin: str, workspace_id: str, website: str) -> str:
    query = urlencode({"workspace": workspace_id, "website": website})
    return f"{app_origin.rstrip('/')}/onboarding/setting-up?{query}"


async def _run(
    *, email: str, website: str, company_name: str | None, app_origin: str | None, apply: bool
) -> None:
    settings = Settings()
    origin = app_origin or settings.app_origin
    try:
        async with db_lifespan(), transaction() as conn:
            result = await provision_additional_workspace(
                conn,
                email=email,
                company_website=website,
                company_name=company_name,
                pages_system_suffix=settings.pages_system_suffix,
            )
            print(f"user       {result.user.user_id} ({email.strip().casefold()})")
            print(f"workspace  {result.workspace.workspace_id}  {result.workspace.name!r}")
            print(f"brand      {result.brand.brand_id}")
            print(f"membership {result.membership.membership_id}  owner, active")
            print(f"onboarding {operator_setup_url(origin, result.workspace.workspace_id, result.company_website)}")
            if not apply:
                raise _DryRun
    except _DryRun:
        print("DRY RUN: rolled back, nothing written (pass --apply to commit)")
        return
    print("COMMITTED. Sign in as the user and open the onboarding link above.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--website", required=True)
    parser.add_argument("--company-name")
    parser.add_argument("--app-origin", help="defaults to the app_origin setting")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        _run(
            email=args.email,
            website=args.website,
            company_name=args.company_name,
            app_origin=args.app_origin,
            apply=args.apply,
        )
    )


if __name__ == "__main__":
    main()
```

Check `Settings` field names before relying on them: `grep -n "app_origin\|pages_system_suffix" libs/clue-config/clue_config/settings.py`. If a name differs, use the real one and ledger the ruling.

- [ ] **Step 4: Run the test, then a dry run against the throwaway DB**

Run: `.venv/bin/pytest tests/scripts/test_provision_additional_workspace.py -q`
Expected: `1 passed`.

Seed one user on the throwaway DB and dry-run the script against it:

```bash
.venv/bin/python - <<'EOF'
import asyncio
from clue_db import db_lifespan, transaction
from clue_auth import provision_self_serve_workspace
from clue_auth.store import update_platform_user_email
async def main():
    async with db_lifespan(), transaction() as conn:
        r = await provision_self_serve_workspace(conn, provider_key="clerk", provider_subject="script-dry-run",
            first_name="Dry", last_name="Run", job_role="Founder", company_name="Dry Run Co",
            company_website="https://dryrun.example")
        await update_platform_user_email(conn, r.user.user_id, "dryrun@example.com")
asyncio.run(main())
EOF
.venv/bin/python scripts/provision_additional_workspace.py --email dryrun@example.com --website https://acme.example --app-origin https://app.cluehq.ai
.venv/bin/python scripts/provision_additional_workspace.py --email dryrun@example.com --website https://acme.example --app-origin https://app.cluehq.ai --apply
.venv/bin/python scripts/provision_additional_workspace.py --email dryrun@example.com --website https://acme.example --app-origin https://app.cluehq.ai
```

Expected: first run prints the five lines and `DRY RUN: rolled back`; second prints `COMMITTED`; third fails with `IdentityConflictError: dryrun@example.com already owns a workspace named 'Acme'`.

- [ ] **Step 5: Lint and commit**

```bash
.venv/bin/ruff check scripts/provision_additional_workspace.py tests/scripts/test_provision_additional_workspace.py
.venv/bin/ruff format --check scripts/provision_additional_workspace.py tests/scripts/test_provision_additional_workspace.py
git add scripts/provision_additional_workspace.py tests/scripts/test_provision_additional_workspace.py
git commit -m "Scripts: provision_additional_workspace, dry run by default

Runs the operator operation from a production worker and prints the link
that opens the setting-up screen for exactly the new workspace."
```

---

### Task 4: The setting-up screen honours an operator link

**Files:**
- Create: `apps/frontend/src/features/onboarding/model/operator-setup.ts`
- Create: `apps/frontend/src/features/onboarding/model/operator-setup.test.ts`
- Create: `apps/frontend/src/features/onboarding/components/operator-setup-screen.tsx`
- Modify: `apps/frontend/src/features/onboarding/components/onboarding-screen.tsx` (props + setting-up branch)
- Modify: `apps/frontend/src/app/onboarding/[step]/page.tsx` (search params)

**Interfaces:**
- Consumes: the link built by `operator_setup_url` (Task 3): `/onboarding/setting-up?workspace=<id>&website=<url>`.
- Produces: `operatorSetupTarget(params: { workspace?: string | string[]; website?: string | string[] }): OperatorSetupTarget | null`, `interface OperatorSetupTarget { workspaceId: string; companyWebsite: string }`, `OperatorSetupScreen({ target, compact, setup })`, and an optional `operatorTarget?: OperatorSetupTarget | null` prop on `OnboardingScreen`.

- [ ] **Step 1: Write the failing test**

`apps/frontend/src/features/onboarding/model/operator-setup.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";
import { operatorSetupTarget } from "./operator-setup";

test("a workspace id and an http website make a target", () => {
  assert.deepEqual(
    operatorSetupTarget({ workspace: " ws_0123abcd ", website: " https://acme.example/x " }),
    { workspaceId: "ws_0123abcd", companyWebsite: "https://acme.example/x" },
  );
});

test("either parameter missing means no target", () => {
  assert.equal(operatorSetupTarget({ workspace: "ws_0123abcd" }), null);
  assert.equal(operatorSetupTarget({ website: "https://acme.example" }), null);
  assert.equal(operatorSetupTarget({}), null);
});

test("a malformed workspace id or website means no target", () => {
  for (const workspace of ["", "0123", "ws_", "ws_../x", "ws_a b"]) {
    assert.equal(operatorSetupTarget({ workspace, website: "https://acme.example" }), null);
  }
  for (const website of ["acme.example", "https://acme", "https://acme .example", "javascript:alert(1)"]) {
    assert.equal(operatorSetupTarget({ workspace: "ws_0123abcd", website }), null);
  }
});

test("a repeated parameter is ambiguous and means no target", () => {
  assert.equal(
    operatorSetupTarget({ workspace: ["ws_a1", "ws_b2"], website: "https://acme.example" }),
    null,
  );
});
```

- [ ] **Step 2: Run it to watch it fail**

Run: `cd apps/frontend && ./node_modules/.bin/tsx --test src/features/onboarding/model/operator-setup.test.ts`
Expected: fails with `Cannot find module './operator-setup'`.

- [ ] **Step 3: Implement the parser**

`apps/frontend/src/features/onboarding/model/operator-setup.ts`:

```ts
/**
 * The operator link (2026-10-14): `/onboarding/setting-up?workspace=<id>&website=<url>`.
 *
 * An operator gives an existing user one more workspace (`scripts/provision_additional_workspace.py`),
 * and the user starts its onboarding by opening this link. Both values are required and must be
 * well-formed: a partial or odd link yields no target, and the screen then behaves exactly as it
 * does without one. The workspace is never trusted from here — the screen selects it through the
 * `selectWorkspace` server action, which re-checks membership.
 */
export interface OperatorSetupTarget {
  workspaceId: string;
  companyWebsite: string;
}

const WORKSPACE_ID = /^ws_[A-Za-z0-9]+$/;
const HTTP_WEBSITE = /^https?:\/\/[^\s/?#]+\.[^\s/?#]+(?:[/?#]\S*)?$/i;

function single(value: string | string[] | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

export function operatorSetupTarget(params: {
  workspace?: string | string[];
  website?: string | string[];
}): OperatorSetupTarget | null {
  const workspaceId = single(params.workspace);
  const companyWebsite = single(params.website);
  if (!WORKSPACE_ID.test(workspaceId) || !HTTP_WEBSITE.test(companyWebsite)) return null;
  return { workspaceId, companyWebsite };
}
```

- [ ] **Step 4: Run the test to watch it pass**

Run: `cd apps/frontend && ./node_modules/.bin/tsx --test src/features/onboarding/model/operator-setup.test.ts`
Expected: `# pass 4`, `# fail 0`.

- [ ] **Step 5: The operator screen**

`apps/frontend/src/features/onboarding/components/operator-setup-screen.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { selectWorkspace } from "@/features/session/data/session-actions";
import type { OnboardingFlow } from "../model/onboarding";
import type { OperatorSetupTarget } from "../model/operator-setup";
import { LiveSetupScreen } from "./live-setup-screen";
import styles from "./onboarding.module.css";

/**
 * The setting-up screen for an operator link. It selects the linked workspace FIRST — the same
 * membership-checked server action the signup controller calls after provisioning — and mounts
 * the live screen only once that succeeded, so onboarding can never start for whichever
 * workspace happened to be selected before the link was opened.
 */
export function OperatorSetupScreen({
  target,
  compact,
  setup,
}: {
  target: OperatorSetupTarget;
  compact: boolean;
  setup: OnboardingFlow["setup"];
}) {
  const [state, setState] = useState<"selecting" | "ready" | "refused">("selecting");

  useEffect(() => {
    let live = true;
    const selection = new FormData();
    selection.set("workspaceId", target.workspaceId);
    selectWorkspace(selection).then(
      () => live && setState("ready"),
      () => live && setState("refused"),
    );
    return () => {
      live = false;
    };
  }, [target.workspaceId]);

  if (state === "ready") {
    return (
      <LiveSetupScreen companyWebsite={target.companyWebsite} compact={compact} setup={setup} />
    );
  }
  if (state === "refused") {
    return (
      <p className={styles.authError} role="alert">
        You don&apos;t have access to this workspace.
      </p>
    );
  }
  return null;
}
```

- [ ] **Step 6: Wire it in**

In `apps/frontend/src/features/onboarding/components/onboarding-screen.tsx`:
- import `OperatorSetupScreen` and `type OperatorSetupTarget`;
- add the optional prop `operatorTarget?: OperatorSetupTarget | null` to the component's props type and destructuring;
- in the `step === "setting-up" || step === "finalizing"` branch, replace the clerk-mode `<LiveSetupScreen … />` with:

```tsx
        {controller.authMode === "clerk" ? (
          operatorTarget ? (
            // An operator link: the workspace and website come from the link, not the profile
            // draft (there is no signup in this flow). See model/operator-setup.ts.
            <OperatorSetupScreen
              compact={step === "finalizing"}
              setup={flow.setup}
              target={operatorTarget}
            />
          ) : (
            // Real lane truth; the presentation timer never runs here. The website is the
            // profile draft's — the same value provisioning posted — not the fixture account's.
            <LiveSetupScreen
              companyWebsite={controller.draft.companyWebsite}
              compact={step === "finalizing"}
              setup={flow.setup}
            />
          )
        ) : (
```

In `apps/frontend/src/app/onboarding/[step]/page.tsx`:
- import `operatorSetupTarget` from `@/features/onboarding/model/operator-setup`;
- widen the search-params type to `Promise<{ hold?: string; reason?: string; workspace?: string | string[]; website?: string | string[] }>`;
- pass `operatorTarget={step === "setting-up" ? operatorSetupTarget(query) : null}` to `<OnboardingScreen>`.

Read the setting-up branch of `onboarding-screen.tsx` and the auto-advance timer first: the operator target must not change fixture mode or any other step. If the controller's auto-advance moves `setting-up` to `finalizing` in clerk mode, keep `operatorTarget` for both steps and record the ruling.

- [ ] **Step 7: Frontend gate**

```bash
cd apps/frontend
./node_modules/.bin/tsx --test src/features/onboarding/model/operator-setup.test.ts src/features/onboarding/model/onboarding.test.ts src/features/onboarding/model/onboarding-navigation.test.ts
npx tsc --noEmit -p tsconfig.json
npm run lint
```

Expected: tests pass, `tsc` prints nothing, lint reports 0 errors. (`npm run build` is CI's job here; see Global Constraints.)

- [ ] **Step 8: Commit**

```bash
git add apps/frontend/src/features/onboarding/model/operator-setup.ts apps/frontend/src/features/onboarding/model/operator-setup.test.ts apps/frontend/src/features/onboarding/components/operator-setup-screen.tsx apps/frontend/src/features/onboarding/components/onboarding-screen.tsx "apps/frontend/src/app/onboarding/[step]/page.tsx"
git commit -m "Onboarding: the setting-up screen honours an operator link

/onboarding/setting-up?workspace=<id>&website=<url> selects that workspace
through the membership-checked selectWorkspace action, then starts the normal
onboarding run for it. The live screen mounts only after selection succeeds,
so a link can never onboard whichever workspace was selected before."
```

---

### Task 5: Record and hand over

**Files:**
- Create: `_memory/2026-10-14-additional-workspace-for-existing-user.md`

- [ ] **Step 1: Whole-branch check**

```bash
.venv/bin/pytest tests/auth tests/scripts/test_provision_additional_workspace.py tests/api/test_frontend_read_settings_pages_db.py -q --ignore-glob='*_live.py'
git log --oneline baafd4e3a..HEAD
```

Expected: all pass; four commits.

- [ ] **Step 2: Write the memory note**

Record: the branch and commits; the decision that no migration is needed and why; the throwaway DB name; the production runbook below; and that the production walk is owed and spends money (one onboarding run).

Production runbook (founder-triggered, after the PR is merged to `main` and `deploy-images` has redeployed workers, platform API and frontend):

```bash
ssh ubuntu@40.160.37.148 'sudo docker exec -i vm-batch1-1 python - --email shank@cluehq.ai --website https://<company-site> --company-name "<Company>" --app-origin https://app.cluehq.ai' < scripts/provision_additional_workspace.py
```

Read the dry run, then repeat with `--apply`. Sign in as `shank@cluehq.ai`, open the printed onboarding link, watch setting-up release into the app, then check the switcher shows the new workspace, Brand context fills in, and Settings shows the website.

- [ ] **Step 3: Commit the note**

```bash
git add _memory/2026-10-14-additional-workspace-for-existing-user.md docs/superpowers/plans/2026-10-14-additional-workspace-for-existing-user.md
git commit -m "Docs: plan and session record for operator-added workspaces"
```
