# Workspace display names — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users only ever see a workspace's display name: the post-sign-in chooser and the sidebar switcher list real memberships by name, switching works, new workspaces are named from the typed company name or the website's domain, and legacy rows are backfilled.

**Architecture:** `workspace.name` stays the one display name. A shared `canonical_workspace_name` rule in `clue_core` names a workspace from its website when no company name is typed. The membership loader joins the workspace name into the session, the session response and the frontend schema carry it, and the switcher provider moves into the protected layout where the session is known, calling the existing cookie-setting action to switch.

**Tech Stack:** FastAPI + pydantic + SQLAlchemy text SQL (backend); Next.js App Router, Zod, Base UI menus, `node:test` via `tsx` (frontend).

**Spec:** `docs/superpowers/specs/2026-09-18-workspace-display-names-design.md`.

## Global Constraints

- Local commits only; never `git push`; never `git stash`; no AI attribution in commit messages.
- Never run `make check`, whole suites, or `*_live.py`. Backend: `set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest <files> -p no:cacheprovider --ignore-glob='*_live.py'`. Frontend from `apps/frontend`: `npm test`, `npm run lint`, `npx tsc --noEmit -p .` (three pre-existing test-file errors are known), and `npm run build` only with the lane dev server stopped (it owns `.next`).
- No new environment flag. No workspace id in any user-visible string. The principal contract, the workspace cookie and Settings rename are untouched.
- Copy (verbatim): chooser heading stays `Choose a workspace`; profile screen hint `Leave blank to use your website's name`; 422 code `COMPANY_NAME_REQUIRED`.
- Do not dispatch subagents; report back.

---

### Task 1: Backend — the canonical rule, provisioning precedence, names on the session

**Files:**
- Modify: `libs/clue-core/clue_core/normalize.py` (add `canonical_workspace_name`), `subsystems/clue-design/apps/api/lumen_ingestion/capture/parse.py:1756-1764` (delegate), `platform/auth/clue_auth/models.py:54-67`, `platform/auth/clue_auth/store.py:55-57, 344-356`, `platform/auth/clue_auth/provisioning.py:340-461`, `platform/api/clue_api/auth_wiring.py:71-86, 98-168, 324-355`
- Test: `tests/core/test_canonical_workspace_name.py` (new), `tests/auth/test_self_serve_provisioning.py`, `tests/auth/test_auth_wiring.py`, `tests/auth/test_principal_resolution.py`

**Interfaces:**
- Produces: `canonical_workspace_name(website: str | None) -> str | None`; `WorkspaceMembership.workspace_name: str | None = None`; `SessionMembershipResponse.workspace_name: str`; `ProvisionRequest.company_name: str | None`; provisioning refusal `ProvisioningValidationError("COMPANY_NAME_REQUIRED")` (or the module's existing typed refusal mapped to 422 with that code).

- [ ] **Step 1: The rule's tests**

Create `tests/core/test_canonical_workspace_name.py`:

```python
import pytest

from clue_core.normalize import canonical_workspace_name


@pytest.mark.parametrize(
    ("website", "expected"),
    [
        ("https://www.acme-health.com/pricing", "Acme Health"),
        ("acme-health.com", "Acme Health"),
        ("http://WWW.Bright_Side.co.uk", "Bright Side"),
        ("shop.example.com.au", "Example"),
        ("https://insighthealth.ai", "Insighthealth"),
        ("https://192.168.1.1/", None),
        ("localhost", None),
        ("", None),
        (None, None),
        ("https://user:pw@www.acme.com", "Acme"),
    ],
)
def test_canonical_workspace_name(website: str | None, expected: str | None) -> None:
    assert canonical_workspace_name(website) == expected
```

- [ ] **Step 2: Run to see it fail** — `uv run pytest tests/core/test_canonical_workspace_name.py -p no:cacheprovider -q` → ImportError.

- [ ] **Step 3: The rule**

Append to `libs/clue-core/clue_core/normalize.py`:

```python
_MULTI_LABEL_SUFFIXES: frozenset[str] = frozenset(
    {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp",
     "co.in", "com.br", "com.mx", "co.za", "myshopify.com", "webflow.io", "github.io"}
)


def canonical_workspace_name(website: str | None) -> str | None:
    """The display name a workspace takes from its website when no company name was typed.

    Host only (a scheme is optional; userinfo, port and path are dropped), lower-cased, minus a
    leading ``www.``; the registrable label — the one before the public suffix, with the common
    multi-label suffixes treated as suffixes — split on ``-``/``_`` and capitalised. An IP
    literal, a dotless host or blank input names nothing (``None``): a name is never invented.
    """

    if not website or not website.strip():
        return None
    raw = website.strip()
    if "://" not in raw:
        raw = "https://" + raw
    host = (urlsplit(raw).hostname or "").lower().removeprefix("www.")
    if not host or "." not in host:
        return None
    labels = host.split(".")
    if all(label.isdigit() for label in labels):
        return None
    suffix_len = 2 if ".".join(labels[-2:]) in _MULTI_LABEL_SUFFIXES and len(labels) > 2 else 1
    if len(labels) <= suffix_len:
        return None
    stem = labels[-(suffix_len + 1)]
    parts = [part for part in re.split(r"[-_]", stem) if part]
    return " ".join(part.capitalize() for part in parts) or None
```

(`urlsplit` and `re` are already imported in that module or add them.) In `parse.py`, `_host_brand_name` becomes `return canonical_workspace_name(base_url)` with a one-line docstring saying the rule lives in `clue_core` (import at the top; `lumen-api` already depends on `clue-core` transitively — declare it in `apps/api/pyproject.toml` if not present).

- [ ] **Step 4: Provisioning precedence**

`auth_wiring.py::ProvisionRequest`: `company_name: str | None = Field(default=None, max_length=200)`; the `_strip_required` validator no longer lists it; add a validator that turns a blank `company_name` into `None`. In `provisioning.py::provision_self_serve_workspace`, replace `name = _required(company_name, label="company_name")` with:

```python
    typed = company_name.strip() if company_name and company_name.strip() else None
    name = typed or canonical_workspace_name(company_website)
    if name is None:
        raise ProvisioningValidationError(
            "COMPANY_NAME_REQUIRED",
            "a company name or a website with a nameable domain is required",
        )
```

Read how the module raises typed refusals today (`_required` raises something the HTTP layer maps to 422); reuse that class and add the code `COMPANY_NAME_REQUIRED` to the HTTP mapping in `auth_wiring.py` if codes are mapped by name. `ProvisionResponse.company_name` stays the recorded workspace name. Tests in `tests/auth/test_self_serve_provisioning.py`: (a) typed name wins over the website; (b) blank name + `www.acme-health.com` → workspace and brand named `Acme Health`; (c) neither → refused with the code. Mirror the file's existing provisioning test setup.

- [ ] **Step 5: Names on the session**

`models.py`: `workspace_name: str | None = None` on `WorkspaceMembership` with a comment "filled by the database loader's join; None only for loaders that do not read the workspace row". `store.py`: `list_user_memberships` selects `m.membership_id, m.workspace_id, m.user_id, m.role_key, m.status, m.created_at, m.activated_at, m.revoked_at, w.name AS workspace_name FROM workspace_membership m JOIN workspace w USING (workspace_id) WHERE m.user_id = :user_id ORDER BY m.created_at, m.membership_id` (keep `_MEMBERSHIP_COLUMNS` for the other readers). `auth_wiring.py`: `SessionMembershipResponse.workspace_name: str`, filled with `item.workspace_name or item.workspace_id` (the fallback exists only for in-memory loaders in tests; the DB join cannot yield None). Tests: `tests/auth/test_auth_wiring.py` session test asserts `workspace_name` on the wire; `tests/auth/test_principal_resolution.py` (DB) asserts the loader's memberships carry the workspace's name.

- [ ] **Step 6: Gate and commit**

`set -a; source .env; set +a; env -u CLUE_CHAT_REASONING_TRACE_MODE uv run pytest tests/core/test_canonical_workspace_name.py tests/auth/test_self_serve_provisioning.py tests/auth/test_auth_wiring.py tests/auth/test_principal_resolution.py -p no:cacheprovider --ignore-glob='*_live.py' -q`; design: `apps/api/tests/test_ingestion_*` files that cover `_host_brand_name` (grep) from `subsystems/clue-design` with `PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python -m pytest … -q -p no:cacheprovider`; `uv run ruff check` + `uv run mypy` on the changed platform files; `uv run lint-imports`. Commit: `feat(auth): workspace display names — canonical rule from the website, typed-name-first provisioning, names on the session`.

---

### Task 2: The backfill

**Files:**
- Create: `scripts/backfill_workspace_names.py`
- Test: `tests/scripts/test_backfill_workspace_names_db.py` (new; lane DB, rolled back)

**Interfaces:**
- Produces: `async def plan_backfill(conn) -> tuple[Rename, ...]` (`Rename(workspace_id, old_name, new_name, website)`) and `async def apply_backfill(conn, plan) -> int`; CLI `uv run python scripts/backfill_workspace_names.py [--apply]` printing one line per rename and a summary; dry-run by default.

- [ ] **Step 1: Test first** — seed (with `tests._workspace.seed_workspace` or raw inserts) three workspaces: A named as its id with a provisioning row `company_website='https://www.acme-health.com'`; B named as its id with no provisioning row; C with a real name `Real Co` and a website. Assert `plan_backfill` returns only A → `Acme Health`; `apply_backfill` renames A only; running it again plans nothing.
- [ ] **Step 2: Run to see it fail.**
- [ ] **Step 3: Implement** — `plan_backfill` runs `SELECT w.workspace_id, w.name, p.company_website FROM workspace w JOIN self_serve_provisioning p USING (workspace_id) WHERE w.name = w.workspace_id AND p.company_website IS NOT NULL ORDER BY w.created_at` and keeps rows where `canonical_workspace_name(website)` is not None; `apply_backfill` calls `clue_spine.rename_workspace` per row. The CLI uses `clue_db.db_lifespan` the way other scripts under `scripts/` do (read one, e.g. `scripts/arv2_repair_person_lookups.py`), sources nothing itself, prints the plan, and only writes with `--apply`.
- [ ] **Step 4: Gate** — the DB test; `ruff`; run the dry-run on the lane: `set -a; source .env; set +a; uv run python scripts/backfill_workspace_names.py` and record the count; do NOT apply (the founder applies, spec §3.6).
- [ ] **Step 5: Commit** — `feat(scripts): backfill legacy workspace names from their provisioning website (dry-run by default)`.

---

### Task 3: Frontend — session names, the chooser, the live switcher, optional company name

**Files:**
- Modify: `apps/frontend/src/features/session/model/session.ts:10-15`, `apps/frontend/src/features/session/data/session-actions.ts` (add `switchWorkspace`; chooser lands on `/`), `apps/frontend/src/app/(auth)/select-workspace/page.tsx:36-48`, `apps/frontend/src/components/shell/workspace-switcher-context.tsx`, `apps/frontend/src/components/shell/sidebar-profile-menu.tsx`, `apps/frontend/src/app/layout.tsx` (remove the provider), `apps/frontend/src/app/(protected)/layout.tsx` (add it with session data), `apps/frontend/src/features/onboarding/model/onboarding.ts:129-172`, `apps/frontend/src/features/onboarding/components/profile-screen.tsx:69-76`, `apps/frontend/src/features/onboarding/hooks/use-onboarding-controller.ts:160-178`
- Test: `apps/frontend/src/features/session/model/session.test.ts` (new or extend), `apps/frontend/src/components/shell/workspace-switcher-context.test.ts`, `apps/frontend/src/features/onboarding/model/onboarding.test.ts` (extend)

**Interfaces:**
- `SessionMembershipSchema` gains `workspace_name: z.string().min(1)`.
- `WorkspaceSwitcherProvider({ demo, workspaces?: SwitcherWorkspace[], activeWorkspaceId?: string | null, children })` where `SwitcherWorkspace = { id, name, initials, role }`; live selection calls the server action `switchWorkspace(workspaceId: string)` (sets the cookie via `selectWorkspace` semantics and `redirect("/")`).
- `useWorkspaceSwitcher()` keeps its shape: `{ demo, workspaces, activeWorkspace, selectWorkspace }`; in live mode `workspaces` are the provided memberships and `selectWorkspace` starts a transition into the server action.
- `ProvisionWorkspaceInputSchema.company_name: z.string().min(1).max(200).nullable()`; `validateProfileDraft` requires the website and not the company name.

- [ ] **Step 1: Tests first**
  - `session.test.ts`: a session payload without `workspace_name` fails the strict schema; with it parses; `resolveWorkspaceMembership` unchanged.
  - `workspace-switcher-context.test.ts`: add a live-mode case — provider given two workspaces and an active id → `workspaces` lists both with initials, `activeWorkspace` is the active one, `demo` false; `selectWorkspace(otherId)` invokes the injected `onSelect` (the provider takes `onSelect` so the test needs no server action) exactly once and never touches localStorage.
  - `onboarding.test.ts`: `validateProfileDraft` with a blank company name and a website passes; blank website fails with the existing message.
- [ ] **Step 2: Run to see them fail.**
- [ ] **Step 3: Implement**
  - `session.ts`: add the field. Contract doc `apps/frontend/docs/api-contracts/session.md:30-33` lists it.
  - `session-actions.ts`: `selectWorkspaceAndContinue` redirects to `/`; add `export async function switchWorkspace(workspaceId: string)` that builds a `FormData` with `workspaceId`, awaits `selectWorkspace`, and `redirect("/")`.
  - `select-workspace/page.tsx`: render `{membership.workspace_name}` and `{membership.role_key}`; the form value stays the id (not visible).
  - `workspace-switcher-context.tsx`: keep the demo store; add props `workspaces`, `activeWorkspaceId`, `onSelect`; in live mode the hook returns them and `selectWorkspace(id)` calls `onSelect(id)` when `id` is one of them. The profile menu's `disabled={!demo}` becomes `disabled={workspaces.length === 0}`; its title becomes `Workspace switching is not available yet` only when there is no choice.
  - `app/layout.tsx`: remove the provider. `(protected)/layout.tsx`: wrap the shell in `WorkspaceSwitcherProvider` with `demo={resolveChatTransport().mode === "fixture"}`, `workspaces={session.memberships.map(m => ({ id: m.workspace_id, name: m.workspace_name, initials: workspaceInitials(m.workspace_name), role: roleLabel(m.role_key) }))}`, `activeWorkspaceId={session.principal.workspace_id}`, `onSelect={switchWorkspace}` (a server action passed to a client component is allowed). `roleLabel` capitalises the role key (`owner` → `Owner`). When there is no session (auth disabled) pass no workspaces.
  - `sidebar-profile-menu.tsx`: `workspaceName = activeWorkspace?.name ?? profile.workspaceName ?? "Clue workspace"` stays; nothing else changes.
  - Onboarding: schema, `validateProfileDraft`, the controller sends `company_name: draft.companyName.trim() || null`, the profile screen gets the hint text under the company-name field. Contract doc `onboarding.md:56-78`: `company_name` optional, name precedence stated.
- [ ] **Step 4: Gate** — `npm test`, `npm run lint`, `npx tsc --noEmit -p .`; then, with the lane frontend stopped, `npm run build`, and relaunch it (`rm -rf .next; npm run dev -- --hostname 127.0.0.1 --port 3020 > /tmp/san-salvador_frontend.log 2>&1 &` from `apps/frontend`). Browser: sign in with the test account, confirm the chooser shows names, land on `/`, open the sidebar menu, see the memberships by name with the active check, switch, confirm the sidebar name changes and the URL is `/`.
- [ ] **Step 5: Commit** — `feat(frontend): workspace display names — chooser and sidebar switcher list real memberships by name; company name optional at onboarding`.

---

### Task 4: Close-out

- [ ] Memory note `_memory/2026-09-18-workspace-display-names.md` + README row: rulings, commits, the backfill dry-run count on the lane (apply is the founder's), owed: a real provisioning with a blank company name.
- [ ] Commit: `docs(memory): workspace display names`.

## Self-review
Spec §3.2 → T1 Step 3; §3.3 → T1 Step 4 + T3 onboarding; §3.4 → T1 Step 5 + T3 schema; §3.5 → T3; §3.6 → T2; §5 acceptance 1–2 → T3 Step 4, 3 → T1 tests, 4 → T2 Step 4, 5 → each gate. Names consistent: `canonical_workspace_name`, `workspace_name`, `switchWorkspace`, `SwitcherWorkspace`, `COMPANY_NAME_REQUIRED`.
