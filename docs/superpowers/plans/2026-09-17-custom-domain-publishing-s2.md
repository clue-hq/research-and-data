# Custom-domain publishing — S2 (custom domains + Settings → Pages) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A workspace admin connects ONE customer-owned subdomain (`go.acme.com`) from Settings → Pages,
watches it walk pending DNS → verifying ownership → issuing certificate → active, and removes it in the
spec's order; the same screen edits the workspace's page defaults (fallback URL, title, description,
favicon, social preview) and the Clue address label.

**Architecture:** The control plane is one FastAPI module on the existing `/frontend/v1` read surface
(`frontend_read/settings_pages.py`) over three new pieces: a Cloudflare custom-hostnames client (the
only module that knows Cloudflare's field names), a DNS observer over public resolvers, and a pure
status-derivation function. Rows live in the S1 tables (`workspace_hostname`, `workspace_pages_settings`)
through `clue_spine` DALs. The page origin's fallback-URL and favicon reads, and the design API's
publish-time defaults, read the same settings row. The frontend lifts the dummy's settings shell
verbatim (the settings-integration slice has not landed on this branch) and binds only the Pages
section, on this repo's `fetchRead` / `fetchMutation` seam.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, `httpx` (+ `httpx.MockTransport` in tests),
`tldextract` (offline public-suffix snapshot), `dnspython`, `python-multipart`; Next.js / TypeScript /
Zod 4 frontend with `node --test`.

**Spec:** `docs/superpowers/specs/archive/2026-09-17-custom-domain-publishing-design.md` §4.1 (label change,
A1), §4.2, §5.2 (fallback/favicon), §7 (control plane), §8.2 (Settings → Pages), §9, §10, §11 (S2 row),
§12. Companion: `docs/superpowers/specs/archive/2026-09-15-settings-integration-design.md` §2.1–2.3, §6.1–6.4
(the shell, autosave, confirmation card, `workspace.manage_settings` = policy revision 3). S1 record:
`_memory/2026-09-17-custom-domain-publishing-s1.md`.

## Global Constraints

- Every env flag the code reads appears in `.env.example` with its default the moment it is introduced,
  and the local `.env` mirrors it (secrets blank). S2 introduces exactly: `CLUE_PAGES_CNAME_TARGET=pages.cluehq.ai`,
  `CLUE_CLOUDFLARE_API_TOKEN=` (secret), `CLUE_CLOUDFLARE_ZONE_ID=`.
- Seam discipline: `clue_spine` imports only `clue_core` + `clue_db` (+ the third-party `tldextract`);
  `clue_design` never imports `clue_spine`; the page origin imports the spine/design DAL/storage only;
  the design API (`lumen_api`) imports `clue_spine` but never `clue_api`; `clue_auth` never imports `clue_api`.
- Hostname rules (spec §1, §7.3), in this order with these codes: `hostname_invalid`, `hostname_is_apex`
  (registrable domain via the public-suffix list; `acme.co.uk` refused, `go.acme.co.uk` accepted),
  `hostname_reserved` (under the registrable domain of `CLUE_PAGES_SYSTEM_SUFFIX`), `custom_hostname_exists`,
  `hostname_taken` (message says only "already connected to a workspace"). One custom hostname per workspace.
- Status ladder (spec §7.4) and the closed error-code set (spec §7.5): `cname_incorrect`, `txt_missing`,
  `caa_blocked`, `hostname_taken`, `verification_expired`, `provider_error`. Active requires our own TXT
  observation even when Cloudflare reports active. Checks are rate-limited to one per 5 s per workspace.
- Removal order (spec §7.6): row → `disconnecting`, Cloudflare delete (404 counts as deleted), row deleted,
  204; a provider failure leaves `disconnecting` and answers 502 `provider_error` with `retryable: true`.
- Cloudflare client (spec §7.7): `POST/GET/DELETE …/zones/{zone_id}/custom_hostnames`, create body
  `{"hostname": …, "ssl": {"method": "http", "type": "dv"}}`, timeouts 10 s, one retry on 5xx, none on 4xx.
- Writes need `workspace.manage_settings` (admin + owner, policy revision 3); a caller without it gets
  `403` with code `PERMISSION_REQUIRED`; reads need an active membership (the router's workspace dependency).
- Upload limits (spec §7.1): favicon ≤ 256 KB, `image/png` | `image/x-icon` | `image/svg+xml`; social
  preview ≤ 2 MB, `image/png` | `image/jpeg`. Bytes go through `clue_design.storage.register_design_bytes`
  (no second upload path).
- Wire JSON is camelCase (`WireModel`, `alias_generator=to_camel`); the read shape is spec §7.2 verbatim.
- Frontend: no fixture fallback for the live Pages read (typed error screen); the dummy UI is the ceiling —
  bind existing controls; the four connection-card states are the one screen the spec adds and their
  frames are owed by the co-founder (§12) — **Task 11 is gated on those frames** (see its header).
- Commits: one per task, plain messages, no AI attribution trailer, never push, never on `main`. Never run
  bare `git stash` / `git stash pop` (shared stash stack) — use a temporary WIP commit.
- **Test-running rules.** Root suites: `( set -a; source .env; set +a; uv run pytest <paths> -q -p no:warnings )`.
  Confirm `grep '^CLUE_DATABASE_URL=' .env` names THIS lane's throwaway DB (`clue_addis-ababa@55040`, empty,
  migrated to head) before any DB test. Never `make check` / broad pytest with real keys; scope to named
  files and `--ignore-glob='*_live.py'`. `tests/api` DB tests use `require_profiling_db` + `rollback_conn`
  (`tests/profiling/conftest.py`). Design API suites run from `subsystems/clue-design/apps/api` with
  `( set -a; source ../../../../.env; set +a; ../../../../.venv/bin/python -m pytest tests/<file> -q -p no:warnings )`
  (pass `-k` at most once per invocation; needs `node` + the built `lumen-api-helper`). Frontend:
  `cd apps/frontend && npm test && npm run lint`; `npm run build` only when `lsof -nP -i :3020` shows nothing.
- Gates for Python: `uv run ruff format <paths> && uv run ruff check <paths> && uv run mypy && uv run lint-imports`;
  mypy baseline is exactly 4 pre-existing errors (`ad_assets.py` / `arv2/*`); import-linter 28 kept.
- Live Cloudflare/DNS calls never run in the suite (spec §10): every test uses `httpx.MockTransport` and a
  fake resolver. The live acceptance walk (§10) is founder-triggered.

---

## Decisions this plan makes beyond the spec (flagged for the founder; each reversible)

1. **`txt_missing` is measured from the row's `created_at`, not from "CNAME correct for 30 minutes".**
   The S1 table has no "CNAME first seen correct" timestamp; adding one is a migration for a timer.
   The row is created at connect, so "30 minutes after connect with the CNAME right and the TXT still
   absent" is the same signal in every real flow (the customer adds both records together).
2. **Permission mapping is local to the settings routes.** The frontend-read app has no handler for
   `clue_auth.errors.PermissionDenied` (the global one lives in `auth_wiring`, which the read-surface
   tests do not install), so the routes check `"workspace.manage_settings" in principal.permissions`
   themselves and raise the FI-1 envelope (`403 PERMISSION_REQUIRED`), matching the settings spec §2.3.
3. **The settings shell is lifted verbatim, non-Pages sections keep the dummy's fixture.** The settings
   integration slice (Profile/Workspace/Members) is on another branch. Spec §11 says S2 mounts Pages
   on the lifted shell and reconciles at merge; lifting the shell files byte-for-byte (and keeping the
   dummy's `settings.fixture.ts` for the sections S2 does not bind) makes that merge a same-file
   no-op for everything but `pages-settings.tsx`, the model split and `data/`.
4. **No sidebar entry point is added.** This repo's profile trigger is inert; the profile menu is the
   settings slice's lift. Until it merges, `/settings/pages` is reached by URL (the founder's walk
   types it). No new visible element.
5. **DNS observation runs in a worker thread** (`asyncio.to_thread`) because `dnspython`'s resolver is
   synchronous; public resolvers `1.1.1.1` and `8.8.8.8`, 5 s lifetime.
6. **Publish-time defaults (spec §4.2)**: the workspace `page_description` fills in only when the page
   derives an empty description; the workspace social preview becomes `og:image` only when the page has
   no image node; `page_title` is NOT applied at publish (the document always has a title) and is kept as
   the workspace default the Settings screen edits for S3-era consumers. Favicon is live (S1 already emits
   the link; this slice serves it).
7. **The `active_custom_hostname` read the design API already does** makes `custom_url` / `custom_origin`
   appear on publish responses the moment a row reaches `active`; no design API change for that.

---

## File structure

| Path | Responsibility |
| --- | --- |
| `libs/clue-config/clue_config/{settings,secrets}.py`, `.env.example`, `.env` | `pages_cname_target`, `cloudflare_zone_id`, `cloudflare_api_token` |
| `libs/clue-spine/pyproject.toml`, `platform/api/pyproject.toml` | `tldextract`; `dnspython`, `python-multipart` |
| `libs/clue-spine/clue_spine/hostnames.py` | custom-hostname validation, `CustomHostname` DAL, label change |
| `libs/clue-spine/clue_spine/pages_settings.py` (new) | `PagesSettings` DAL |
| `platform/page_origin/clue_page_origin/reads.py` | `DbPageReads.fallback_url` / `favicon` read the settings row |
| `platform/auth/clue_auth/policy.py` | `workspace.manage_settings`, revision 3 |
| `platform/api/clue_api/cloudflare_custom_hostnames.py` (new) | the three Cloudflare calls |
| `platform/api/clue_api/dns_observe.py` (new) | CNAME + TXT observation |
| `platform/api/clue_api/pages_hostname_status.py` (new) | pure status derivation + error codes |
| `platform/api/clue_api/frontend_read/settings_pages.py` (new), `frontend_read/app.py` | routes + service |
| `subsystems/clue-design/apps/api/lumen_api/{design_store.py, toolbelt/publishes.py, web_export.py}` | publish-time defaults |
| `apps/frontend/src/features/settings/**`, `src/app/(protected)/settings/[[...section]]/{page,error,loading}.tsx`, `src/components/ui/confirmation-card.tsx` | lifted shell + Pages section |
| `apps/frontend/docs/api-contracts/settings.md` (new, Pages section) | reconciled contract |
| `_memory/2026-09-17-custom-domain-publishing-s2.md` (new) | session record |

---

### Task 1: Config, secrets, dependencies, env parity

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (after `pages_origin_port`, line 757), `libs/clue-config/clue_config/secrets.py` (after `pages_edge_secret`, line 113)
- Modify: `.env.example` (after `CLUE_PAGES_ORIGIN_PORT=8040`, line 486), `.env` (same lines, secret blank)
- Modify: `libs/clue-spine/pyproject.toml` (`dependencies` += `"tldextract>=5,<6"`), `platform/api/pyproject.toml` (`dependencies` += `"dnspython>=2.6,<3"`, `"python-multipart>=0.0.9,<1"`)
- Test: `tests/test_pages_settings.py` (extend)

**Interfaces:**
- Produces: `Settings.pages_cname_target: str = "pages.cluehq.ai"`, `Settings.cloudflare_zone_id: str | None = None`,
  `Secrets.cloudflare_api_token: SecretStr | None = None`.

- [ ] **Step 1: Extend the failing test.** In `tests/test_pages_settings.py` add to `PAGES_SETTING_DEFAULTS`:
  `"pages_cname_target": "pages.cluehq.ai"`, `"cloudflare_zone_id": None`; change
  `PAGES_SECRET_FIELDS = ("pages_edge_secret", "cloudflare_api_token")`. Run
  `uv run pytest tests/test_pages_settings.py -q` → FAIL on the missing attribute.

- [ ] **Step 2: Add the fields.** `settings.py`, directly after `pages_origin_port`:

```python
    # The CNAME value a customer points their subdomain at (spec §3 item 4, §7.2). Normally the
    # Cloudflare for SaaS fallback-origin record in our zone. Env: ``CLUE_PAGES_CNAME_TARGET``.
    pages_cname_target: str = "pages.cluehq.ai"
    # The Cloudflare zone that holds our DNS and the SaaS custom hostnames (spec §7.7). None = the
    # custom-domain control plane is not configured (connect answers 503). Env: ``CLUE_CLOUDFLARE_ZONE_ID``.
    cloudflare_zone_id: str | None = None
```

`secrets.py`, after `pages_edge_secret`:

```python
    # Env: CLUE_CLOUDFLARE_API_TOKEN. Zone-scoped token with only "SSL and Certificates: Edit"
    # (spec §7.7); read by the custom-hostnames client and nothing else.
    cloudflare_api_token: SecretStr | None = None
```

`.env.example` after `CLUE_PAGES_ORIGIN_PORT=8040`:

```dotenv
# Custom domains (S2): the CNAME target shown to customers, and the Cloudflare for SaaS control plane.
# Token + zone empty = the Connect action answers 503 PROVIDER_NOT_CONFIGURED; everything else works.
CLUE_PAGES_CNAME_TARGET=pages.cluehq.ai
CLUE_CLOUDFLARE_API_TOKEN=
CLUE_CLOUDFLARE_ZONE_ID=
```

Mirror the three lines into `.env` (never staged). Add the dependencies to the two `pyproject.toml`
files and run `uv sync --all-packages` (stage `uv.lock`).

- [ ] **Step 3: Run + gates + commit.** `uv run pytest tests/test_pages_settings.py -q` → PASS.
  `uv run ruff format libs/clue-config tests/test_pages_settings.py && uv run ruff check libs/clue-config tests/test_pages_settings.py && uv run mypy`.

```bash
git add libs/clue-config libs/clue-spine/pyproject.toml platform/api/pyproject.toml uv.lock .env.example tests/test_pages_settings.py
git commit -m "config: custom-domain control-plane settings, Cloudflare secret, S2 dependencies"
```

---

### Task 2: `clue_spine.hostnames` — custom-hostname validation, custom-row DAL, label change

**Files:**
- Modify: `libs/clue-spine/clue_spine/hostnames.py` (append), `libs/clue-spine/clue_spine/__init__.py` (exports)
- Test: `tests/clue_spine/test_hostnames_custom_pure.py` (new, no DB), `tests/clue_spine/test_hostnames_custom_db.py` (new, DB)

**Interfaces:**
- Produces (pure): `class HostnameRefused(ValueError)` with `.code: str`, `.message: str`;
  `registrable_domain(hostname: str) -> str`; `validate_custom_hostname(value: str, *, system_suffix: str) -> str`;
  `validate_label(label: str) -> str` (codes `label_invalid`, `label_reserved`).
- Produces (DAL, all `async`, first arg `conn`): `CustomHostname` (pydantic: `hostname, workspace_id, status, cf_custom_hostname_id, cname_target, ownership_txt_name, ownership_txt_value, observed_cname, observed_txt_present, last_checked_at, last_error_code, last_error_detail, created_at, updated_at, activated_at`);
  `get_custom_hostname(conn, workspace_id) -> CustomHostname | None`; `hostname_exists(conn, hostname) -> bool`;
  `insert_custom_hostname(conn, *, workspace_id, hostname, cname_target) -> CustomHostname` (status `pending_dns`, ownership placeholders `"pending"`; raises `IntegrityError` on a taken hostname or a second custom row);
  `set_custom_hostname_provider(conn, *, hostname, cf_custom_hostname_id, ownership_txt_name, ownership_txt_value) -> None`;
  `record_custom_hostname_check(conn, *, hostname, status, observed_cname, observed_txt_present, last_error_code, last_error_detail, checked_at) -> CustomHostname` (sets `activated_at` the first time status is `active`);
  `set_custom_hostname_status(conn, *, hostname, status) -> None`; `delete_custom_hostname(conn, *, hostname) -> bool`;
  `replace_system_label(conn, *, workspace_id, label, suffix) -> WorkspaceHostname` (raises `HostnameRefused("label_taken")`).

- [ ] **Step 1: Write the failing pure tests**

```python
# tests/clue_spine/test_hostnames_custom_pure.py
from __future__ import annotations

import pytest

from clue_spine.hostnames import (
    HostnameRefused,
    registrable_domain,
    validate_custom_hostname,
    validate_label,
)

SUFFIX = "pages.cluehq.ai"


@pytest.mark.parametrize(
    ("hostname", "registrable"),
    [
        ("go.acme.com", "acme.com"),
        ("acme.co.uk", "acme.co.uk"),
        ("go.acme.co.uk", "acme.co.uk"),
        ("a.b.c.example", "c.example"),  # unknown suffix: last two labels
        ("acme.pages.cluehq.ai", "cluehq.ai"),
    ],
)
def test_registrable_domain(hostname: str, registrable: str) -> None:
    assert registrable_domain(hostname) == registrable


@pytest.mark.parametrize(
    "ok", ["go.acme.com", "Go.Acme.COM.", "go.acme.co.uk", "pages.bücher.example", "a" * 63 + ".acme.com"]
)
def test_accepted_hostnames_are_normalised(ok: str) -> None:
    result = validate_custom_hostname(ok, system_suffix=SUFFIX)
    assert result == result.lower() and not result.endswith(".")


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        ("", "hostname_invalid"),
        ("go acme.com", "hostname_invalid"),
        ("-go.acme.com", "hostname_invalid"),
        ("a" * 64 + ".acme.com", "hostname_invalid"),
        ("acme.com", "hostname_is_apex"),
        ("acme.co.uk", "hostname_is_apex"),
        ("x.cluehq.ai", "hostname_reserved"),
        ("cluehq.ai", "hostname_reserved"),
        ("go.pages.cluehq.ai", "hostname_reserved"),
    ],
)
def test_refusals_in_spec_order(bad: str, code: str) -> None:
    with pytest.raises(HostnameRefused) as caught:
        validate_custom_hostname(bad, system_suffix=SUFFIX)
    assert caught.value.code == code
    assert caught.value.message


def test_apex_message_names_a_subdomain_example() -> None:
    with pytest.raises(HostnameRefused) as caught:
        validate_custom_hostname("acme.com", system_suffix=SUFFIX)
    assert "go.acme.com" in caught.value.message


@pytest.mark.parametrize("label", ["acme", "acme-hq", "a1b"])
def test_valid_labels(label: str) -> None:
    assert validate_label(label) == label


@pytest.mark.parametrize(
    ("label", "code"),
    [("ab", "label_invalid"), ("-acme", "label_invalid"), ("Acme", "label_invalid"), ("a" * 41, "label_invalid"), ("www", "label_reserved")],
)
def test_invalid_labels(label: str, code: str) -> None:
    with pytest.raises(HostnameRefused) as caught:
        validate_label(label)
    assert caught.value.code == code
```

Run: `uv run pytest tests/clue_spine/test_hostnames_custom_pure.py -q` → `ImportError`.

- [ ] **Step 2: Append the pure part to `hostnames.py`**

```python
# --- custom hostnames: validation (spec §7.3) --------------------------------
import tldextract  # noqa: E402  (module-level import; place it in the import block in practice)

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)
_LABEL_SHAPE = re.compile(rf"^[a-z0-9](?:[a-z0-9-]{{{LABEL_MIN - 2},{LABEL_MAX - 2}}}[a-z0-9])$")


class HostnameRefused(ValueError):
    """A hostname or label the control plane refuses, with its closed-set code (spec §7.3)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def registrable_domain(hostname: str) -> str:
    """The public-suffix registrable domain (``acme.co.uk`` for ``go.acme.co.uk``). Offline: the
    bundled snapshot only, never a network fetch. An unknown suffix falls back to the last two labels."""
    parts = _EXTRACT(hostname)
    if parts.suffix and parts.domain:
        return f"{parts.domain}.{parts.suffix}"
    labels = hostname.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else hostname


def validate_custom_hostname(value: str, *, system_suffix: str) -> str:
    """Normalise and refuse in spec order: invalid → apex → reserved. Returns the normalised hostname."""
    try:
        hostname = normalize_hostname(value)
    except ValueError as error:
        raise HostnameRefused("hostname_invalid", f"{value!r} is not a valid hostname") from error
    registrable = registrable_domain(hostname)
    if hostname == registrable:
        raise HostnameRefused(
            "hostname_is_apex",
            f"A dedicated subdomain such as go.{registrable} is required; the bare domain "
            f"{registrable} cannot be connected.",
        )
    ours = registrable_domain(system_suffix)
    if hostname == ours or hostname.endswith("." + ours):
        raise HostnameRefused("hostname_reserved", f"Hostnames under {ours} cannot be connected.")
    return hostname


def validate_label(label: str) -> str:
    """A Clue-address label an admin picks by hand (spec §4.1 A1): 3–40 of ``[a-z0-9-]``, no edge
    hyphen, not reserved."""
    if not _LABEL_SHAPE.fullmatch(label):
        raise HostnameRefused(
            "label_invalid", "Use 3–40 lowercase letters, digits or hyphens, not starting or ending with a hyphen."
        )
    if label in RESERVED_LABELS:
        raise HostnameRefused("label_reserved", f"{label!r} is reserved.")
    return label
```

(Put `import tldextract` in the module's import block, not mid-file; the `noqa` above only marks where
it is shown.)

- [ ] **Step 3: Run the pure tests** → PASS. Commit checkpoint:
  `git commit -am "spine: custom-hostname and label validation (spec §7.3)"` after `git add libs/clue-spine tests/clue_spine/test_hostnames_custom_pure.py`.

- [ ] **Step 4: Write the failing DB tests**

```python
# tests/clue_spine/test_hostnames_custom_db.py
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from clue_spine import create_workspace
from clue_spine.hostnames import (
    HostnameRefused,
    delete_custom_hostname,
    get_custom_hostname,
    hostname_exists,
    insert_custom_hostname,
    record_custom_hostname_check,
    replace_system_label,
    resolve_active_hostname,
    set_custom_hostname_provider,
    set_custom_hostname_status,
    system_hostname,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")
SUFFIX = "pages.test"
T0 = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def _host() -> str:
    return f"go.{uuid4().hex[:8]}.example"


def test_connect_lifecycle_rows() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(conn, name="Acme " + uuid4().hex[:4], pages_system_suffix=SUFFIX)
            host = _host()
            assert await get_custom_hostname(conn, ws.workspace_id) is None
            assert not await hostname_exists(conn, host)
            row = await insert_custom_hostname(conn, workspace_id=ws.workspace_id, hostname=host, cname_target="pages.test")
            assert row.status == "pending_dns" and row.ownership_txt_name == "pending"
            assert await hostname_exists(conn, host)
            await set_custom_hostname_provider(
                conn, hostname=host, cf_custom_hostname_id="cf_1",
                ownership_txt_name=f"_cf-custom-hostname.{host}", ownership_txt_value="tok",
            )
            checked = await record_custom_hostname_check(
                conn, hostname=host, status="verifying_ownership", observed_cname="pages.test",
                observed_txt_present=False, last_error_code=None, last_error_detail=None, checked_at=T0,
            )
            assert checked.observed_cname == "pages.test" and checked.activated_at is None
            assert await resolve_active_hostname(conn, host) is None
            active = await record_custom_hostname_check(
                conn, hostname=host, status="active", observed_cname="pages.test",
                observed_txt_present=True, last_error_code=None, last_error_detail=None, checked_at=T0,
            )
            assert active.activated_at is not None
            assert await resolve_active_hostname(conn, host) == ws.workspace_id
            await set_custom_hostname_status(conn, hostname=host, status="disconnecting")
            assert await resolve_active_hostname(conn, host) is None
            assert await delete_custom_hostname(conn, hostname=host) is True
            assert await delete_custom_hostname(conn, hostname=host) is False

    run_async(scenario())


def test_second_custom_row_and_taken_hostname_are_integrity_errors() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            a = await create_workspace(conn, name="A " + uuid4().hex[:4], pages_system_suffix=SUFFIX)
            b = await create_workspace(conn, name="B " + uuid4().hex[:4], pages_system_suffix=SUFFIX)
            host = _host()
            await insert_custom_hostname(conn, workspace_id=a.workspace_id, hostname=host, cname_target="pages.test")
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await insert_custom_hostname(conn, workspace_id=b.workspace_id, hostname=host, cname_target="pages.test")
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await insert_custom_hostname(conn, workspace_id=a.workspace_id, hostname=_host(), cname_target="pages.test")

    run_async(scenario())


def test_replace_system_label_is_atomic_and_frees_the_old_label() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(conn, name="Label " + uuid4().hex[:4], pages_system_suffix=SUFFIX)
            old = await system_hostname(conn, ws.workspace_id)
            new = await replace_system_label(conn, workspace_id=ws.workspace_id, label="acme-hq-" + uuid4().hex[:4], suffix=SUFFIX)
            assert new.kind == "system" and new.status == "active"
            assert await system_hostname(conn, ws.workspace_id) == new.hostname
            assert old is not None and await resolve_active_hostname(conn, old) is None
            other = await create_workspace(conn, name="Other " + uuid4().hex[:4], pages_system_suffix=SUFFIX)
            with pytest.raises(HostnameRefused) as caught:
                await replace_system_label(conn, workspace_id=other.workspace_id, label=new.hostname.removesuffix("." + SUFFIX), suffix=SUFFIX)
            assert caught.value.code == "label_taken"
            with pytest.raises(HostnameRefused):
                await replace_system_label(conn, workspace_id=ws.workspace_id, label="www", suffix=SUFFIX)

    run_async(scenario())
```

Run: `( set -a; source .env; set +a; uv run pytest tests/clue_spine/test_hostnames_custom_db.py -q )` → `ImportError`.

- [ ] **Step 5: Append the DAL to `hostnames.py`**

```python
# --- custom hostnames: DAL (spec §4.1, §7) -----------------------------------
_CUSTOM_ROW = (
    "hostname, workspace_id, status, cf_custom_hostname_id, cname_target, ownership_txt_name, "
    "ownership_txt_value, observed_cname, observed_txt_present, last_checked_at, last_error_code, "
    "last_error_detail, created_at, updated_at, activated_at"
)


class CustomHostname(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    hostname: str
    workspace_id: str
    status: HostnameStatus
    cf_custom_hostname_id: str | None
    cname_target: str
    ownership_txt_name: str
    ownership_txt_value: str
    observed_cname: str | None
    observed_txt_present: bool | None
    last_checked_at: UtcDatetime | None
    last_error_code: str | None
    last_error_detail: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    activated_at: UtcDatetime | None


async def get_custom_hostname(conn: AsyncConnection, workspace_id: str) -> CustomHostname | None:
    result = await conn.execute(
        text(f"SELECT {_CUSTOM_ROW} FROM workspace_hostname WHERE workspace_id = :w AND kind = 'custom'"),
        {"w": workspace_id},
    )
    row = result.mappings().first()
    return CustomHostname(**dict(row)) if row is not None else None


async def hostname_exists(conn: AsyncConnection, hostname: str) -> bool:
    result = await conn.execute(
        text("SELECT 1 FROM workspace_hostname WHERE hostname = :h"), {"h": hostname}
    )
    return result.first() is not None


async def insert_custom_hostname(
    conn: AsyncConnection, *, workspace_id: str, hostname: str, cname_target: str
) -> CustomHostname:
    """The connect insert (spec §7.3): ``pending_dns`` with placeholder ownership columns so the
    ``workspace_hostname_custom_columns`` CHECK holds until Cloudflare answers. The primary key and
    the one-custom-per-workspace index are the arbiters — a loser gets ``IntegrityError``."""
    result = await conn.execute(
        text(
            "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, cname_target, "
            "ownership_txt_name, ownership_txt_value) VALUES (:h, :w, 'custom', 'pending_dns', :t, "
            f"'pending', 'pending') RETURNING {_CUSTOM_ROW}"
        ),
        {"h": hostname, "w": workspace_id, "t": cname_target},
    )
    return CustomHostname(**dict(result.mappings().one()))


async def set_custom_hostname_provider(
    conn: AsyncConnection, *, hostname: str, cf_custom_hostname_id: str,
    ownership_txt_name: str, ownership_txt_value: str,
) -> None:
    await conn.execute(
        text(
            "UPDATE workspace_hostname SET cf_custom_hostname_id = :i, ownership_txt_name = :n, "
            "ownership_txt_value = :v, updated_at = now() WHERE hostname = :h AND kind = 'custom'"
        ),
        {"i": cf_custom_hostname_id, "n": ownership_txt_name, "v": ownership_txt_value, "h": hostname},
    )


async def record_custom_hostname_check(
    conn: AsyncConnection, *, hostname: str, status: HostnameStatus, observed_cname: str | None,
    observed_txt_present: bool | None, last_error_code: str | None, last_error_detail: str | None,
    checked_at: datetime,
) -> CustomHostname:
    result = await conn.execute(
        text(
            "UPDATE workspace_hostname SET status = :s, observed_cname = :c, observed_txt_present = :p, "
            "last_checked_at = :at, last_error_code = :ec, last_error_detail = :ed, updated_at = now(), "
            "activated_at = CASE WHEN :s = 'active' THEN COALESCE(activated_at, now()) ELSE activated_at END "
            f"WHERE hostname = :h AND kind = 'custom' RETURNING {_CUSTOM_ROW}"
        ),
        {"s": status, "c": observed_cname, "p": observed_txt_present, "at": checked_at,
         "ec": last_error_code, "ed": last_error_detail, "h": hostname},
    )
    return CustomHostname(**dict(result.mappings().one()))


async def set_custom_hostname_status(conn: AsyncConnection, *, hostname: str, status: HostnameStatus) -> None:
    await conn.execute(
        text("UPDATE workspace_hostname SET status = :s, updated_at = now() WHERE hostname = :h AND kind = 'custom'"),
        {"s": status, "h": hostname},
    )


async def delete_custom_hostname(conn: AsyncConnection, *, hostname: str) -> bool:
    result = await conn.execute(
        text("DELETE FROM workspace_hostname WHERE hostname = :h AND kind = 'custom'"), {"h": hostname}
    )
    return bool(result.rowcount)


async def replace_system_label(
    conn: AsyncConnection, *, workspace_id: str, label: str, suffix: str
) -> WorkspaceHostname:
    """Label change (spec §4.1, A1): delete the old system row and insert the new one in ONE
    transaction. The old label is free immediately; there is no redirect."""
    validate_label(label)
    hostname = f"{label}.{suffix}"
    try:
        async with conn.begin_nested():
            await conn.execute(
                text("DELETE FROM workspace_hostname WHERE workspace_id = :w AND kind = 'system'"),
                {"w": workspace_id},
            )
            result = await conn.execute(
                text(
                    "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, activated_at) "
                    f"VALUES (:h, :w, 'system', 'active', now()) RETURNING {_ROW}"
                ),
                {"h": hostname, "w": workspace_id},
            )
    except IntegrityError as error:
        raise HostnameRefused("label_taken", f"{label!r} is already in use.") from error
    return WorkspaceHostname(**dict(result.mappings().one()))
```

Add `from datetime import datetime` to the imports. Export everything new from `clue_spine/__init__.py`.

- [ ] **Step 6: Run, gates, commit.** Both test files → PASS. `uv run ruff format libs/clue-spine tests/clue_spine && uv run ruff check libs/clue-spine tests/clue_spine && uv run mypy && uv run lint-imports`.

```bash
git add libs/clue-spine tests/clue_spine/test_hostnames_custom_db.py
git commit -m "spine: custom-hostname DAL and atomic system-label change"
```

---

### Task 3: `clue_spine.pages_settings` DAL; the origin reads fallback URL and favicon

**Files:**
- Create: `libs/clue-spine/clue_spine/pages_settings.py`; modify `clue_spine/__init__.py`
- Modify: `platform/page_origin/clue_page_origin/reads.py:75-82`
- Test: `tests/clue_spine/test_pages_settings_db.py` (new)

**Interfaces:**
- Produces: `class Unset` / `UNSET`; `PagesSettings` (`workspace_id, fallback_url, page_title, page_description, favicon_sha256, social_preview_sha256, updated_at: UtcDatetime | None`);
  `get_pages_settings(conn, workspace_id) -> PagesSettings` (defaults when no row);
  `update_pages_settings(conn, *, workspace_id, fallback_url=UNSET, page_title=UNSET, page_description=UNSET, favicon_sha256=UNSET, social_preview_sha256=UNSET) -> PagesSettings` (any subset; `None` clears; raises `IntegrityError` for a non-https fallback).

- [ ] **Step 1: Write the failing test**

```python
# tests/clue_spine/test_pages_settings_db.py
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from clue_spine import create_workspace
from clue_spine.pages_settings import UNSET, get_pages_settings, update_pages_settings

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")


def test_defaults_then_partial_updates_then_clear() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(conn, name="Pages " + uuid4().hex[:4], pages_system_suffix="pages.test")
            initial = await get_pages_settings(conn, ws.workspace_id)
            assert initial.fallback_url is None and initial.updated_at is None
            first = await update_pages_settings(conn, workspace_id=ws.workspace_id, fallback_url="https://www.acme.com", page_title="Acme")
            assert first.fallback_url == "https://www.acme.com" and first.page_title == "Acme"
            assert first.page_description is None and first.updated_at is not None
            second = await update_pages_settings(conn, workspace_id=ws.workspace_id, page_description="Hello")
            assert second.fallback_url == "https://www.acme.com"  # untouched
            assert second.page_description == "Hello"
            cleared = await update_pages_settings(conn, workspace_id=ws.workspace_id, fallback_url=None)
            assert cleared.fallback_url is None and cleared.page_title == "Acme"
            assert (await get_pages_settings(conn, ws.workspace_id)) == cleared
            assert UNSET is not None
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await update_pages_settings(conn, workspace_id=ws.workspace_id, fallback_url="http://insecure.example")

    run_async(scenario())
```

Run → `ModuleNotFoundError`.

- [ ] **Step 2: Write the module**

```python
"""``workspace_pages_settings`` — one row of page defaults per workspace (custom-domain publishing §4.2).

A missing row means all defaults. Updates are partial: a field left ``UNSET`` is untouched, ``None``
clears it. Readers: the Settings → Pages screen (platform API), the page origin (fallback URL,
favicon — live), and the design API's publish (description + social-preview defaults, at publish time).
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import UtcDatetime


class Unset:
    """The "leave it alone" marker for partial updates."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = Unset()

_COLUMNS = ("fallback_url", "page_title", "page_description", "favicon_sha256", "social_preview_sha256")


class PagesSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    fallback_url: str | None = None
    page_title: str | None = None
    page_description: str | None = None
    favicon_sha256: str | None = None
    social_preview_sha256: str | None = None
    updated_at: UtcDatetime | None = None


async def get_pages_settings(conn: AsyncConnection, workspace_id: str) -> PagesSettings:
    result = await conn.execute(
        text(
            "SELECT workspace_id, fallback_url, page_title, page_description, favicon_sha256, "
            "social_preview_sha256, updated_at FROM workspace_pages_settings WHERE workspace_id = :w"
        ),
        {"w": workspace_id},
    )
    row = result.mappings().first()
    return PagesSettings(**dict(row)) if row is not None else PagesSettings(workspace_id=workspace_id)


async def update_pages_settings(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    fallback_url: str | None | Unset = UNSET,
    page_title: str | None | Unset = UNSET,
    page_description: str | None | Unset = UNSET,
    favicon_sha256: str | None | Unset = UNSET,
    social_preview_sha256: str | None | Unset = UNSET,
) -> PagesSettings:
    provided = {
        name: value
        for name, value in (
            ("fallback_url", fallback_url), ("page_title", page_title), ("page_description", page_description),
            ("favicon_sha256", favicon_sha256), ("social_preview_sha256", social_preview_sha256),
        )
        if not isinstance(value, Unset)
    }
    if not provided:
        return await get_pages_settings(conn, workspace_id)
    columns = ", ".join(provided)
    placeholders = ", ".join(f":{name}" for name in provided)
    assignments = ", ".join(f"{name} = EXCLUDED.{name}" for name in provided)
    result = await conn.execute(
        text(
            f"INSERT INTO workspace_pages_settings (workspace_id, {columns}) VALUES (:w, {placeholders}) "
            f"ON CONFLICT (workspace_id) DO UPDATE SET {assignments}, updated_at = now() "
            "RETURNING workspace_id, fallback_url, page_title, page_description, favicon_sha256, "
            "social_preview_sha256, updated_at"
        ),
        {"w": workspace_id, **provided},
    )
    return PagesSettings(**dict(result.mappings().one()))
```

Export `PagesSettings, UNSET, Unset, get_pages_settings, update_pages_settings` from `clue_spine/__init__.py`.

- [ ] **Step 3: Wire the origin.** In `platform/page_origin/clue_page_origin/reads.py`, add
  `from clue_spine.pages_settings import get_pages_settings` and replace the two stubs:

```python
    async def fallback_url(self, workspace_id: str) -> str | None:
        async with self._conn_factory() as conn:
            return (await get_pages_settings(conn, workspace_id)).fallback_url

    async def favicon(self, workspace_id: str) -> tuple[str, bytes] | None:
        async with self._conn_factory() as conn:
            sha256 = (await get_pages_settings(conn, workspace_id)).favicon_sha256
            if sha256 is None:
                return None
            try:
                return await read_design_blob(conn, self._storage, workspace_id=workspace_id, sha256=sha256)
            except DesignNotFoundError:
                return None
```

- [ ] **Step 4: Run, gates, commit.** `( set -a; source .env; set +a; uv run pytest tests/clue_spine/test_pages_settings_db.py tests/page_origin -q -p no:warnings )` → PASS. Gates as usual.

```bash
git add libs/clue-spine platform/page_origin tests/clue_spine/test_pages_settings_db.py
git commit -m "spine: workspace pages-settings DAL; page origin serves the fallback URL and favicon"
```

---

### Task 4: Cloudflare custom-hostnames client

**Files:**
- Create: `platform/api/clue_api/cloudflare_custom_hostnames.py`
- Test: `tests/api/test_cloudflare_custom_hostnames.py` (new, no DB)

**Interfaces:**
- Produces: `@dataclass(frozen=True) CustomHostnameRecord(id: str, status: str, ssl_status: str | None, ownership_txt_name: str | None, ownership_txt_value: str | None, verification_errors: tuple[str, ...], ssl_validation_errors: tuple[str, ...])`;
  `class CloudflareError(Exception)` with `.status: int | None`, `.message: str`, `.retryable: bool`;
  `class CloudflareCustomHostnames(*, zone_id: str, api_token: str, client: httpx.AsyncClient | None = None, base_url: str = "https://api.cloudflare.com/client/v4")` with `async create(hostname) -> CustomHostnameRecord`, `async get(custom_hostname_id) -> CustomHostnameRecord | None` (None when Cloudflare answers 404), `async delete(custom_hostname_id) -> None` (404 is success).

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_cloudflare_custom_hostnames.py
from __future__ import annotations

import json

import httpx
import pytest

from clue_api.cloudflare_custom_hostnames import CloudflareCustomHostnames, CloudflareError
from tests.db.conftest import run_async

ZONE = "zone123"
CREATED = {
    "success": True, "errors": [], "messages": [],
    "result": {
        "id": "ch_1", "hostname": "go.acme.com", "status": "pending",
        "ssl": {"status": "pending_validation", "method": "http", "type": "dv", "validation_errors": []},
        "ownership_verification": {"type": "txt", "name": "_cf-custom-hostname.go.acme.com", "value": "tok-1"},
        "verification_errors": [],
    },
}


def _client(handler):  # type: ignore[no-untyped-def]
    return CloudflareCustomHostnames(
        zone_id=ZONE, api_token="t0k", client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def test_create_sends_the_documented_body_and_parses_the_record() -> None:
    async def scenario() -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(201, json=CREATED)

        record = await _client(handler).create("go.acme.com")
        assert seen[0].method == "POST" and seen[0].url.path == f"/client/v4/zones/{ZONE}/custom_hostnames"
        assert seen[0].headers["authorization"] == "Bearer t0k"
        assert json.loads(seen[0].content) == {"hostname": "go.acme.com", "ssl": {"method": "http", "type": "dv"}}
        assert record.id == "ch_1" and record.status == "pending" and record.ssl_status == "pending_validation"
        assert record.ownership_txt_name == "_cf-custom-hostname.go.acme.com" and record.ownership_txt_value == "tok-1"


    run_async(scenario())

def test_get_parses_errors_and_404_is_none() -> None:
    async def scenario() -> None:
        body = json.loads(json.dumps(CREATED))
        body["result"]["status"] = "active"
        body["result"]["ssl"]["status"] = "active"
        body["result"]["ssl"]["validation_errors"] = [{"message": "CAA record prevents issuance"}]
        body["result"]["verification_errors"] = ["ownership verification pending"]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ch_1"):
                return httpx.Response(200, json=body)
            return httpx.Response(404, json={"success": False, "errors": [{"code": 1436, "message": "not found"}], "result": None})

        client = _client(handler)
        record = await client.get("ch_1")
        assert record is not None and record.status == "active" and record.ssl_status == "active"
        assert record.ssl_validation_errors == ("CAA record prevents issuance",)
        assert record.verification_errors == ("ownership verification pending",)
        assert await client.get("ch_missing") is None


    run_async(scenario())

def test_delete_treats_404_as_deleted_and_5xx_retries_once() -> None:
    async def scenario() -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if request.method == "DELETE" and request.url.path.endswith("/gone"):
                return httpx.Response(404, json={"success": False, "errors": [{"code": 1436, "message": "not found"}]})
            if calls["n"] == 1:
                return httpx.Response(502, text="bad gateway")
            return httpx.Response(200, json={"success": True, "errors": [], "result": {"id": "ch_1"}})

        client = _client(handler)
        await client.delete("gone")
        calls["n"] = 0
        await client.delete("ch_1")
        assert calls["n"] == 2  # one retry on 5xx


    run_async(scenario())

def test_4xx_is_a_non_retryable_cloudflare_error_with_the_message() -> None:
    async def scenario() -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"success": False, "errors": [{"code": 1406, "message": "Duplicate custom hostname found."}], "result": None})

        with pytest.raises(CloudflareError) as caught:
            await _client(handler).create("go.acme.com")
        assert caught.value.status == 409 and not caught.value.retryable
        assert "Duplicate custom hostname" in caught.value.message


    run_async(scenario())

def test_persistent_5xx_is_retryable() -> None:
    async def scenario() -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="down")

        with pytest.raises(CloudflareError) as caught:
            await _client(handler).create("go.acme.com")
        assert caught.value.retryable and caught.value.status == 503

    run_async(scenario())
```

The repo has no async test plugin, hence the inner `async def scenario()` + `run_async(scenario())`
shape (the `tests/db/conftest.py` pattern used everywhere in `tests/`).

Run: `uv run pytest tests/api/test_cloudflare_custom_hostnames.py -q` → `ModuleNotFoundError`.

- [ ] **Step 2: Write the client**

```python
"""Cloudflare for SaaS custom hostnames — the three calls the control plane makes (spec §7.7).

The ONLY module that knows Cloudflare's field names. ``httpx`` bearer auth, 10 s timeouts, one retry
on a 5xx or a transport failure, never on a 4xx. Field names follow the v4 API reference for
``/zones/{zone_id}/custom_hostnames`` and are pinned by ``tests/api/test_cloudflare_custom_hostnames.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from clue_obs import get_logger

log = get_logger("clue_api.cloudflare_custom_hostnames")
_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class CustomHostnameRecord:
    id: str
    status: str
    ssl_status: str | None
    ownership_txt_name: str | None
    ownership_txt_value: str | None
    verification_errors: tuple[str, ...]
    ssl_validation_errors: tuple[str, ...]


class CloudflareError(Exception):
    def __init__(self, message: str, *, status: int | None, retryable: bool) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.retryable = retryable


def _messages(items: Any) -> tuple[str, ...]:
    out: list[str] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and isinstance(item.get("message"), str):
            out.append(item["message"])
        elif isinstance(item, str):
            out.append(item)
    return tuple(out)


def _record(result: Any) -> CustomHostnameRecord:
    if not isinstance(result, dict) or not isinstance(result.get("id"), str):
        raise CloudflareError("Cloudflare returned no custom hostname record", status=None, retryable=False)
    ssl = result.get("ssl") if isinstance(result.get("ssl"), dict) else {}
    ownership = result.get("ownership_verification") if isinstance(result.get("ownership_verification"), dict) else {}
    return CustomHostnameRecord(
        id=result["id"],
        status=str(result.get("status") or "pending"),
        ssl_status=str(ssl["status"]) if isinstance(ssl.get("status"), str) else None,
        ownership_txt_name=ownership.get("name") if isinstance(ownership.get("name"), str) else None,
        ownership_txt_value=ownership.get("value") if isinstance(ownership.get("value"), str) else None,
        verification_errors=_messages(result.get("verification_errors")),
        ssl_validation_errors=_messages(ssl.get("validation_errors")),
    )


class CloudflareCustomHostnames:
    def __init__(
        self, *, zone_id: str, api_token: str, client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.cloudflare.com/client/v4",
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=_TIMEOUT_S)
        self._base = f"{base_url.rstrip('/')}/zones/{zone_id}/custom_hostnames"
        self._headers = {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}

    async def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> httpx.Response:
        last: CloudflareError | None = None
        for attempt in (1, 2):
            try:
                response = await self._client.request(
                    method, f"{self._base}{path}", json=json, headers=self._headers, timeout=_TIMEOUT_S
                )
            except httpx.HTTPError as error:
                last = CloudflareError(f"Cloudflare unreachable: {error}", status=None, retryable=True)
                continue
            if response.status_code >= 500:
                last = CloudflareError(f"Cloudflare {response.status_code}: {response.text[:200]}", status=response.status_code, retryable=True)
                continue
            return response
        assert last is not None
        log.warning("cloudflare.custom_hostnames.failed", method=method, path=path, status=last.status)
        raise last

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:200] or f"HTTP {response.status_code}"
        messages = _messages(body.get("errors")) if isinstance(body, dict) else ()
        return "; ".join(messages) or f"HTTP {response.status_code}"

    async def create(self, hostname: str) -> CustomHostnameRecord:
        response = await self._request("POST", "", json={"hostname": hostname, "ssl": {"method": "http", "type": "dv"}})
        if response.status_code >= 400:
            raise CloudflareError(self._error_message(response), status=response.status_code, retryable=False)
        return _record(response.json().get("result"))

    async def get(self, custom_hostname_id: str) -> CustomHostnameRecord | None:
        response = await self._request("GET", f"/{custom_hostname_id}")
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise CloudflareError(self._error_message(response), status=response.status_code, retryable=False)
        return _record(response.json().get("result"))

    async def delete(self, custom_hostname_id: str) -> None:
        response = await self._request("DELETE", f"/{custom_hostname_id}")
        if response.status_code == 404 or response.status_code < 400:
            return
        raise CloudflareError(self._error_message(response), status=response.status_code, retryable=False)
```

- [ ] **Step 3: Run, gates, commit.** Tests → PASS. `uv run ruff format platform/api/clue_api/cloudflare_custom_hostnames.py tests/api/test_cloudflare_custom_hostnames.py && uv run ruff check … && uv run mypy && uv run lint-imports`.

```bash
git add platform/api/clue_api/cloudflare_custom_hostnames.py tests/api/test_cloudflare_custom_hostnames.py
git commit -m "api: Cloudflare custom-hostnames client (create/get/delete, recorded-fixture tests)"
```

---

### Task 5: DNS observation and pure status derivation

**Files:**
- Create: `platform/api/clue_api/dns_observe.py`, `platform/api/clue_api/pages_hostname_status.py`
- Test: `tests/api/test_dns_observe.py`, `tests/api/test_pages_hostname_status.py` (both no DB)

**Interfaces:**
- `dns_observe`: `@dataclass(frozen=True) DnsObservation(cname: str | None, txt_values: tuple[str, ...], error: str | None)`;
  `class DnsResolver(Protocol): def resolve(self, name: str, rdtype: str) -> list[str]` (empty list = no such record; raises `DnsLookupError` on resolver failure);
  `class DnsLookupError(Exception)`; `class PublicDnsResolver` (dnspython over `1.1.1.1`, `8.8.8.8`, lifetime 5 s);
  `observe_hostname(hostname: str, txt_name: str, *, resolver: DnsResolver) -> DnsObservation` (sync; the service wraps it in `asyncio.to_thread`).
- `pages_hostname_status`: `@dataclass(frozen=True) ProviderState(status: str, ssl_status: str | None, verification_errors: tuple[str, ...], ssl_validation_errors: tuple[str, ...], deleted: bool = False)`;
  `@dataclass(frozen=True) StatusDecision(status: str, error_code: str | None, error_detail: str | None)`;
  `TXT_GRACE = timedelta(minutes=30)`;
  `derive_status(*, observation: DnsObservation, provider: ProviderState | None, cname_target: str, expected_txt_value: str, connected_at: datetime, now: datetime) -> StatusDecision`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_dns_observe.py
from __future__ import annotations

from clue_api.dns_observe import DnsLookupError, DnsObservation, observe_hostname


class FakeResolver:
    def __init__(self, records: dict[tuple[str, str], list[str]], *, fail: bool = False) -> None:
        self.records = records
        self.fail = fail

    def resolve(self, name: str, rdtype: str) -> list[str]:
        if self.fail:
            raise DnsLookupError("SERVFAIL")
        return self.records.get((name, rdtype), [])


def test_observation_reports_cname_and_txt_values() -> None:
    resolver = FakeResolver({("go.acme.com", "CNAME"): ["pages.cluehq.ai"], ("_cf-custom-hostname.go.acme.com", "TXT"): ["tok-1", "other"]})
    seen = observe_hostname("go.acme.com", "_cf-custom-hostname.go.acme.com", resolver=resolver)
    assert seen == DnsObservation(cname="pages.cluehq.ai", txt_values=("tok-1", "other"), error=None)


def test_missing_records_are_none_and_empty() -> None:
    seen = observe_hostname("go.acme.com", "_cf-custom-hostname.go.acme.com", resolver=FakeResolver({}))
    assert seen.cname is None and seen.txt_values == () and seen.error is None


def test_resolver_failure_is_reported_not_raised() -> None:
    seen = observe_hostname("go.acme.com", "_cf-custom-hostname.go.acme.com", resolver=FakeResolver({}, fail=True))
    assert seen.cname is None and "SERVFAIL" in (seen.error or "")
```

```python
# tests/api/test_pages_hostname_status.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from clue_api.dns_observe import DnsObservation
from clue_api.pages_hostname_status import ProviderState, derive_status

T0 = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
TARGET = "pages.cluehq.ai"
OK_PROVIDER = ProviderState(status="active", ssl_status="active", verification_errors=(), ssl_validation_errors=())
PENDING_PROVIDER = ProviderState(status="pending", ssl_status="pending_validation", verification_errors=(), ssl_validation_errors=())


def _obs(cname: str | None, *txt: str, error: str | None = None) -> DnsObservation:
    return DnsObservation(cname=cname, txt_values=tuple(txt), error=error)


@pytest.mark.parametrize(
    ("observation", "provider", "now", "status", "code"),
    [
        (_obs(None), PENDING_PROVIDER, T0, "pending_dns", None),
        (_obs("elsewhere.example"), PENDING_PROVIDER, T0, "error", "cname_incorrect"),
        (_obs(TARGET), PENDING_PROVIDER, T0, "verifying_ownership", None),
        (_obs(TARGET), OK_PROVIDER, T0, "verifying_ownership", None),  # our TXT rule beats Cloudflare's active
        (_obs(TARGET), PENDING_PROVIDER, T0 + timedelta(minutes=31), "error", "txt_missing"),
        (_obs(TARGET, "tok"), PENDING_PROVIDER, T0, "issuing_certificate", None),
        (_obs(TARGET, "tok"), ProviderState("active", "pending_validation", (), ()), T0, "issuing_certificate", None),
        (_obs(TARGET, "tok"), OK_PROVIDER, T0, "active", None),
        (_obs(TARGET, "tok"), ProviderState("pending", "pending_validation", (), ("CAA record at acme.com prevents issuance",)), T0, "error", "caa_blocked"),
        (_obs(TARGET, "tok"), ProviderState("pending", "pending_validation", ("Custom hostname already exists elsewhere (1034)",), ()), T0, "error", "provider_error"),
        (_obs(TARGET, "tok"), ProviderState("moved", "active", (), ()), T0, "error", "verification_expired"),
        (_obs(TARGET, "tok"), None, T0, "error", "verification_expired"),
        (_obs(None, error="SERVFAIL"), PENDING_PROVIDER, T0, "error", "provider_error"),
    ],
)
def test_ladder(observation: DnsObservation, provider: ProviderState | None, now: datetime, status: str, code: str | None) -> None:
    decision = derive_status(observation=observation, provider=provider, cname_target=TARGET, expected_txt_value="tok", connected_at=T0, now=now)
    assert (decision.status, decision.error_code) == (status, code)
    assert (decision.error_detail is not None) == (code is not None)


def test_cname_comparison_ignores_case_and_trailing_dot() -> None:
    decision = derive_status(observation=_obs("Pages.CluehQ.ai.", "tok"), provider=OK_PROVIDER, cname_target=TARGET, expected_txt_value="tok", connected_at=T0, now=T0)
    assert decision.status == "active"
```

Run both → `ModuleNotFoundError`.

- [ ] **Step 2: Write `dns_observe.py`**

```python
"""DNS observation for custom hostnames (spec §7.4): CNAME of the hostname and TXT at the ownership
name, through PUBLIC resolvers so a cached local answer cannot mislead. Synchronous (dnspython);
callers run it in a thread."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

PUBLIC_NAMESERVERS = ("1.1.1.1", "8.8.8.8")
_LIFETIME_S = 5.0


class DnsLookupError(Exception):
    """The resolver itself failed (timeout, SERVFAIL); distinct from "no such record"."""


class DnsResolver(Protocol):
    def resolve(self, name: str, rdtype: str) -> list[str]: ...


@dataclass(frozen=True)
class DnsObservation:
    cname: str | None
    txt_values: tuple[str, ...]
    error: str | None


class PublicDnsResolver:
    def __init__(self, nameservers: tuple[str, ...] = PUBLIC_NAMESERVERS) -> None:
        import dns.resolver  # lazy: importing this module must not need dnspython at import time

        self._resolver = dns.resolver.Resolver(configure=False)
        self._resolver.nameservers = list(nameservers)
        self._resolver.lifetime = _LIFETIME_S

    def resolve(self, name: str, rdtype: str) -> list[str]:
        import dns.exception
        import dns.resolver

        try:
            answer = self._resolver.resolve(name, rdtype, raise_on_no_answer=False)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers) as error:
            if isinstance(error, dns.resolver.NXDOMAIN):
                return []
            raise DnsLookupError(str(error)) from error
        except dns.exception.DNSException as error:
            raise DnsLookupError(str(error)) from error
        values: list[str] = []
        for rdata in answer:
            if rdtype == "CNAME":
                values.append(str(rdata.target).rstrip(".").lower())
            elif rdtype == "TXT":
                values.append(b"".join(rdata.strings).decode("utf-8", "replace"))
            else:
                values.append(str(rdata))
        return values


def observe_hostname(hostname: str, txt_name: str, *, resolver: DnsResolver) -> DnsObservation:
    try:
        cnames = resolver.resolve(hostname, "CNAME")
        txts = resolver.resolve(txt_name, "TXT")
    except DnsLookupError as error:
        return DnsObservation(cname=None, txt_values=(), error=str(error))
    return DnsObservation(cname=cnames[0].rstrip(".").lower() if cnames else None, txt_values=tuple(txts), error=None)
```

- [ ] **Step 3: Write `pages_hostname_status.py`**

```python
"""Status derivation for a custom hostname (spec §7.4) and the closed error-code set (§7.5). Pure."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from clue_api.dns_observe import DnsObservation

TXT_GRACE = timedelta(minutes=30)


@dataclass(frozen=True)
class ProviderState:
    status: str
    ssl_status: str | None
    verification_errors: tuple[str, ...]
    ssl_validation_errors: tuple[str, ...]
    deleted: bool = False


@dataclass(frozen=True)
class StatusDecision:
    status: str
    error_code: str | None
    error_detail: str | None


def _error(code: str, detail: str) -> StatusDecision:
    return StatusDecision(status="error", error_code=code, error_detail=detail)


def derive_status(
    *, observation: DnsObservation, provider: ProviderState | None, cname_target: str,
    expected_txt_value: str, connected_at: datetime, now: datetime,
) -> StatusDecision:
    if provider is None or provider.deleted or provider.status in ("moved", "deleted"):
        return _error("verification_expired", "Cloudflare no longer holds this hostname; remove it and connect again.")
    if observation.error:
        return _error("provider_error", f"DNS lookup failed: {observation.error}")
    caa = [m for m in provider.ssl_validation_errors if "caa" in m.lower()]
    if caa:
        return _error("caa_blocked", caa[0])
    other = (*provider.verification_errors, *provider.ssl_validation_errors)
    if other:
        return _error("provider_error", "; ".join(other))
    observed = observation.cname.rstrip(".").lower() if observation.cname else None
    if observed is None:
        return StatusDecision(status="pending_dns", error_code=None, error_detail=None)
    if observed != cname_target.rstrip(".").lower():
        return _error("cname_incorrect", f"CNAME points at {observed}, expected {cname_target}.")
    if expected_txt_value not in observation.txt_values:
        if now - connected_at > TXT_GRACE:
            return _error("txt_missing", "The ownership TXT record has not appeared; add it to your DNS.")
        return StatusDecision(status="verifying_ownership", error_code=None, error_detail=None)
    if provider.status != "active" or provider.ssl_status != "active":
        return StatusDecision(status="issuing_certificate", error_code=None, error_detail=None)
    return StatusDecision(status="active", error_code=None, error_detail=None)
```

- [ ] **Step 4: Run, gates, commit.** Both files → PASS.

```bash
git add platform/api/clue_api/dns_observe.py platform/api/clue_api/pages_hostname_status.py tests/api/test_dns_observe.py tests/api/test_pages_hostname_status.py
git commit -m "api: DNS observation over public resolvers and the custom-hostname status ladder"
```

---

### Task 6: `workspace.manage_settings` — policy revision 3

**Files:**
- Modify: `platform/auth/clue_auth/policy.py`
- Test: `tests/auth/test_policy.py` (extend, or the file that asserts `ROLE_POLICY_VERSION` — find with `grep -rn "ROLE_POLICY_VERSION\|manage_members" tests/auth`)

- [ ] **Step 1: Write the failing test** (add to the existing policy test module):

```python
def test_manage_settings_is_admin_and_owner_only_at_revision_3() -> None:
    from clue_auth.policy import ROLE_POLICY_VERSION, role_has_permission

    assert ROLE_POLICY_VERSION == 3
    assert role_has_permission("owner", "workspace.manage_settings")
    assert role_has_permission("admin", "workspace.manage_settings")
    assert not role_has_permission("operator", "workspace.manage_settings")
    assert not role_has_permission("viewer", "workspace.manage_settings")
```

Run → FAIL (`ROLE_POLICY_VERSION == 2`, and the Literal rejects the string under mypy).

- [ ] **Step 2: Change the policy.** In `policy.py`: add `"workspace.manage_settings",` after `"workspace.manage_members",` in `Permission`; set `ROLE_POLICY_VERSION = 3`; extend `_MANAGE` to
  `_OPERATE | frozenset({"research.approve_spend", "workspace.manage_members", "workspace.manage_settings"})`.
  Update any existing test that asserts the exact `_MANAGE` set or version 2. Search `platform`/`tests`
  for `ROLE_POLICY_VERSION` consumers that persist the version (a DB column or a resolver check) and
  keep them consistent (the version is resolved at authorization time per the B2 comment; no migration).

- [ ] **Step 3: Run, gates, commit.** `( set -a; source .env; set +a; uv run pytest tests/auth -q -p no:warnings --ignore-glob='*_live.py' )` → PASS.

```bash
git add platform/auth tests/auth
git commit -m "auth: workspace.manage_settings permission (policy revision 3)"
```

---

### Task 7: Settings → Pages control plane — read, PATCH, uploads, label change

**Files:**
- Create: `platform/api/clue_api/frontend_read/settings_pages.py`
- Modify: `platform/api/clue_api/frontend_read/app.py` (register call next to `register_artifact_routes`, ~line 309; pass `settings=settings, secrets=secrets, storage=evidence_storage, allow_local_mutations=allow_local_mutations`)
- Test: `tests/api/test_frontend_read_settings_pages_db.py` (new)

**Interfaces:**
- Produces wire models (all `WireModel` subclasses from `clue_api.frontend_read.accounts_list`): `PagesSettingsWire(fallback_url, page_title, page_description, favicon_url, social_preview_url)`, `SystemHostnameWire(hostname, label, url)`, `DnsRecordWire(type, name, required, observed, ok)`, `HostnameErrorWire(code, detail)`, `CustomHostnameWire(hostname, status, records, last_checked_at, error, url)`, `PagesSettingsReadWire(settings, system_hostname, custom_hostname)` → serialises as spec §7.2.
- Produces `PagesSettingsService(conn_factory, *, settings, storage, cloudflare: CloudflareCustomHostnames | None, resolver: DnsResolver | None, clock: Callable[[], datetime] = lambda: datetime.now(UTC))` with `read`, `update_settings`, `store_image`, `change_label` (this task) and `connect`, `check`, `remove` (Task 8).
- Produces `register_settings_pages_routes(router, *, conn_factory, settings, secrets, storage, allow_local_mutations, cloudflare=None, resolver=None)`.
- Routes (this task): `GET /settings/pages`, `PATCH /settings/pages`, `POST /settings/pages/favicon`, `POST /settings/pages/social-preview`, `PATCH /settings/pages/system-hostname`.

- [ ] **Step 1: Write the failing tests** (harness copied from `tests/api/test_frontend_read_artifacts_db.py`: `_app`, `_app_with_principal`, `rollback_conn(seed_pack=False)`, `seed_principal`; build the principal's `permissions` explicitly so one fixture has `workspace.manage_settings` and one does not)

```python
# tests/api/test_frontend_read_settings_pages_db.py
"""Settings → Pages control plane (custom-domain publishing §7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import Request
from httpx import ASGITransport

from clue_api.chat import RequestPrincipal
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.app import frontend_read_workspace_resolver
from clue_api.projections_app import create_projections_app
from clue_auth.policy import permissions_for_role
from clue_config import load_settings
from clue_spine import create_workspace
from clue_storage import FsStorage
from tests._identity import fixture_membership_id, seed_principal
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")
BASE = f"{FRONTEND_READ_PREFIX}/settings/pages"
USER_ID = "usr_pages_settings"
SUFFIX = "pages.test"


def _settings(**overrides: Any) -> Any:
    return load_settings(
        _env_file=None, frontend_read_enabled=True, arv2_display_generate_on_read=False,
        pages_system_suffix=SUFFIX, pages_public_scheme="https", pages_public_port=None,
        pages_cname_target="pages.test", **overrides,
    )


class TickingClock:
    """Each call is 10 s later than the last, so consecutive checks clear the 5 s rate limit;
    `hold()` freezes it to prove the limit."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
        self.frozen = False

    def __call__(self) -> datetime:
        if not self.frozen:
            self.now = self.now + timedelta(seconds=10)
        return self.now


def _app(conn: Any, tmp_path: Any, *, role: str, cloudflare: Any = None, resolver: Any = None, clock: Any = None) -> Any:
    app = create_projections_app(
        surface=None, tool_invoker=None,  # type: ignore[arg-type]
        settings=_settings(), conn_factory=conn_session_factory(conn), manage_db_lifespan=False,
        ingestion_storage=FsStorage(tmp_path / "blobs"),
    )
    # The route builder accepts injected fakes for the provider and the resolver; the projections
    # app threads them through `build_frontend_read_router(..., pages_cloudflare=, pages_resolver=)`.
    if cloudflare is not None:
        app.state.pages_cloudflare = cloudflare
    if resolver is not None:
        app.state.pages_resolver = resolver
    if clock is not None:
        app.state.pages_clock = clock

    async def _resolver(request: Request) -> str:
        workspace_id = request.headers["X-Workspace-Id"]
        request.state.clue_principal = RequestPrincipal(
            user_id=USER_ID, membership_id=fixture_membership_id(workspace_id=workspace_id, user_id=USER_ID),
            workspace_id=workspace_id, role_key=role, permissions=permissions_for_role(role),  # type: ignore[arg-type]
            authenticated_at=datetime(2026, 9, 17, 9, 0, tzinfo=UTC),
        )
        return workspace_id

    app.dependency_overrides[frontend_read_workspace_resolver] = _resolver
    return app


async def _workspace(conn: Any) -> str:
    ws = await create_workspace(conn, name="Acme " + uuid4().hex[:4], pages_system_suffix=SUFFIX)
    await seed_principal(conn, workspace_id=ws.workspace_id, user_id=USER_ID)
    return ws.workspace_id


def test_read_defaults_and_the_system_hostname(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            async with httpx.AsyncClient(transport=ASGITransport(app=_app(conn, tmp_path, role="viewer")), base_url="http://t") as client:
                response = await client.get(BASE, headers={"X-Workspace-Id": ws})
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["settings"] == {"fallbackUrl": None, "pageTitle": None, "pageDescription": None, "faviconUrl": None, "socialPreviewUrl": None}
            assert body["systemHostname"]["hostname"].endswith("." + SUFFIX)
            assert body["systemHostname"]["url"] == "https://" + body["systemHostname"]["hostname"]
            assert body["systemHostname"]["label"] == body["systemHostname"]["hostname"].removesuffix("." + SUFFIX)
            assert body["customHostname"] is None

    run_async(scenario())


def test_patch_needs_manage_settings_and_clears_with_null(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            headers = {"X-Workspace-Id": ws}
            async with httpx.AsyncClient(transport=ASGITransport(app=_app(conn, tmp_path, role="operator")), base_url="http://t") as client:
                denied = await client.patch(BASE, json={"fallbackUrl": "https://www.acme.com"}, headers=headers)
            assert denied.status_code == 403 and denied.json()["error"]["code"] == "PERMISSION_REQUIRED"
            async with httpx.AsyncClient(transport=ASGITransport(app=_app(conn, tmp_path, role="admin")), base_url="http://t") as client:
                ok = await client.patch(BASE, json={"fallbackUrl": "https://www.acme.com", "pageTitle": "Acme"}, headers=headers)
                assert ok.status_code == 200, ok.text
                assert ok.json()["settings"]["fallbackUrl"] == "https://www.acme.com"
                cleared = await client.patch(BASE, json={"fallbackUrl": None}, headers=headers)
                assert cleared.json()["settings"]["fallbackUrl"] is None and cleared.json()["settings"]["pageTitle"] == "Acme"
                bad = await client.patch(BASE, json={"fallbackUrl": "http://insecure.example"}, headers=headers)
                assert bad.status_code == 422

    run_async(scenario())


def test_favicon_and_social_preview_uploads(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            headers = {"X-Workspace-Id": ws}
            async with httpx.AsyncClient(transport=ASGITransport(app=_app(conn, tmp_path, role="owner")), base_url="http://t") as client:
                favicon = await client.post(f"{BASE}/favicon", files={"file": ("f.png", b"\x89PNGfake", "image/png")}, headers=headers)
                assert favicon.status_code == 200, favicon.text
                assert favicon.json()["settings"]["faviconUrl"].endswith("/favicon.ico")
                too_big = await client.post(f"{BASE}/favicon", files={"file": ("f.png", b"x" * (256 * 1024 + 1), "image/png")}, headers=headers)
                assert too_big.status_code == 413
                wrong_type = await client.post(f"{BASE}/favicon", files={"file": ("f.gif", b"GIF89a", "image/gif")}, headers=headers)
                assert wrong_type.status_code == 415
                social = await client.post(f"{BASE}/social-preview", files={"file": ("s.jpg", b"\xff\xd8fake", "image/jpeg")}, headers=headers)
                assert social.status_code == 200 and "/asset-store/" in social.json()["settings"]["socialPreviewUrl"]

    run_async(scenario())


def test_label_change_is_validated_and_atomic(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            headers = {"X-Workspace-Id": ws}
            async with httpx.AsyncClient(transport=ASGITransport(app=_app(conn, tmp_path, role="admin")), base_url="http://t") as client:
                label = "acme-hq-" + uuid4().hex[:4]
                ok = await client.patch(f"{BASE}/system-hostname", json={"label": label}, headers=headers)
                assert ok.status_code == 200 and ok.json()["systemHostname"]["label"] == label
                reserved = await client.patch(f"{BASE}/system-hostname", json={"label": "www"}, headers=headers)
                assert reserved.status_code == 422 and reserved.json()["error"]["code"] == "label_reserved"

    run_async(scenario())
```

Run: `( set -a; source .env; set +a; uv run pytest tests/api/test_frontend_read_settings_pages_db.py -q -p no:warnings )` → 404s (route missing).

- [ ] **Step 2: Write the module (read/PATCH/uploads/label parts)**

```python
"""Settings → Pages control plane (custom-domain publishing §7): page defaults, the Clue address
label, and (Task 8) connecting / checking / removing ONE customer hostname."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from clue_api.auth_wiring import principal_from_request
from clue_api.cloudflare_custom_hostnames import CloudflareCustomHostnames, CloudflareError
from clue_api.dns_observe import DnsResolver, PublicDnsResolver, observe_hostname
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.pages_hostname_status import ProviderState, derive_status
from clue_config import Secrets, Settings
from clue_db import ConnFactory
from clue_design.storage import register_design_bytes
from clue_obs import get_logger
from clue_spine.hostnames import (
    HostnameRefused, delete_custom_hostname, get_custom_hostname, hostname_exists,
    insert_custom_hostname, public_origin, record_custom_hostname_check, replace_system_label,
    set_custom_hostname_provider, set_custom_hostname_status, system_hostname,
    validate_custom_hostname,
)
from clue_spine.pages_settings import UNSET, Unset, get_pages_settings, update_pages_settings
from clue_storage import StorageBackend, content_address

log = get_logger("clue_api.frontend_read.settings_pages")

FAVICON_TYPES = {"image/png", "image/x-icon", "image/vnd.microsoft.icon", "image/svg+xml"}
SOCIAL_TYPES = {"image/png", "image/jpeg"}
FAVICON_MAX = 256 * 1024
SOCIAL_MAX = 2 * 1024 * 1024
CHECK_INTERVAL_S = 5.0


# --- wire (spec §7.2) ------------------------------------------------------
class PagesSettingsWire(WireModel):
    fallback_url: str | None
    page_title: str | None
    page_description: str | None
    favicon_url: str | None
    social_preview_url: str | None


class SystemHostnameWire(WireModel):
    hostname: str
    label: str
    url: str


class DnsRecordWire(WireModel):
    type: Literal["CNAME", "TXT"]
    name: str
    required: str
    observed: str | None
    ok: bool


class HostnameErrorWire(WireModel):
    code: str
    detail: str | None


class CustomHostnameWire(WireModel):
    hostname: str
    status: str
    records: list[DnsRecordWire]
    last_checked_at: str | None
    error: HostnameErrorWire | None
    url: str | None


class PagesSettingsReadWire(WireModel):
    settings: PagesSettingsWire
    system_hostname: SystemHostnameWire
    custom_hostname: CustomHostnameWire | None


class PagesSettingsPatch(BaseModel):
    fallback_url: str | None | Unset = Field(default=UNSET, alias="fallbackUrl")
    page_title: str | None | Unset = Field(default=UNSET, alias="pageTitle")
    page_description: str | None | Unset = Field(default=UNSET, alias="pageDescription")
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, populate_by_name=True)


class LabelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str


class ConnectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hostname: str


def _refusal(status_code: int, code: str, message: str, *, extra: dict[str, Any] | None = None) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message, **(extra or {})})


def require_manage_settings(request: Request, *, allow_local_mutations: bool) -> None:
    principal = principal_from_request(request)
    if principal is not None:
        if "workspace.manage_settings" not in principal.permissions:
            raise _refusal(403, "PERMISSION_REQUIRED", "workspace.manage_settings is required")
        return
    if not allow_local_mutations:
        raise _refusal(401, "UNAUTHORIZED", "An authenticated session is required.")


class PagesSettingsService:
    def __init__(
        self, conn_factory: ConnFactory, *, settings: Settings, storage: StorageBackend | None,
        cloudflare: CloudflareCustomHostnames | None, resolver: DnsResolver | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._conn_factory = conn_factory
        self._settings = settings
        self._storage = storage
        self._cloudflare = cloudflare
        self._resolver = resolver
        self._clock = clock

    # -- shapes --------------------------------------------------------------
    def _origin(self, hostname: str) -> str:
        return public_origin(hostname, scheme=self._settings.pages_public_scheme, port=self._settings.pages_public_port)

    async def read(self, workspace_id: str) -> PagesSettingsReadWire:
        async with self._conn_factory() as conn:
            row = await get_pages_settings(conn, workspace_id)
            system = await system_hostname(conn, workspace_id)
            custom = await get_custom_hostname(conn, workspace_id)
        if system is None:
            raise _refusal(500, "SYSTEM_HOSTNAME_MISSING", "run `make pages-backfill-hostnames`")
        origin = self._origin(system)
        settings_wire = PagesSettingsWire(
            fallback_url=row.fallback_url, page_title=row.page_title, page_description=row.page_description,
            favicon_url=f"{origin}/favicon.ico" if row.favicon_sha256 else None,
            social_preview_url=f"{origin}/asset-store/{row.social_preview_sha256}" if row.social_preview_sha256 else None,
        )
        suffix = "." + self._settings.pages_system_suffix
        return PagesSettingsReadWire(
            settings=settings_wire,
            system_hostname=SystemHostnameWire(hostname=system, label=system.removesuffix(suffix), url=origin),
            custom_hostname=self._custom_wire(custom) if custom is not None else None,
        )

    def _custom_wire(self, row: Any) -> CustomHostnameWire:
        records = [
            DnsRecordWire(type="CNAME", name=row.hostname, required=row.cname_target, observed=row.observed_cname,
                          ok=(row.observed_cname or "").lower() == row.cname_target.lower()),
            DnsRecordWire(type="TXT", name=row.ownership_txt_name, required=row.ownership_txt_value,
                          observed=row.ownership_txt_value if row.observed_txt_present else None,
                          ok=bool(row.observed_txt_present)),
        ]
        return CustomHostnameWire(
            hostname=row.hostname, status=row.status, records=records,
            last_checked_at=row.last_checked_at.isoformat() if row.last_checked_at else None,
            error=HostnameErrorWire(code=row.last_error_code, detail=row.last_error_detail) if row.last_error_code else None,
            url=f"https://{row.hostname}" if row.status == "active" else None,
        )

    # -- settings ------------------------------------------------------------
    async def update_settings(self, workspace_id: str, patch: PagesSettingsPatch) -> PagesSettingsReadWire:
        if isinstance(patch.fallback_url, str) and not patch.fallback_url.startswith("https://"):
            raise _refusal(422, "VALIDATION_ERROR", "fallbackUrl must start with https://")
        async with self._conn_factory() as conn:
            await update_pages_settings(
                conn, workspace_id=workspace_id, fallback_url=patch.fallback_url,
                page_title=patch.page_title, page_description=patch.page_description,
            )
        return await self.read(workspace_id)

    async def store_image(self, workspace_id: str, kind: Literal["favicon", "social_preview"], upload: UploadFile) -> PagesSettingsReadWire:
        if self._storage is None:
            raise _refusal(503, "PAGES_STORAGE_UNAVAILABLE", "Image storage is unavailable.")
        allowed, limit = (FAVICON_TYPES, FAVICON_MAX) if kind == "favicon" else (SOCIAL_TYPES, SOCIAL_MAX)
        media_type = (upload.content_type or "").split(";")[0].strip().lower()
        if media_type not in allowed:
            raise _refusal(415, "UNSUPPORTED_MEDIA_TYPE", f"{media_type or 'unknown'} is not allowed for {kind}")
        data = await upload.read(limit + 1)
        if len(data) > limit:
            raise _refusal(413, "PAYLOAD_TOO_LARGE", f"{kind} must be at most {limit} bytes")
        async with self._conn_factory() as conn:
            await register_design_bytes(conn, self._storage, workspace_id=workspace_id, data=data, media_type=media_type, source_key=f"pages_settings_{kind}")
            digest = content_address(data)
            if kind == "favicon":
                await update_pages_settings(conn, workspace_id=workspace_id, favicon_sha256=digest)
            else:
                await update_pages_settings(conn, workspace_id=workspace_id, social_preview_sha256=digest)
        return await self.read(workspace_id)

    async def change_label(self, workspace_id: str, label: str) -> PagesSettingsReadWire:
        try:
            async with self._conn_factory() as conn:
                await replace_system_label(conn, workspace_id=workspace_id, label=label, suffix=self._settings.pages_system_suffix)
        except HostnameRefused as refused:
            raise _refusal(422 if refused.code != "label_taken" else 409, refused.code, refused.message) from refused
        return await self.read(workspace_id)
```

(`connect`, `check`, `remove` are added in Task 8; leave the class ending here.)

Routes and registration in the same file:

```python
def build_cloudflare_client(settings: Settings, secrets: Secrets | None) -> CloudflareCustomHostnames | None:
    token = secrets.cloudflare_api_token.get_secret_value() if secrets and secrets.cloudflare_api_token else None
    if not token or not settings.cloudflare_zone_id:
        return None
    return CloudflareCustomHostnames(zone_id=settings.cloudflare_zone_id, api_token=token)


def register_settings_pages_routes(
    router: APIRouter, *, conn_factory: ConnFactory, settings: Settings, secrets: Secrets | None,
    storage: StorageBackend | None, allow_local_mutations: bool,
    cloudflare: CloudflareCustomHostnames | None = None, resolver: DnsResolver | None = None,
) -> None:
    service = PagesSettingsService(
        conn_factory, settings=settings, storage=storage,
        cloudflare=cloudflare if cloudflare is not None else build_cloudflare_client(settings, secrets),
        resolver=resolver if resolver is not None else PublicDnsResolver(),
    )

    def _service(request: Request) -> PagesSettingsService:
        # Tests inject fakes (provider, resolver, clock) through app.state; production has nothing
        # there and uses `service`. A test that sets only a clock still gets cloudflare=None.
        state = request.app.state
        if not any(hasattr(state, name) for name in ("pages_cloudflare", "pages_resolver", "pages_clock")):
            return service
        return PagesSettingsService(
            conn_factory, settings=settings, storage=storage,
            cloudflare=getattr(state, "pages_cloudflare", None), resolver=getattr(state, "pages_resolver", None),
            clock=getattr(state, "pages_clock", None) or (lambda: datetime.now(UTC)),
        )

    @router.get("/settings/pages", response_model=PagesSettingsReadWire)
    async def read_pages_settings(request: Request, workspace_id: WorkspaceDep) -> PagesSettingsReadWire:
        return await _service(request).read(workspace_id)  # Task 8 switches this to read_with_refresh

    @router.patch("/settings/pages", response_model=PagesSettingsReadWire)
    async def patch_pages_settings(request: Request, workspace_id: WorkspaceDep, body: PagesSettingsPatch) -> PagesSettingsReadWire:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        return await _service(request).update_settings(workspace_id, body)

    @router.post("/settings/pages/favicon", response_model=PagesSettingsReadWire)
    async def upload_favicon(request: Request, workspace_id: WorkspaceDep, file: Annotated[UploadFile, File()]) -> PagesSettingsReadWire:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        return await _service(request).store_image(workspace_id, "favicon", file)

    @router.post("/settings/pages/social-preview", response_model=PagesSettingsReadWire)
    async def upload_social_preview(request: Request, workspace_id: WorkspaceDep, file: Annotated[UploadFile, File()]) -> PagesSettingsReadWire:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        return await _service(request).store_image(workspace_id, "social_preview", file)

    @router.patch("/settings/pages/system-hostname", response_model=PagesSettingsReadWire)
    async def patch_system_hostname(request: Request, workspace_id: WorkspaceDep, body: LabelPatch) -> PagesSettingsReadWire:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        return await _service(request).change_label(workspace_id, body.label)
```

In `app.py`,
after `register_artifact_routes(router, conn_factory=conn_factory)`, add:

```python
    # Settings → Pages: page defaults, the Clue address label, the custom hostname (spec 2026-09-17 §7).
    from clue_api.frontend_read.settings_pages import register_settings_pages_routes

    register_settings_pages_routes(
        router, conn_factory=conn_factory, settings=settings, secrets=secrets,
        storage=evidence_storage, allow_local_mutations=allow_local_mutations,
    )
```

The `PagesSettingsPatch` model must accept camelCase keys and treat an absent key as `UNSET` and an
explicit `null` as `None`; pydantic cannot type `Unset` without `arbitrary_types_allowed=True`, which is why its one
`model_config` carries `extra="forbid", arbitrary_types_allowed=True, populate_by_name=True`. The FI-1 envelope turns the `HTTPException` detail dicts into
`{"error": {"code", "message", "requestId"}}` automatically.

- [ ] **Step 3: Run, gates, commit.** Test file → PASS. `uv run ruff format platform/api/clue_api/frontend_read/settings_pages.py platform/api/clue_api/frontend_read/app.py tests/api/test_frontend_read_settings_pages_db.py && uv run ruff check … && uv run mypy && uv run lint-imports`.

```bash
git add platform/api/clue_api/frontend_read/settings_pages.py platform/api/clue_api/frontend_read/app.py tests/api/test_frontend_read_settings_pages_db.py
git commit -m "api: Settings → Pages read, defaults, uploads and label change under workspace.manage_settings"
```

---

### Task 8: Connect, check, remove

**Files:**
- Modify: `platform/api/clue_api/frontend_read/settings_pages.py` (service methods + three routes; `read_with_refresh`)
- Test: `tests/api/test_frontend_read_settings_pages_db.py` (extend)

**Interfaces:**
- `PagesSettingsService.connect(workspace_id, hostname) -> PagesSettingsReadWire`, `.check(workspace_id) -> PagesSettingsReadWire`,
  `.remove(workspace_id) -> None`, `.read_with_refresh(workspace_id)`.
- Routes: `POST /settings/pages/custom-hostname` (201), `POST /settings/pages/custom-hostname/check` (200, membership),
  `DELETE /settings/pages/custom-hostname` (204; 404 when none; 502 `provider_error` + `retryable: true`).

- [ ] **Step 1: Write the failing tests** (append; a `FakeCloudflare` and a `FakeResolver` you control step by step)

```python
class FakeCloudflare:
    def __init__(self) -> None:
        self.records: dict[str, Any] = {}
        self.create_error: CloudflareError | None = None
        self.delete_error: CloudflareError | None = None
        self.calls: list[tuple[str, str]] = []

    async def create(self, hostname: str):  # type: ignore[no-untyped-def]
        self.calls.append(("create", hostname))
        if self.create_error:
            raise self.create_error
        record = CustomHostnameRecord(id=f"cf_{hostname}", status="pending", ssl_status="pending_validation",
                                      ownership_txt_name=f"_cf-custom-hostname.{hostname}", ownership_txt_value="tok-" + hostname,
                                      verification_errors=(), ssl_validation_errors=())
        self.records[record.id] = record
        return record

    async def get(self, custom_hostname_id: str):  # type: ignore[no-untyped-def]
        self.calls.append(("get", custom_hostname_id))
        return self.records.get(custom_hostname_id)

    async def delete(self, custom_hostname_id: str) -> None:
        self.calls.append(("delete", custom_hostname_id))
        if self.delete_error:
            raise self.delete_error
        self.records.pop(custom_hostname_id, None)


class FakeResolver:
    def __init__(self) -> None:
        self.cname: dict[str, str] = {}
        self.txt: dict[str, list[str]] = {}

    def resolve(self, name: str, rdtype: str) -> list[str]:
        if rdtype == "CNAME":
            return [self.cname[name]] if name in self.cname else []
        return list(self.txt.get(name, []))


def test_connect_refusals_in_spec_order(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            other = await _workspace_named(conn, "Other")
            cf, dns = FakeCloudflare(), FakeResolver()
            app = _app(conn, tmp_path, role="admin", cloudflare=cf, resolver=dns)
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                for hostname, code in [("not a host", "hostname_invalid"), ("acme.com", "hostname_is_apex"), ("x.pages.test", "hostname_reserved")]:
                    r = await client.post(f"{BASE}/custom-hostname", json={"hostname": hostname}, headers={"X-Workspace-Id": ws})
                    assert (r.status_code, r.json()["error"]["code"]) == (422, code), r.text
                taken = await client.post(f"{BASE}/custom-hostname", json={"hostname": "go.acme.example"}, headers={"X-Workspace-Id": other})
                assert taken.status_code == 201
                again = await client.post(f"{BASE}/custom-hostname", json={"hostname": "go.acme.example"}, headers={"X-Workspace-Id": ws})
                assert (again.status_code, again.json()["error"]["code"]) == (409, "hostname_taken")
                assert "already connected to a workspace" in again.json()["error"]["message"]
                first = await client.post(f"{BASE}/custom-hostname", json={"hostname": "go.mine.example"}, headers={"X-Workspace-Id": ws})
                assert first.status_code == 201
                second = await client.post(f"{BASE}/custom-hostname", json={"hostname": "go2.mine.example"}, headers={"X-Workspace-Id": ws})
                assert (second.status_code, second.json()["error"]["code"]) == (409, "custom_hostname_exists")
            assert cf.calls.count(("create", "go.mine.example")) == 1

    run_async(scenario())


def test_provider_refusal_leaves_no_row(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            cf, dns = FakeCloudflare(), FakeResolver()
            cf.create_error = CloudflareError("Duplicate custom hostname found.", status=409, retryable=False)
            app = _app(conn, tmp_path, role="admin", cloudflare=cf, resolver=dns)
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                r = await client.post(f"{BASE}/custom-hostname", json={"hostname": "go.dup.example"}, headers={"X-Workspace-Id": ws})
                assert (r.status_code, r.json()["error"]["code"]) == (502, "provider_error")
                assert "Duplicate" in r.json()["error"]["message"]
                read = await client.get(BASE, headers={"X-Workspace-Id": ws})
                assert read.json()["customHostname"] is None

    run_async(scenario())


def test_check_walks_the_ladder_and_read_refreshes(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            cf, dns, clock = FakeCloudflare(), FakeResolver(), TickingClock()
            app = _app(conn, tmp_path, role="admin", cloudflare=cf, resolver=dns, clock=clock)
            headers = {"X-Workspace-Id": ws}
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                created = (await client.post(f"{BASE}/custom-hostname", json={"hostname": "go.walk.example"}, headers=headers)).json()["customHostname"]
                assert created["status"] == "pending_dns"
                assert [r["type"] for r in created["records"]] == ["CNAME", "TXT"]
                assert created["records"][0]["required"] == "pages.test"
                assert created["records"][1]["name"] == "_cf-custom-hostname.go.walk.example"
                dns.cname["go.walk.example"] = "pages.test"
                step1 = (await client.post(f"{BASE}/custom-hostname/check", headers=headers)).json()["customHostname"]
                assert step1["status"] == "verifying_ownership" and step1["records"][0]["ok"] and not step1["records"][1]["ok"]
                dns.txt["_cf-custom-hostname.go.walk.example"] = ["tok-go.walk.example"]
                step2 = (await client.post(f"{BASE}/custom-hostname/check", headers=headers)).json()["customHostname"]
                assert step2["status"] == "issuing_certificate"
                cf.records["cf_go.walk.example"] = CustomHostnameRecord(id="cf_go.walk.example", status="active", ssl_status="active",
                                                                       ownership_txt_name="_cf-custom-hostname.go.walk.example",
                                                                       ownership_txt_value="tok-go.walk.example", verification_errors=(), ssl_validation_errors=())
                step3 = (await client.post(f"{BASE}/custom-hostname/check", headers=headers)).json()["customHostname"]
                assert step3["status"] == "active" and step3["url"] == "https://go.walk.example" and step3["error"] is None
                # rate limit: a second check inside 5 s returns the stored state without touching the provider
                clock.frozen = True
                calls_before = len(cf.calls)
                await client.post(f"{BASE}/custom-hostname/check", headers=headers)
                assert len(cf.calls) == calls_before

    run_async(scenario())


def test_remove_is_ordered_and_survives_a_provider_outage(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            cf, dns = FakeCloudflare(), FakeResolver()
            app = _app(conn, tmp_path, role="admin", cloudflare=cf, resolver=dns, clock=TickingClock())
            headers = {"X-Workspace-Id": ws}
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                await client.post(f"{BASE}/custom-hostname", json={"hostname": "go.gone.example"}, headers=headers)
                cf.delete_error = CloudflareError("down", status=503, retryable=True)
                failed = await client.delete(f"{BASE}/custom-hostname", headers=headers)
                assert failed.status_code == 502 and failed.json()["error"]["code"] == "provider_error"
                assert failed.json()["error"]["retryable"] is True
                stuck = (await client.get(BASE, headers=headers)).json()["customHostname"]
                assert stuck["status"] == "disconnecting"
                cf.delete_error = None
                completed = await client.post(f"{BASE}/custom-hostname/check", headers=headers)  # check-now retries the delete
                assert completed.json()["customHostname"] is None
                assert cf.calls[-1] == ("delete", "cf_go.gone.example")
                assert (await client.delete(f"{BASE}/custom-hostname", headers=headers)).status_code == 404
                await client.post(f"{BASE}/custom-hostname", json={"hostname": "go.gone2.example"}, headers=headers)
                assert (await client.delete(f"{BASE}/custom-hostname", headers=headers)).status_code == 204
                assert (await client.get(BASE, headers=headers)).json()["customHostname"] is None

    run_async(scenario())


def test_connect_without_a_configured_provider_is_503(tmp_path: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            ws = await _workspace(conn)
            app = _app(conn, tmp_path, role="admin", cloudflare=None, resolver=FakeResolver())
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                r = await client.post(f"{BASE}/custom-hostname", json={"hostname": "go.nocf.example"}, headers={"X-Workspace-Id": ws})
            assert (r.status_code, r.json()["error"]["code"]) == (503, "PROVIDER_NOT_CONFIGURED")

    run_async(scenario())
```

(`_workspace_named(conn, name)` is `_workspace` with a name parameter; add it. Import
`CloudflareError`, `CustomHostnameRecord` from `clue_api.cloudflare_custom_hostnames`. When only a
resolver fake is given, `_service` must still build a service with `cloudflare=None`.)

- [ ] **Step 2: Add the service methods**

```python
    # -- custom hostname (spec §7.3–7.6) --------------------------------------
    async def connect(self, workspace_id: str, raw_hostname: str) -> PagesSettingsReadWire:
        try:
            hostname = validate_custom_hostname(raw_hostname, system_suffix=self._settings.pages_system_suffix)
        except HostnameRefused as refused:
            raise _refusal(422, refused.code, refused.message) from refused
        if self._cloudflare is None:
            raise _refusal(503, "PROVIDER_NOT_CONFIGURED", "Custom domains are not configured on this deployment.")
        async with self._conn_factory() as conn:
            if await get_custom_hostname(conn, workspace_id) is not None:
                raise _refusal(409, "custom_hostname_exists", "This workspace already has a custom hostname; remove it first.")
            if await hostname_exists(conn, hostname):
                raise _refusal(409, "hostname_taken", "This hostname is already connected to a workspace.")
            try:
                async with conn.begin_nested():
                    await insert_custom_hostname(conn, workspace_id=workspace_id, hostname=hostname, cname_target=self._settings.pages_cname_target)
            except IntegrityError as error:
                raise _refusal(409, "hostname_taken", "This hostname is already connected to a workspace.") from error
        # Committed. Now the provider; a refusal deletes the row again.
        try:
            record = await self._cloudflare.create(hostname)
        except CloudflareError as error:
            async with self._conn_factory() as conn:
                await delete_custom_hostname(conn, hostname=hostname)
            raise _refusal(502, "provider_error", error.message) from error
        async with self._conn_factory() as conn:
            await set_custom_hostname_provider(
                conn, hostname=hostname, cf_custom_hostname_id=record.id,
                ownership_txt_name=record.ownership_txt_name or f"_cf-custom-hostname.{hostname}",
                ownership_txt_value=record.ownership_txt_value or "",
            )
        log.info("pages.custom_hostname.connected", workspace_id=workspace_id, hostname=hostname)
        return await self.read(workspace_id)

    async def _provider_state(self, row: Any) -> ProviderState | None:
        if self._cloudflare is None or not row.cf_custom_hostname_id:
            return None
        record = await self._cloudflare.get(row.cf_custom_hostname_id)
        if record is None:
            return None
        return ProviderState(status=record.status, ssl_status=record.ssl_status,
                             verification_errors=record.verification_errors, ssl_validation_errors=record.ssl_validation_errors)

    async def check(self, workspace_id: str, *, force: bool = True) -> PagesSettingsReadWire:
        now = self._clock()
        async with self._conn_factory() as conn:
            row = await get_custom_hostname(conn, workspace_id)
        if row is None:
            return await self.read(workspace_id)
        if row.last_checked_at is not None and (now - row.last_checked_at).total_seconds() < CHECK_INTERVAL_S:
            return await self.read(workspace_id)
        if row.status == "disconnecting":
            await self._finish_remove(row)
            return await self.read(workspace_id)
        resolver = self._resolver or PublicDnsResolver()
        observation = await asyncio.to_thread(observe_hostname, row.hostname, row.ownership_txt_name, resolver=resolver)
        try:
            provider = await self._provider_state(row)
        except CloudflareError as error:
            provider = ProviderState(status=row.status, ssl_status=None, verification_errors=(error.message,), ssl_validation_errors=())
        decision = derive_status(
            observation=observation, provider=provider, cname_target=row.cname_target,
            expected_txt_value=row.ownership_txt_value, connected_at=row.created_at, now=now,
        )
        async with self._conn_factory() as conn:
            await record_custom_hostname_check(
                conn, hostname=row.hostname, status=decision.status, observed_cname=observation.cname,
                observed_txt_present=row.ownership_txt_value in observation.txt_values,
                last_error_code=decision.error_code, last_error_detail=decision.error_detail, checked_at=now,
            )
        return await self.read(workspace_id)

    async def read_with_refresh(self, workspace_id: str) -> PagesSettingsReadWire:
        """The GET: a cheap refresh when the custom row is non-active and stale (spec §7.1)."""
        async with self._conn_factory() as conn:
            row = await get_custom_hostname(conn, workspace_id)
        if row is not None and row.status != "active":
            return await self.check(workspace_id)
        return await self.read(workspace_id)

    async def _finish_remove(self, row: Any) -> None:
        if self._cloudflare is not None and row.cf_custom_hostname_id:
            try:
                await self._cloudflare.delete(row.cf_custom_hostname_id)
            except CloudflareError as error:
                raise _refusal(502, "provider_error", error.message, extra={"retryable": True}) from error
        async with self._conn_factory() as conn:
            await delete_custom_hostname(conn, hostname=row.hostname)

    async def remove(self, workspace_id: str) -> None:
        async with self._conn_factory() as conn:
            row = await get_custom_hostname(conn, workspace_id)
            if row is None:
                raise _refusal(404, "CUSTOM_HOSTNAME_NOT_FOUND", "No custom hostname is connected.")
            await set_custom_hostname_status(conn, hostname=row.hostname, status="disconnecting")
        await self._finish_remove(row)
        log.info("pages.custom_hostname.removed", workspace_id=workspace_id, hostname=row.hostname)
```

The 502 from `_finish_remove` carries `retryable: true` through `_refusal(..., extra={"retryable": True})`
(the envelope handler copies only `code`/`message`; add `retryable` as a top-level key of the
`error` object by extending `_envelope_parts` in `app.py` to pass through a boolean `retryable`
when present — a two-line change; pin it in the remove test with
`assert failed.json()["error"]["retryable"] is True`).
`check` on a `disconnecting` row lets the 502 propagate (the screen's Check now retries the delete).

Routes (add to `register_settings_pages_routes`; switch the GET to `read_with_refresh`):

```python
    @router.post("/settings/pages/custom-hostname", response_model=PagesSettingsReadWire, status_code=201)
    async def connect_custom_hostname(request: Request, workspace_id: WorkspaceDep, body: ConnectBody) -> PagesSettingsReadWire:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        return await _service(request).connect(workspace_id, body.hostname)

    @router.post("/settings/pages/custom-hostname/check", response_model=PagesSettingsReadWire)
    async def check_custom_hostname(request: Request, workspace_id: WorkspaceDep) -> PagesSettingsReadWire:
        return await _service(request).check(workspace_id)

    @router.delete("/settings/pages/custom-hostname", status_code=204)
    async def remove_custom_hostname(request: Request, workspace_id: WorkspaceDep) -> Response:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        await _service(request).remove(workspace_id)
        return Response(status_code=204)
```

(`from fastapi import Response`.) Because each test's `conn` is one rolled-back connection, "commit
between transactions" is simulated by the session factory; the row-before-provider ORDER is what the
tests pin (the provider refusal deletes the row, and a second connect sees `custom_hostname_exists`).

- [ ] **Step 3: Run, gates, commit.** The whole test file → PASS.

```bash
git add platform/api/clue_api/frontend_read/settings_pages.py tests/api/test_frontend_read_settings_pages_db.py
git commit -m "api: connect, check and remove a customer hostname through Cloudflare for SaaS"
```

---

### Task 9: Design API — publish-time defaults from the settings row

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/design_store.py` (`HybridRepository`: `pages_defaults()` next to `system_hostname()`), `lumen_api/toolbelt/publishes.py` (`publish_web_document`), `lumen_api/web_export.py` (`build_publish_package`, `build_publish_html`)
- Test: `subsystems/clue-design/apps/api/tests/test_public_pages.py` (extend)

**Interfaces:**
- `HybridRepository.pages_defaults() -> dict[str, str | None]` with keys `page_description`, `social_preview_sha256`.
- `build_publish_package(..., public_origin: str, workspace_id: str, default_description: str | None = None, default_social_preview_sha256: str | None = None, ...)`.

- [ ] **Step 1: Write the failing test** (in `tests/test_public_pages.py`)

```python
def test_publish_falls_back_to_workspace_description_and_social_preview(client: TestClient, monkeypatch) -> None:
    from clue_spine.pages_settings import update_pages_settings
    from clue_storage import content_address
    from conftest import make_blob_store, published_html

    monkeypatch.setenv("CLUE_PAGES_SYSTEM_SUFFIX", "pages.test")
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_SCHEME", "https")
    monkeypatch.delenv("CLUE_PAGES_PUBLIC_PORT", raising=False)
    document = seed_document(client)  # SAMPLE_HTML has no image node and its description is derived from text
    repo = HybridRepository()
    preview = b"\x89PNG-social-preview"
    make_blob_store(client.app).register(preview, media_type="image/png", source_key="test")
    repo._bridge._run(lambda conn: update_pages_settings(conn, workspace_id=repo.workspace_id,
                                                         page_description="From workspace settings",
                                                         social_preview_sha256=content_address(preview)))
    client.post(f"/documents/{document['id']}/web/publish", json={"slug": "defaults"})
    html = published_html(repo.workspace_id, "defaults")
    assert f'property="og:image" content="https://{repo.system_hostname()}/asset-store/{content_address(preview)}"' in html
    # the page's own derived description wins when non-empty; assert the workspace one appears only if the page had none
    assert 'name="description"' in html
```

Add a second assertion path: seed a document whose text yields an empty derived description (look at
how `_seo_description` derives it; an empty web doc with only an image-less hero) and assert
`content="From workspace settings"`. If no such fixture is cheap, assert via a direct
`build_publish_package(..., default_description="From workspace settings")` call on a document with
an empty body that the meta carries it.

- [ ] **Step 2: Implement.** `design_store.py`:

```python
    def pages_defaults(self) -> dict[str, str | None]:
        """Workspace page defaults applied at publish time (custom-domain publishing §4.2)."""
        async def _read(conn: AsyncConnection) -> dict[str, str | None]:
            row = await get_pages_settings(conn, self.workspace_id)
            return {"page_description": row.page_description, "social_preview_sha256": row.social_preview_sha256}
        return self._bridge._run(_read)
```

(`from clue_spine.pages_settings import get_pages_settings`.) `toolbelt/publishes.py::publish_web_document`:
`defaults = repository.pages_defaults()` and pass `default_description=defaults["page_description"], default_social_preview_sha256=defaults["social_preview_sha256"]`.
`web_export.build_publish_package`: add the two keyword parameters; `description = _seo_description(web_doc, document["title"]) or (default_description or "")`;
`og_image`: keep the image-node branch, then `elif default_social_preview_sha256: og_image = f"{origin}/asset-store/{default_social_preview_sha256}"`.
Thread the same two parameters through `build_publish_html`.

- [ ] **Step 3: Run, commit.** From the API dir: `tests/test_public_pages.py`, `tests/test_web_export.py -k host_independent` → PASS.

```bash
git add subsystems/clue-design/apps/api
git commit -m "design-api: workspace description and social-preview defaults at publish time"
```

---

### Task 10: Frontend model, repository and actions for Pages

**Files:**
- Create: `apps/frontend/src/features/settings/model/pages.ts`, `model/pages.test.ts`, `data/pages.repository.ts`, `data/pages.actions.ts`

**Interfaces:**
- `model/pages.ts`: Zod `PagesSettingsReadSchema` (spec §7.2, camelCase), types `PagesSettingsRead`, `CustomHostnameState`, `HostnameStatus`; `connectionView(custom: CustomHostname | null): "not_connected" | "connecting" | "active" | "error"`; `STATUS_STEPS = ["pending_dns", "verifying_ownership", "issuing_certificate", "active"] as const`; `stepIndex(status): number`; `REFUSAL_MESSAGES: Record<string, string>` for the §7.3 codes.
- `data/pages.repository.ts`: `getPagesSettings(read = fetchRead): Promise<PagesSettingsRead>` (no fixture mode; throws `ClueApiError`).
- `data/pages.actions.ts` (browser): `updatePagesSettings(patch)`, `uploadPagesImage(kind: "favicon" | "social-preview", file: File)`, `changeSystemLabel(label)`, `connectCustomHostname(hostname)`, `checkCustomHostname()`, `removeCustomHostname()` — each returns `PagesSettingsRead` (remove returns `void`).

- [ ] **Step 1: Write the failing model test**

```ts
// apps/frontend/src/features/settings/model/pages.test.ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { PagesSettingsReadSchema, connectionView, stepIndex } from "./pages";

const base = {
  settings: { fallbackUrl: null, pageTitle: null, pageDescription: null, faviconUrl: null, socialPreviewUrl: null },
  systemHostname: { hostname: "acme.pages.cluehq.ai", label: "acme", url: "https://acme.pages.cluehq.ai" },
  customHostname: null,
};

test("the read shape parses and a missing custom hostname is not connected", () => {
  const parsed = PagesSettingsReadSchema.parse(base);
  assert.equal(connectionView(parsed.customHostname), "not_connected");
});

test("connecting, active and error views follow the status", () => {
  const records = [
    { type: "CNAME", name: "go.acme.com", required: "pages.cluehq.ai", observed: null, ok: false },
    { type: "TXT", name: "_cf-custom-hostname.go.acme.com", required: "tok", observed: null, ok: false },
  ];
  const connecting = PagesSettingsReadSchema.parse({ ...base, customHostname: { hostname: "go.acme.com", status: "verifying_ownership", records, lastCheckedAt: null, error: null, url: null } });
  assert.equal(connectionView(connecting.customHostname), "connecting");
  assert.equal(stepIndex("verifying_ownership"), 1);
  const active = PagesSettingsReadSchema.parse({ ...base, customHostname: { hostname: "go.acme.com", status: "active", records, lastCheckedAt: "2026-09-17T12:00:00Z", error: null, url: "https://go.acme.com" } });
  assert.equal(connectionView(active.customHostname), "active");
  const errored = PagesSettingsReadSchema.parse({ ...base, customHostname: { hostname: "go.acme.com", status: "error", records, lastCheckedAt: null, error: { code: "caa_blocked", detail: "CAA" }, url: null } });
  assert.equal(connectionView(errored.customHostname), "error");
  assert.equal(stepIndex("error"), -1);
});
```

Run `cd apps/frontend && npm test` → fails on the missing module.

- [ ] **Step 2: Write the model**

```ts
// apps/frontend/src/features/settings/model/pages.ts
import { z } from "zod";

export const HostnameStatusSchema = z.enum(["pending_dns", "verifying_ownership", "issuing_certificate", "active", "error", "disconnecting"]);
export type HostnameStatus = z.infer<typeof HostnameStatusSchema>;

export const DnsRecordSchema = z.object({
  type: z.enum(["CNAME", "TXT"]), name: z.string(), required: z.string(), observed: z.string().nullable(), ok: z.boolean(),
});
export const CustomHostnameSchema = z.object({
  hostname: z.string(), status: HostnameStatusSchema, records: z.array(DnsRecordSchema),
  lastCheckedAt: z.string().nullable(), error: z.object({ code: z.string(), detail: z.string().nullable() }).nullable(),
  url: z.string().nullable(),
});
export const PagesSettingsReadSchema = z.object({
  settings: z.object({
    fallbackUrl: z.string().nullable(), pageTitle: z.string().nullable(), pageDescription: z.string().nullable(),
    faviconUrl: z.string().nullable(), socialPreviewUrl: z.string().nullable(),
  }),
  systemHostname: z.object({ hostname: z.string(), label: z.string(), url: z.string() }),
  customHostname: CustomHostnameSchema.nullable(),
});
export type PagesSettingsRead = z.infer<typeof PagesSettingsReadSchema>;
export type CustomHostname = z.infer<typeof CustomHostnameSchema>;

export const STATUS_STEPS = ["pending_dns", "verifying_ownership", "issuing_certificate", "active"] as const;
export function stepIndex(status: HostnameStatus): number {
  return STATUS_STEPS.indexOf(status as (typeof STATUS_STEPS)[number]);
}
export type ConnectionView = "not_connected" | "connecting" | "active" | "error";
export function connectionView(custom: CustomHostname | null): ConnectionView {
  if (!custom) return "not_connected";
  if (custom.status === "active") return "active";
  if (custom.status === "error") return "error";
  return "connecting";
}
/** Copy for the §7.3 refusal codes, rendered inline under the hostname input. */
export const REFUSAL_MESSAGES: Record<string, string> = {
  hostname_invalid: "That is not a valid hostname.",
  hostname_is_apex: "Use a dedicated subdomain such as go.acme.com — a bare domain cannot be connected.",
  hostname_reserved: "Hostnames under cluehq.ai cannot be connected.",
  custom_hostname_exists: "This workspace already has a custom domain. Remove it first.",
  hostname_taken: "This hostname is already connected to a workspace.",
  provider_error: "The hosting provider refused this hostname. Try again or contact support.",
  PROVIDER_NOT_CONFIGURED: "Custom domains are not configured on this deployment.",
};
```

- [ ] **Step 3: Repository and actions**

```ts
// apps/frontend/src/features/settings/data/pages.repository.ts
import { fetchRead } from "@/features/accounts/data/frontend-api";
import { PagesSettingsReadSchema, type PagesSettingsRead } from "../model/pages";

export async function getPagesSettings(read: typeof fetchRead = fetchRead): Promise<PagesSettingsRead> {
  return PagesSettingsReadSchema.parse(await read("/settings/pages"));
}
```

```ts
// apps/frontend/src/features/settings/data/pages.actions.ts
import { fetchMutation } from "@/features/accounts/data/frontend-mutation";
import { ClueApiError } from "@/features/accounts/data/clue-api-error";
import { PagesSettingsReadSchema, type PagesSettingsRead } from "../model/pages";

const BFF_PREFIX = "/api/clue/frontend/v1";

export interface PagesSettingsPatch { fallbackUrl?: string | null; pageTitle?: string | null; pageDescription?: string | null }

export async function updatePagesSettings(patch: PagesSettingsPatch): Promise<PagesSettingsRead> {
  return PagesSettingsReadSchema.parse(await fetchMutation("/settings/pages", { method: "PATCH", body: JSON.stringify(patch) }));
}
export async function changeSystemLabel(label: string): Promise<PagesSettingsRead> {
  return PagesSettingsReadSchema.parse(await fetchMutation("/settings/pages/system-hostname", { method: "PATCH", body: JSON.stringify({ label }) }));
}
export async function connectCustomHostname(hostname: string): Promise<PagesSettingsRead> {
  return PagesSettingsReadSchema.parse(await fetchMutation("/settings/pages/custom-hostname", { method: "POST", body: JSON.stringify({ hostname }) }));
}
export async function checkCustomHostname(): Promise<PagesSettingsRead> {
  return PagesSettingsReadSchema.parse(await fetchMutation("/settings/pages/custom-hostname/check", { method: "POST" }));
}
export async function removeCustomHostname(): Promise<void> {
  await fetchMutation("/settings/pages/custom-hostname", { method: "DELETE" });
}
/** Multipart upload: the browser sets the multipart boundary itself, so this bypasses
 * `fetchMutation`'s JSON content-type default and calls the BFF directly. */
export async function uploadPagesImage(kind: "favicon" | "social-preview", file: File): Promise<PagesSettingsRead> {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await fetch(`${BFF_PREFIX}/settings/pages/${kind}`, { method: "POST", body: form, headers: { Accept: "application/json" } });
  if (!response.ok) {
    let envelope: { code?: string; message?: string; requestId?: string | null } = {};
    try { envelope = (await response.json()).error ?? {}; } catch { /* not an envelope */ }
    throw new ClueApiError(envelope.message ?? `Upload failed (${response.status})`, { code: envelope.code ?? "HTTP_ERROR", requestId: envelope.requestId ?? null, status: response.status });
  }
  return PagesSettingsReadSchema.parse(await response.json());
}
```

`fetchMutation` returns `response.json()`, which throws on a 204 body — for `removeCustomHostname`
guard: if `fetchMutation` cannot handle an empty body, add a `parseBody: false` option to it (a
one-line change in `features/accounts/data/frontend-mutation.ts` returning `null` when
`response.status === 204`) and use it; do not duplicate the mutation helper.

- [ ] **Step 4: Run + commit.** `npm test && npm run lint` → clean.

```bash
git add apps/frontend/src/features/settings apps/frontend/src/features/accounts/data/frontend-mutation.ts
git commit -m "frontend: Pages settings model, repository and actions on the frontend/v1 seam"
```

---

### Task 11: Frontend — lift the settings shell, bind the Pages section

> **Gate (spec §12):** this task starts only when the co-founder's frames for the four connection-card
> states and the "Your Clue address" row exist in the Figma `Clue` file, OR the founder waives them in
> writing for this lane (in which case the card is built from spec §8.2's description with the lifted
> `settings-primitives` and flagged for the redraw). The controller records which in the ledger.

**Files:**
- Create (lifted verbatim from `/Users/aryankeshri/conductor/workspaces/clue-frontend/port-of-spain/src/features/settings/`): `components/{settings-screen,settings-sidebar,settings-nav-icon,settings-primitives,settings-coming-soon,connections-settings,profile-settings,workspace-settings,members-settings,data-model-settings,billing-settings}.tsx`, `components/settings.module.css`, `config/settings-navigation.ts`, `model/settings.ts`, `data/settings.fixture.ts`, `data/settings.repository.ts` (fixture-only: delete the HTTP branch — the non-Pages sections are dummies by ruling until the settings slice merges).
- Create: `src/app/(protected)/settings/[[...section]]/page.tsx`, `error.tsx`, `loading.tsx`; `src/components/ui/confirmation-card.tsx`; `components/settings-autosave-input.tsx`; `components/custom-domain-card.tsx`; `hooks/use-pages-settings.ts`
- Rewrite: `components/pages-settings.tsx`

- [ ] **Step 1: Lift.** `cp` the files listed above from the dummy. In `settings-screen.tsx`, change only the
  `case "pages":` branch to `return <PagesSettings initial={pages} canManage={canManage} />;` and add
  `pages: PagesSettingsRead; canManage: boolean` to the screen's props (the dummy fixture's `workspace.pages`
  is no longer used by the Pages branch; leave the fixture's other sections untouched). Delete the HTTP
  branch in `settings.repository.ts` and rename `getSettingsWorkspace` → `getSettingsFixture` with a
  docblock: "placeholder data for the sections the settings-integration slice binds; never a fallback".

- [ ] **Step 2: Route**

```tsx
// src/app/(protected)/settings/[[...section]]/page.tsx
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { SettingsScreen } from "@/features/settings/components/settings-screen";
import { getPagesSettings } from "@/features/settings/data/pages.repository";
import { getSettingsFixture } from "@/features/settings/data/settings.repository";
import { SettingsRouteSchema } from "@/features/settings/model/settings";
import { getProtectedSession } from "@/features/session/data/session-dal";

export const metadata: Metadata = { title: "Settings" };
export const dynamic = "force-dynamic";

export default async function SettingsPage({ params }: { params: Promise<{ section?: string[] }> }) {
  const route = SettingsRouteSchema.safeParse((await params).section ?? []);
  if (!route.success) notFound();
  const [session, workspace] = await Promise.all([getProtectedSession(), getSettingsFixture()]);
  const canManage = session?.principal.permissions.includes("workspace.manage_settings") ?? false;
  const pages = route.data.section === "pages" ? await getPagesSettings() : null;
  return <SettingsScreen route={route.data} workspace={workspace} pages={pages} canManage={canManage} />;
}
```

`error.tsx` / `loading.tsx` mirror `(protected)/artifacts/` (title "Settings couldn't be loaded", no
`ApplicationShell` — the dummy's settings screen owns its own sidebar). `pages` is `null` for other
sections; `SettingsScreen`'s Pages branch requires it non-null (narrow before rendering).

- [ ] **Step 3: Confirmation card + autosave input** (settings spec §6.3–6.4; founder-authorised UI)

```tsx
// src/components/ui/confirmation-card.tsx
"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Check, X } from "lucide-react";

interface Confirmation { id: number; text: string; tone: "ok" | "error" }
const ConfirmationContext = createContext<(text: string, tone?: "ok" | "error") => void>(() => {});
export function useConfirmation() { return useContext(ConfirmationContext); }

export function ConfirmationCardProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<Confirmation | null>(null);
  const show = useCallback((text: string, tone: "ok" | "error" = "ok") => setCurrent({ id: Date.now(), text, tone }), []);
  useEffect(() => {
    if (!current) return;
    const timer = setTimeout(() => setCurrent(null), 4000);
    return () => clearTimeout(timer);
  }, [current]);
  const value = useMemo(() => show, [show]);
  return (
    <ConfirmationContext.Provider value={value}>
      {children}
      {current ? (
        <div role="status" className="fixed bottom-4 right-4 flex items-center gap-2 rounded-[var(--clue-ds-radius-md)] border-[0.5px] border-[var(--clue-ds-color-border-subtle)] bg-[var(--clue-ds-color-surface-inverse)] px-3 py-2 text-[var(--clue-ds-color-text-inverse)] shadow">
          <Check size={14} aria-hidden="true" className={current.tone === "ok" ? "text-[var(--clue-ds-color-success)]" : "text-[var(--clue-ds-color-danger)]"} />
          <span>{current.text}</span>
          <button aria-label="Dismiss" onClick={() => setCurrent(null)} type="button"><X size={14} /></button>
        </div>
      ) : null}
    </ConfirmationContext.Provider>
  );
}
```

Use the exact token names that exist in `packages/design-system/generated/tokens.css` (grep for
`surface-inverse`, `text-inverse`, `success`, `danger`; substitute the closest existing token when a
name differs, and say so in the report). Mount `<ConfirmationCardProvider>` once in the settings
route's page around `SettingsScreen` (not the protected layout — the settings slice mounts it globally
at merge).

```tsx
// features/settings/components/settings-autosave-input.tsx
"use client";
import { useState } from "react";
import styles from "./settings.module.css";

export function SettingsAutosaveInput({ ariaLabel, value, onSave, readOnly = false, multiline = false, placeholder }: {
  ariaLabel: string; value: string; onSave: (next: string | null) => Promise<void>; readOnly?: boolean; multiline?: boolean; placeholder?: string;
}) {
  const [draft, setDraft] = useState(value);
  const [saved, setSaved] = useState(value);
  const [saving, setSaving] = useState(false);
  const commit = async () => {
    const next = draft.trim();
    if (next === saved.trim()) return;
    setSaving(true);
    try { await onSave(next === "" ? null : next); setSaved(next); }
    catch { setDraft(saved); }
    finally { setSaving(false); }
  };
  const common = {
    "aria-label": ariaLabel, value: draft, readOnly: readOnly || saving, placeholder,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft(e.target.value),
    onBlur: () => void commit(),
    onKeyDown: (e: React.KeyboardEvent) => { if (e.key === "Escape") setDraft(saved); if (e.key === "Enter" && !multiline) void commit(); },
  };
  return multiline ? <textarea className={styles.textarea} rows={3} {...common} /> : <input className={styles.input} {...common} />;
}
```

- [ ] **Step 4: Pages section + custom-domain card**

`hooks/use-pages-settings.ts`: holds `PagesSettingsRead` state seeded from `initial`; exposes
`save(patch)`, `upload(kind, file)`, `changeLabel(label)`, `connect(hostname)`, `check()`, `remove()`,
each calling the Task 10 action, replacing state with the response, and calling `useConfirmation()`
with "Pages updated" / the `ClueApiError.message` on failure; `refusal` state for the connect input
(`REFUSAL_MESSAGES[error.code] ?? error.message`). Polling: while `connectionView(state.customHostname) === "connecting"`
and the card is mounted, `setInterval(() => check(), 5000)` (spec §8.2 state 2), cleared on unmount
or when the view changes.

`components/custom-domain-card.tsx` renders the four states of spec §8.2 with the lifted primitives:
1. not connected — `SettingsInput`-styled input (`aria-label="Custom domain"`), helper text
   "Use a dedicated subdomain such as go.acme.com", a Connect button (`@/components/ui/button`),
   the refusal line under the input.
2. connecting — a table (Type / Name / Required value / Observed value / ✓) from `records`; a
   four-step stepper from `STATUS_STEPS` with `stepIndex(status)` marking the current step; a
   "Check now" button; the note "DNS changes can take up to 48 hours".
3. active — hostname with a green dot (`styles.statusDot`, add the class to the lifted CSS), "Open"
   (link to `url`) and "Remove" (two-step: first click shows "Remove go.acme.com? Your Clue address
   keeps working." with Confirm / Cancel).
4. error — state 2 plus the error line (`error.code` mapped through a small `ERROR_LINES` table:
   `cname_incorrect` → "Your CNAME points somewhere else.", `txt_missing` → "The ownership TXT record
   hasn't appeared.", `caa_blocked` → "A CAA record blocks certificate issuance.", `hostname_taken`,
   `verification_expired`, `provider_error` → the detail text).
   When `!canManage`: no input/Connect/Remove/Check-now; the table and stepper still render.

`components/pages-settings.tsx` (rewrite): the trimmed field set — "Your Clue address" row
(`systemHostname.hostname` read-only text + an Edit affordance that swaps to a label input with
Save/Cancel; on Save `changeLabel`; the row's helper says "Changing it makes existing links stop
working"), the custom-domain card, Fallback URL (`SettingsAutosaveInput`, `pageTitle`, `pageDescription`
likewise), Favicon (`uploadSquare` button opening a hidden `<input type="file" accept="image/png,image/x-icon,image/svg+xml">`;
shows the current favicon `<img>` when `faviconUrl`), Social preview (`uploadPreview` button, accept
`image/png,image/jpeg`; shows the image when set). The "Search engine settings", "Additional code
snippets" and "AI crawler discovery" sections are removed (spec §8.2 dropped/deferred).

- [ ] **Step 5: Gates.** `npm test && npm run lint` clean; `npm run design-system:build && npm run build` when
  port 3020 is free. Manual walk on the dev stack (founder-triggered or with a stack you are allowed to
  start): `/settings/pages` renders the Clue address, autosave works, favicon upload shows at
  `http://<label>.pages.localhost:8040/favicon.ico`, the connect card refuses `acme.com` inline.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src
git commit -m "frontend: Settings → Pages on the lifted settings shell — defaults, Clue address, custom domain card"
```

---

### Task 12: Contract doc, memory note, spec status

**Files:**
- Create: `apps/frontend/docs/api-contracts/settings.md` (Pages section only: the eight routes, the §7.2 read shape, refusal codes and HTTP statuses, the multipart uploads, "reconciled 2026-09-17: per-section `/frontend/v1/settings/*` over `fetchRead` + BFF mutations; the dummy's `GET /api/v1/settings` blob is superseded for Pages")
- Create: `_memory/2026-09-17-custom-domain-publishing-s2.md` (what landed per task with commits, the seven decisions above, tests run with counts, owed items: live Cloudflare walk §10 with a founder-owned hostname, the frames status, `npm run build`, the settings-slice merge reconciliation list — which lifted files are byte-identical and which S2 changed); pointer line in `_memory/README.md`
- Modify: the spec's status header (`**Implementation:**` line: append "S2 landed on `<branch>` (commits …); live acceptance owed")

- [ ] **Step 1: Write the three documents; verify every path cited exists (`ls`).**
- [ ] **Step 2: Commit**

```bash
git add apps/frontend/docs/api-contracts/settings.md _memory/2026-09-17-custom-domain-publishing-s2.md _memory/README.md docs/superpowers/specs/archive/2026-09-17-custom-domain-publishing-design.md
git commit -m "docs: Pages settings contract, custom-domain S2 session record"
```

---

## S2 exit gate (spec §10, §11)

1. `( set -a; source .env; set +a; uv run pytest tests/test_pages_settings.py tests/clue_spine tests/auth tests/api/test_cloudflare_custom_hostnames.py tests/api/test_dns_observe.py tests/api/test_pages_hostname_status.py tests/api/test_frontend_read_settings_pages_db.py tests/page_origin -q -p no:warnings --ignore-glob='*_live.py' )` — green.
2. Design API: `tests/test_public_pages.py`, `tests/test_web_export.py` — green.
3. `uv run ruff format --check <slice files> && uv run ruff check <slice files> && uv run mypy && uv run lint-imports` — clean (mypy baseline 4, contracts 28 kept).
4. `cd apps/frontend && npm test && npm run lint && npm run build` (stack stopped) — green.
5. Dev-stack walk: Settings → Pages autosave, favicon served by the origin, label change updates the share menu's host, connect refuses an apex inline, a fake-free connect against a real zone is NOT run here.
6. **Live acceptance (founder-triggered, recorded in `_memory/`):** one founder-owned hostname walks the whole ladder to active through the screen, the page renders on it, removal returns it to 404 within a minute while the system hostname keeps serving.
