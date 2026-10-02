# FI — Comprehensive account/contact research: slice-by-slice implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the founder-ratified scope contract `docs/FI-comprehensive-account-contact-research-contract.md` — comprehensive 21-field account research, live task progress, Sumble committee discovery with agent-derived role inference, reachable exact-set contact research, 15-field contact execution with correct Sumble/Exa routing, real channel lookup, and C7/handoff serving — in seven independently verifiable slices A–G.

**Architecture:** No new subsystems. Every slice is contract expansion, decoupling, wiring correction, or projection exposure over machinery that already exists: the M8D entity-research fleet, the claim store, the Exa Deep bundler, the Sumble account/committee/people adapters, the `research_tasks` projection, and the FI-2 trusted-turn launch pattern. Nothing here builds a source waterfall, an adaptive gap planner, a committee fallback, a coverage UI, or a confidence gate — those are §10 deferrals.

**Tech stack:** Python (uv workspace: `clue_config`, `clue_core`, `clue_research`, `clue_api`, `clue_projections`, `clue_fleet`, `clue_agents`), PostgreSQL + Alembic (hash revision ids, single head), Next.js frontend at `apps/frontend` (Zod + repository seam), pytest with `_env_file=None` settings construction.

**Spec:** `docs/FI-comprehensive-account-contact-research-contract.md` (the ratified contract; §13 annotation ledger governs every interpretation below). The audit evidence trail is the 2026-08-18 conversation transcript; where the audit and the contract conflict, the contract wins.

## Global constraints

Copied from the contract; every task inherits these.

- **Providers:** only Exa Websets (reuse), Exa Deep, Sumble Organizations / Jobs / Tech Stack / Teams+People. No Firecrawl, Scrapling, registries, CRM, Apollo, ZoomInfo, BuiltWith (§2.2).
- **No new waterfall, no adaptive gap planner** — fixed profile expansion + static provider ownership only (§3.2, annotations 2–3).
- **No committee-provider fallback** — a Sumble miss is an honest miss (§5.1, annotation 9).
- **No provider-coverage / unsearched-channel UI, no confidence-blocking UX, no standalone role classifier, no separate approval tool, no plausibility gate, no secondary decision** (§5.2, §10, annotations 10, 12, 13).
- **STRICT VISUAL PARITY WITH THE DUMMY FRONTEND — first-priority frontend rule (founder, 2026-08-18).** The dummy frontend at `/Users/aryankeshri/conductor/repos/clue-frontend/` is the sole presentation truth, strongest on the **contact research details, buying-committee details, and contact details pages**. The backend must serve *every* field it researches through the API; the frontend propagates **only** the fields the designed components already display — if the backend serves ten fields and the design shows two, wire exactly those two. **No new components, no new visualization elements, no new displayed fields, and no source/date captions under newly connected fields.** Any proposed visual addition — even one field — is asked of the founder *before* it is added. Slices C, D, F, and G each carry a side-by-side parity comparison against the dummy frontend as part of their exit gate.
- **LinkedIn must never be a hard eligibility prerequisite** (§6.3, annotation 15).
- **Budget prompts and verification gates stay disabled in this acceptance environment and their absence must not disable anything** (§9).
- **Honest-empty over fabricated** — a supported provider returning nothing is a correct empty field (§3.1); observed channel values are never promoted to verified (§8).
- **No false human provenance** — agent-derived role writes stay identified as agent-derived (§5.2).
- **Flags resolve on through checked-in configuration, never undocumented terminal state; missing credentials fail visibly. Credentials never enter the repo or memory** (§9).
- **Migrations:** `alembic revision -m "<slug>"` (hash ids), one head always, hand-written reversible up/down, `make db-smoke` on a clean throwaway DB.
- **Verification per slice:** backend `make check` (ruff, mypy, lint-imports, pytest), `make db-smoke` when a migration lands, frontend `npm run design-system:build && npm run lint && npm run build` when `apps/frontend` changes. Each slice ends with founder manual browser testing before the next slice is treated as accepted (§11).
- **Git:** feature-branch commits at every green checkpoint; never push; no AI attribution in commit messages.
- **Immutable resources:** agent profiles/skills/prompts are versioned folders — never edit an existing version; add v(N+1) and promote.

## Slice sequencing and parallelism

```
A (activation + contract freeze)
├─→ B (comprehensive account execution)      — worktree-parallel with C, D
├─→ C (live account progress)                — worktree-parallel with B, D
└─→ D (committee + agent role inference)     — worktree-parallel with B, C
        └─→ E (contact launch reachability)  — needs D for the account-tagged journey
                └─→ F (contact execution + channels + contact progress) — needs C's projection surface
                        └─→ G (C7 reads, handoff, paid acceptance)      — needs everything
```

B, C, D touch disjoint file sets (launch/provider-wiring vs projections/frontend vs committee worker/agent catalog) and can run in parallel worktrees after A merges. E–G are sequential.

Current branch: `platform/comprehensive-account-contact-research`. Each slice may be its own child branch merged back here after founder acceptance.

---

# Slice A — capability and contract activation

Contract §11-A: make the required product-path flags resolve on; fail visibly for missing provider configuration; freeze the fixed 21-field and 15-field request contracts in tests; keep excluded providers absent from composition.

**Design decision recorded here (needs no new machinery elsewhere):** there is no profile/preset mechanism in `clue_config` today — one flat `Settings(BaseSettings)` (`libs/clue-config/clue_config/settings.py:79`, `env_prefix="CLUE_"`, `frozen=True`) with per-flag env overrides, and the audit proved the browser runs relied on undocumented local `.env` state. We introduce a first-class **product path** field: `CLUE_PRODUCT_PATH=integration_pilot` applies a checked-in overlay of defaults; an explicit env var for any individual flag still wins. This satisfies "checked-in configuration/defaults appropriate to the integration product path" without flipping the conservative global defaults that ~10 existing tests freeze (`tests/test_config_settings.py:44-77`, `tests/integration/test_r11_lane_f_acceptance.py:673`, `tests/api/test_pilot_budget_controls.py:142` — all stay green).

**Phased overlay, stated openly (founder attention flag):** three §9 rows are *not* turned on in Slice A because turning them on today makes composition raise before their owning slice lands: `contact_channel_enrichment_enabled` raises at `platform/api/clue_api/entity_research_provider_wiring.py:546-548` ("channel enrichment enabled without validator coordinator") until Slice F binds the channel path; the C7 flags raise at `platform/api/clue_api/projections_app.py:936-948` until Slice G composes their readers. The overlay map is therefore extended by F (channels + email lookup) and G (C7 read/compose/handoff). Every other §9 row activates here.

### Task A1: `product_path` overlay in `Settings`

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (class `Settings`, after line ~110)
- Test: `tests/test_config_settings.py` (append)

**Interfaces:**
- Produces: `Settings.product_path: Literal["default", "integration_pilot"]` (env `CLUE_PRODUCT_PATH`, default `"default"`); module constant `INTEGRATION_PILOT_OVERLAY: dict[str, bool]`.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config_settings.py  (append)

def test_default_product_path_changes_no_default() -> None:
    """CLUE_PRODUCT_PATH is default:'default' and the conservative defaults are untouched."""
    s = load_settings(_env_file=None)  # type: ignore[call-arg]
    assert s.product_path == "default"
    assert s.exa_account_deep_acquisition_enabled is False
    assert s.sumble_committee_acquisition_enabled is False


def test_integration_pilot_overlay_resolves_the_required_capability_state() -> None:
    """Contract §9: the integration product path resolves acquisition, research, committee,
    contact-deep, runtime, chat, and frontend-read to ON, and verification/budget to OFF —
    from checked-in defaults, not terminal state."""
    s = load_settings(_env_file=None, product_path="integration_pilot")  # type: ignore[call-arg]
    assert s.exa_websets_lifecycle_enabled is True
    assert s.exa_websets_acquisition_enabled is True
    assert s.exa_account_deep_acquisition_enabled is True
    assert s.sumble_account_gap_enrichment_enabled is True
    assert s.sumble_committee_acquisition_enabled is True
    assert s.exa_contact_deep_acquisition_enabled is True
    assert s.entity_research_runtime_enabled is True
    assert s.chat_enabled is True
    assert s.frontend_read_enabled is True
    assert s.verification_enabled is False
    assert s.budget_controls_enabled is False
    # Slice F/G extend the overlay; asserting the current phase honestly:
    assert s.contact_channel_enrichment_enabled is False
    assert s.frontend_contact_email_lookup_enabled is False
    assert s.c7_research_view_read_enabled is False


def test_explicit_env_value_beats_the_overlay() -> None:
    s = load_settings(  # type: ignore[call-arg]
        _env_file=None, product_path="integration_pilot", exa_account_deep_acquisition_enabled=False
    )
    assert s.exa_account_deep_acquisition_enabled is False
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_config_settings.py -k product_path -x` → FAIL (`product_path` not defined).

- [ ] **Step 3: Implement the overlay**

```python
# libs/clue-config/clue_config/settings.py — inside Settings, near the deployment flags

    # The integration/pilot product path (docs/FI-comprehensive-account-contact-research-contract.md §9).
    # "integration_pilot" applies INTEGRATION_PILOT_OVERLAY as *defaults*: any flag explicitly
    # provided (env var or kwarg) still wins. This is the checked-in activation record; individual
    # deployments keep the conservative "default" path.
    product_path: Literal["default", "integration_pilot"] = "default"

# module level (above the class):
INTEGRATION_PILOT_OVERLAY: dict[str, bool] = {
    "exa_websets_lifecycle_enabled": True,
    "exa_websets_acquisition_enabled": True,
    "exa_account_deep_acquisition_enabled": True,
    "sumble_account_gap_enrichment_enabled": True,
    "sumble_committee_acquisition_enabled": True,
    "exa_contact_deep_acquisition_enabled": True,
    "entity_research_runtime_enabled": True,
    "chat_enabled": True,
    "frontend_read_enabled": True,
    "verification_enabled": False,
    "budget_controls_enabled": False,
    # Slice F adds: contact_channel_enrichment_enabled, frontend_contact_email_lookup_enabled.
    # Slice G adds: c7_research_view_read_enabled, c7_snapshot_compose_enabled,
    #               c7_production_handoff_enabled.
}

# inside Settings:
    @model_validator(mode="before")
    @classmethod
    def _apply_product_path_overlay(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("product_path") == "integration_pilot":
            for field, value in INTEGRATION_PILOT_OVERLAY.items():
                data.setdefault(field, value)
        return data
```

Note: `mode="before"` sees the merged source dict (env + kwargs), so `setdefault` preserves explicit values — that is what Step 1's third test proves. Case caveat: pydantic-settings lowercases env-sourced keys for these fields, matching the field names used above.

- [ ] **Step 4: Run** — `uv run pytest tests/test_config_settings.py -x` → PASS (including every pre-existing default-off freeze).
- [ ] **Step 5: Commit** — `feat(config): CLUE_PRODUCT_PATH=integration_pilot checked-in activation overlay (contract §9)`

### Task A2: fail-visible composition preflight for the product path

**Files:**
- Create: `platform/api/clue_api/product_path_preflight.py`
- Modify: `platform/api/clue_api/projections_main.py` (after `load_settings()`, ~line 303), `platform/api/clue_api/fleet_main.py` (after `settings = load_settings()`, line 529)
- Test: `tests/api/test_product_path_preflight.py`

**Interfaces:**
- Produces: `assert_product_path_composition(settings: Settings, secrets: Secrets) -> None` raising `ProductPathCompositionError(RuntimeError)` naming every missing `CLUE_*` credential.

Rationale: today `Secrets` fields are `SecretStr | None = None` and several paths compose silently-empty (e.g. the email-lookup service builds per-provider "unavailable" outcomes with absent keys — `platform/api/clue_api/projections_main.py:144-155`). The contract requires the product path to "fail visibly when a required credential or composition is missing", once, at startup, instead of scattering per-feature RuntimeErrors.

- [ ] **Step 1: Failing tests**

```python
# tests/api/test_product_path_preflight.py
import pytest
from pydantic import SecretStr

from clue_api.product_path_preflight import ProductPathCompositionError, assert_product_path_composition
from clue_config import Secrets, Settings


def _pilot(**kw):  # noqa: ANN003
    return Settings(_env_file=None, product_path="integration_pilot", **kw)  # type: ignore[call-arg]


def test_default_path_never_raises() -> None:
    assert_product_path_composition(Settings(_env_file=None), Secrets(_env_file=None))  # type: ignore[call-arg]


def test_pilot_with_all_credentials_passes() -> None:
    assert_product_path_composition(
        _pilot(),
        Secrets(  # type: ignore[call-arg]
            _env_file=None,
            exa_api_key=SecretStr("k"),
            sumble_api_key=SecretStr("k"),
            openrouter_api_key=SecretStr("k"),
        ),
    )


def test_pilot_names_every_missing_credential() -> None:
    with pytest.raises(ProductPathCompositionError) as err:
        assert_product_path_composition(_pilot(), Secrets(_env_file=None))  # type: ignore[call-arg]
    msg = str(err.value)
    assert "CLUE_EXA_API_KEY" in msg
    assert "CLUE_SUMBLE_API_KEY" in msg
    assert "CLUE_OPENROUTER_API_KEY" in msg
```

- [ ] **Step 2: Run to fail** — module missing.
- [ ] **Step 3: Implement**

```python
# platform/api/clue_api/product_path_preflight.py
"""One startup gate: the integration product path fails loudly when a required credential
is absent (contract §9), instead of composing silently-degraded provider slots."""

from clue_config import Secrets, Settings


class ProductPathCompositionError(RuntimeError):
    pass


_REQUIREMENTS: tuple[tuple[str, str, str], ...] = (
    # (settings flag, secrets attr, env var named in the error)
    ("exa_websets_lifecycle_enabled", "exa_api_key", "CLUE_EXA_API_KEY"),
    ("exa_account_deep_acquisition_enabled", "exa_api_key", "CLUE_EXA_API_KEY"),
    ("exa_contact_deep_acquisition_enabled", "exa_api_key", "CLUE_EXA_API_KEY"),
    ("sumble_account_gap_enrichment_enabled", "sumble_api_key", "CLUE_SUMBLE_API_KEY"),
    ("sumble_committee_acquisition_enabled", "sumble_api_key", "CLUE_SUMBLE_API_KEY"),
    ("chat_enabled", "openrouter_api_key", "CLUE_OPENROUTER_API_KEY"),
    # Slice F appends: (contact_channel/email lookup, exa+sumble keys).
)


def assert_product_path_composition(settings: Settings, secrets: Secrets) -> None:
    if settings.product_path != "integration_pilot":
        return
    missing = sorted(
        {
            env_name
            for flag, secret_attr, env_name in _REQUIREMENTS
            if getattr(settings, flag) and getattr(secrets, secret_attr) is None
        }
    )
    if missing:
        raise ProductPathCompositionError(
            "integration_pilot product path is missing required credentials: " + ", ".join(missing)
        )
```

- [ ] **Step 4: Wire into both composition roots.** In `projections_main.py` immediately after settings/secrets resolution, and in `fleet_main.py:529` after `settings = load_settings()`: `assert_product_path_composition(settings, secrets)`. (Read each root first; both already construct `Secrets` — reuse the same instance, do not construct a second.)
- [ ] **Step 5: Run** — `uv run pytest tests/api/test_product_path_preflight.py -x`, then `uv run pytest tests/api/test_frontend_read_app.py tests/api/test_entity_research_cutover_r10.py -x` (roots still import-clean).
- [ ] **Step 6: Commit** — `feat(api): integration-pilot startup preflight fails loudly on missing provider credentials`

### Task A3: freeze the 21-field and 15-field request contracts + static provider ownership

**Files:**
- Create: `platform/api/clue_api/comprehensive_research_contract.py`
- Test: `tests/api/test_comprehensive_research_contract.py`

**Interfaces (consumed by B4, F3):**
- `COMPREHENSIVE_ACCOUNT_FIELDS: tuple[str, ...]` — re-export of `PROSE_ACCOUNT_FIELDS` (`subsystems/research/clue_research/narrative/prose.py:142-164`).
- `COMPREHENSIVE_ACCOUNT_FIELD_SOURCES: dict[str, tuple[str, ...]]` — contract §3.1 static ownership, values drawn only from `{"exa_deep","sumble_organizations","sumble_jobs","sumble_tech_stack"}` (plus `()` for the two derive-only fields).
- `CONTACT_STRUCTURED_FIELDS: tuple[str, ...]` (6 Sumble-owned), `CONTACT_DEEP_FIELDS: tuple[str, ...]` (9 Exa-owned) — partition of `PROSE_CONTACT_FIELDS` (`prose.py:189-206`).

- [ ] **Step 1: Failing test freezing the exact lists (order included) and the partition**

```python
# tests/api/test_comprehensive_research_contract.py
from clue_api.comprehensive_research_contract import (
    COMPREHENSIVE_ACCOUNT_FIELD_SOURCES,
    COMPREHENSIVE_ACCOUNT_FIELDS,
    CONTACT_DEEP_FIELDS,
    CONTACT_STRUCTURED_FIELDS,
)
from clue_research.narrative.prose import PROSE_ACCOUNT_FIELDS, PROSE_CONTACT_FIELDS

_PERMITTED_ACCOUNT_SOURCES = {"exa_deep", "sumble_organizations", "sumble_jobs", "sumble_tech_stack"}


def test_the_21_field_account_contract_is_frozen_verbatim() -> None:
    assert COMPREHENSIVE_ACCOUNT_FIELDS == PROSE_ACCOUNT_FIELDS
    assert len(COMPREHENSIVE_ACCOUNT_FIELDS) == 21
    assert COMPREHENSIVE_ACCOUNT_FIELDS[0] == "core.account_name"
    assert COMPREHENSIVE_ACCOUNT_FIELDS[20] == "account.resonance.buying_culture"


def test_every_account_field_has_static_ownership_within_the_permitted_set() -> None:
    assert set(COMPREHENSIVE_ACCOUNT_FIELD_SOURCES) == set(COMPREHENSIVE_ACCOUNT_FIELDS)
    for field, sources in COMPREHENSIVE_ACCOUNT_FIELD_SOURCES.items():
        assert set(sources) <= _PERMITTED_ACCOUNT_SOURCES, field
    # §3.1 spot checks:
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["core.primary_tech_stack"] == ("sumble_tech_stack",)
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["account.hiring_velocity_eng"] == ("sumble_jobs",)
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["account.operational_pain"] == ("exa_deep",)
    # Derive-only fields own no acquisition source:
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["core.employee_range"] == ()
    assert COMPREHENSIVE_ACCOUNT_FIELD_SOURCES["core.revenue_band"] == ()


def test_the_15_field_contact_partition_is_exact_and_disjoint() -> None:
    assert CONTACT_STRUCTURED_FIELDS + CONTACT_DEEP_FIELDS == PROSE_CONTACT_FIELDS
    assert len(CONTACT_STRUCTURED_FIELDS) == 6
    assert len(CONTACT_DEEP_FIELDS) == 9
    assert all(k.startswith("contact.facet.") for k in CONTACT_DEEP_FIELDS)
    assert not any(k.startswith("contact.facet.") for k in CONTACT_STRUCTURED_FIELDS)
```

- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Implement the module** — literal tuples/dict transcribed from contract §3.1 / §7.1 (module docstring cites the contract path; §3.1 row 2/3/7/etc. multi-source fields get `("exa_deep", "sumble_organizations")`-style tuples in provider-preference order: structured Sumble first for structured facts, `exa_deep` first for qualitative).
- [ ] **Step 4: Run → PASS. Commit** — `feat(api): freeze the 21/15-field comprehensive research contracts and static provider ownership`

### Task A4: excluded-providers guard

**Files:**
- Test: `tests/api/test_comprehensive_research_contract.py` (append)

- [ ] **Step 1: Write the guards (fail if anyone later widens composition):**

```python
def test_the_account_launcher_supports_exactly_the_four_permitted_field_sources() -> None:
    from clue_api.account_research_fleet_launch import _SUPPORTED_FIELD_SOURCES

    assert _SUPPORTED_FIELD_SOURCES == frozenset(_PERMITTED_ACCOUNT_SOURCES)


def test_committee_discovery_has_exactly_one_provider_and_no_fallback() -> None:
    # Contract §5.1 / annotation 9: Sumble Teams/People only.
    from clue_api.account_research_fleet_launch import PEOPLE_SOURCE_KEY

    assert PEOPLE_SOURCE_KEY == "sumble_people"


def test_no_excluded_provider_family_is_importable_from_the_entity_research_wiring() -> None:
    import inspect

    import clue_api.entity_research_provider_wiring as wiring

    source = inspect.getsource(wiring)
    for banned in ("firecrawl", "apollo", "zoominfo", "builtwith", "scrapling", "clay"):
        assert banned not in source.lower(), banned
```

- [ ] **Step 2: Run → PASS immediately (these freeze current truth; they are regression tripwires, so no red phase is expected — note it in the test docstring).**
- [ ] **Step 3: Commit** — `test(api): tripwires keeping excluded providers out of the research composition (contract §2.2)`

### Task A5: document the activation surface

**Files:**
- Modify: `.env.example` (append the never-documented vars: `CLUE_PRODUCT_PATH`, `CLUE_EXA_ACCOUNT_DEEP_ACQUISITION_ENABLED`, `CLUE_SUMBLE_COMMITTEE_ACQUISITION_ENABLED`, `CLUE_C7_SNAPSHOT_COMPOSE_ENABLED`, `CLUE_C7_PRODUCTION_HANDOFF_ENABLED`, `CLUE_FRONTEND_READ_ENABLED`, each with a one-line comment naming the contract §9 row; values left `false`/`default` — the overlay, not the example file, is the activation record).

- [ ] **Step 1: Append the block; run `uv run pytest tests/test_config_settings.py -x` (unchanged).**
- [ ] **Step 2: Commit** — `docs(env): document every contract-§9 flag and CLUE_PRODUCT_PATH in .env.example`

**Slice A exit gate:** `make check` green; founder starts API + fleet with only `CLUE_PRODUCT_PATH=integration_pilot` plus real keys in the local `.env`, sees a loud preflight error when a key is deliberately removed, and a clean boot when restored.

---

# Slice B — comprehensive account execution

Contract §11-B: reuse fresh Exa Websets claims; admit `core.*` fields to the account launch path; route every remaining fixed field to Exa Deep or the correct Sumble action; internally batch Exa field bundles; prove all 21 fields reach a settled attempted/satisfied state per account.

**What already exists and is deliberately NOT rebuilt** (from the code recon — do not duplicate any of this):
- Fresh-claim reuse happens *inside the job*, not at launch: `born_complete_account_field_keys` (`platform/api/clue_api/account_entity_research.py:127`) is subtracted during Exa preparation (`platform/api/clue_api/exa_deep_preparation.py:141-157`, emitting `"{field}:existing_claim_fresh"` skips). The launcher's comment block (`account_research_fleet_launch.py:244-269`) records why a launch-time freshness probe would corrupt replay identity. **Keep this design** — "reuse fresh discovery claims" (§3.2 step 2) is already satisfied post-launch; Slice B only has to *prove* it covers Websets-written `core.*` facts once those fields are admitted.
- Exa >8-field bundling exists: `EXA_OUTPUT_MAX_FIELDS = 8` (`subsystems/research/clue_research/resolvers/exa/deep_contract.py:51`) enforced at `validate_exa_output_schema` and greedily packed by `compile_exa_deep_acquisition_plan` (`platform/api/clue_api/exa_deep_acquisition.py:881-998`) into deterministic bundles behind one job. **Keep**; only prove ~13 Exa-owned fields split into ≥2 bundles.
- Per-field source compilation already runs `plan_sources(mode=ACCOUNT_PROFILING)` per field and freezes `FieldSourceAuthority` rows (`account_research_fleet_launch.py:341-435`).

### Task B1: admit `core.*` fields at the launcher

**Files:**
- Modify: `platform/api/clue_api/account_research_fleet_launch.py:325-332`
- Test: `tests/api/test_account_research_fleet_launch_r6_db.py` (append)

- [ ] **Step 1: Failing DB test** — extend the existing single test file's fixtures (`confirmed_account_research_direction(...)` from `tests/api/account_deep_test_support`) to confirm a directive whose `field_keys` include `core.industry`, `core.primary_tech_stack`, `account.hiring_velocity_eng`, `account.operational_pain`; assert the launched selection's `admitted_field_keys` contains all four (today the two `core.*` keys are silently dropped and, if all fields were `core.*`, launch raises).

```python
def test_core_fields_survive_launch_and_are_not_silently_dropped(...):
    ...
    assert "core.industry" in selection.admitted_field_keys
    assert "core.primary_tech_stack" in selection.admitted_field_keys
```

- [ ] **Step 2: Run to fail.**
- [ ] **Step 3: Replace the raw prefix filter with the shared axis projection** (the runtime already uses it at `exa_deep_preparation.py:141`):

```python
# account_research_fleet_launch.py — replace lines 325-327
from clue_core.field import account_axis_field_keys  # with the existing imports

            field_keys = tuple(str(k) for k in account_axis_field_keys(first.field_keys))
```

`account_axis_field_keys` (`libs/clue-core/clue_core/field.py:108-118`) admits `FieldClass.CORE | ACCOUNT | ACCOUNT_RESONANCE | PACK` and is the same projection the in-job preparation uses — launcher and runtime can no longer disagree about the field universe.

- [ ] **Step 4: Run → PASS. Also rerun the file's original test unchanged.**
- [ ] **Step 5: Commit** — `fix(launch): admit core.* account fields via the shared account-axis projection (contract §3.3 row 2)`

### Task B2: widen the `account.%`-only DB constraints

**Files:**
- Create: `alembic/versions/<hash>_widen_account_coverage_field_axis.py` (via `uv run alembic revision -m "widen account coverage field axis to core fields"`)
- Test: `tests/api/test_account_entity_research_r5_db.py` (append one insert-shaped test)

The coverage table's field-axis CHECK forces `account.%` keys (`alembic/versions/85595185f793_m8d_r5_account_research_agent_state.py:195` on `entity_research_account_coverage.completed_field_keys` / `unresolved_field_keys`). With `core.*` admitted, a job settling `core.industry` would violate it.

- [ ] **Step 1:** `grep -rn "account\.%" alembic/versions/` and `grep -rn "startswith(\"account\.\")\|startswith('account.')" platform subsystems libs` — enumerate every constraint/guard on the launch-field axis. Known: the 85595185f793 CHECK; expect possible siblings on `entity_research_result_field` / review tables. Every hit that stores *launch field keys* gets widened; anything storing only qualitative claim output stays.
- [ ] **Step 2: Failing DB test** — insert a coverage row with `completed_field_keys=["core.industry"]` → currently `IntegrityError`.
- [ ] **Step 3: Migration** — hash id, `down_revision` = current head; `upgrade()` drops and recreates each CHECK as `(field LIKE 'account.%' OR field LIKE 'core.%')` (token-named constraints, exact names copied from the original migration); `downgrade()` restores the original text.
- [ ] **Step 4:** `make db-smoke` on a throwaway DB; `uv run alembic heads` → exactly one head. Run the test → PASS.
- [ ] **Step 5: Commit** — `feat(db): coverage field axis admits core.* launch fields`

### Task B3: static ownership reaches the source planner

**Files:**
- Modify: `subsystems/research/clue_research/sources/seeds.py` (the `exa_deep`, `sumble_organizations`, `sumble_jobs`, `sumble_tech_stack` entries' `yields`)
- Test: `tests/api/test_comprehensive_research_contract.py` (append), `tests/sources/test_source_manifest.py` (update frozen expectations)

The launcher plans per-field sources with `plan_sources(...)`/`load_effective_source_plan(...)` and then intersects with `_SUPPORTED_FIELD_SOURCES`; a field no permitted source *yields* raises `"no composed R5 source is authorized for {field}"` (`account_research_fleet_launch.py:418-421`). So the §3.1 ownership table must be reflected in the manifest `yields`.

- [ ] **Step 1: Failing test** — for every field in `COMPREHENSIVE_ACCOUNT_FIELDS` except the two derive-only fields (`core.employee_range`, `core.revenue_band`) and identity-reuse `core.account_name`, assert the planned source set is non-empty and a subset of `COMPREHENSIVE_ACCOUNT_FIELD_SOURCES[field]` (call the same `plan_sources(mode=ResearchMode.ACCOUNT_PROFILING, entity_scope=EntityScope.ACCOUNT)` path the launcher uses).
- [ ] **Step 2: Run; record which fields currently plan empty** (expected: most `core.*` rows).
- [ ] **Step 3: Extend `yields`** on the four permitted seed entries exactly per `COMPREHENSIVE_ACCOUNT_FIELD_SOURCES` (e.g. `sumble_organizations` gains `core.industry`, `core.company_about`, `core.employee_count`, `core.hq_location`, `core.annual_revenue`, `core.company_linkedin_url`, `account.total_funding`, `account.recent_funding`; `sumble_jobs` gains `account.hiring_velocity_eng`; `sumble_tech_stack` gains `core.primary_tech_stack`; `exa_deep` gains the qualitative + funding fields it owns in §3.1). Update `test_source_manifest.py` frozen expectations in the same commit — that file is the drift guard, and this is a deliberate, contract-cited drift.
- [ ] **Step 4: Run both test files → PASS. Commit** — `feat(sources): permitted-source yields cover the fixed 21-field profile (contract §3.1 ownership)`

### Task B4: the deterministic comprehensive-profile compiler at directive drafting

**Files:**
- Modify: `platform/api/clue_api/*` module defining `draft_account_research_directive` (locate via `grep -rn "draft_account_research_directive" platform/api`), adding the expansion
- Create: `platform/agents/catalog/skills/account-deep-steering/v7/SKILL.md` (copy of v6 + amended field vocabulary)
- Create: `platform/agents/catalog/profiles/head-of-abm/v37/profile.yaml` (copy of v36, skill pin → v7, new tool schema sha for the directive tool)
- Modify: the active-profile map `C6_ACTIVE_PROFILE_VERSIONS` (`platform/api/clue_api/agent_registry_wiring.py:38-45`, `HEAD_OF_ABM: "v37"`) and `PROJECT_CONVERSATION_AGENT_PROFILE_ID` (`platform/api/clue_api/chat/composer_context.py:41`)
- Test: `tests/api/test_comprehensive_research_contract.py` (append), the profile/registry parity tests (`tests/api/test_agent_registry_wiring.py`)

Contract §3.2 wants *mechanical* expansion, and §3.3 row 1 wants "full-profile commands compile to all 21 fields unless the user explicitly requests a narrower subset". The deterministic seat for that is the directive-draft tool, not agent prose:

- [ ] **Step 1: Failing test** — drafting a directive with the new input `profile="comprehensive"` (and no explicit `field_keys`) produces a directive whose `field_keys == COMPREHENSIVE_ACCOUNT_FIELDS`; `profile="custom"` with explicit keys passes them through unchanged; `profile="comprehensive"` **with** explicit keys is rejected (ambiguous request — the agent must pick one).
- [ ] **Step 2: Implement** — add `profile: Literal["comprehensive", "custom"] = "comprehensive"` to the tool's input model; in the tool body, when `comprehensive`, set `field_keys = COMPREHENSIVE_ACCOUNT_FIELDS` before validation. Bump the tool version (v3 → v4) since the input schema changes; regenerate the schema shas in profile v37.
- [ ] **Step 3: Skill v7** — copy v6, replace the three-field "standard qualitative acquisition fields" block (`v6/SKILL.md:88-94`) with: the normal comprehensive request compiles to the complete fixed 21-field account profile via `profile="comprehensive"`; a narrower subset only when the user explicitly asks; name the four permitted sources (`exa_deep`, `sumble_organizations`, `sumble_jobs`, `sumble_tech_stack`) and that `core.*` identity/firmographic fields are reused from discovery when fresh. Keep the v6 rules about derived outputs and never inventing field keys verbatim.
- [ ] **Step 4: Promote v37** and update the two version pins; run `tests/api/test_agent_registry_wiring.py` + `tests/agents/test_tool_authority_audit.py` (the registry equality guard at `agent_registry_wiring.py:~465` will catch a missed grant).
- [ ] **Step 5: Run → PASS. Commit** — `feat(agents): comprehensive directive profile — 21 fields by default, narrower only on explicit request`

### Task B5: decouple account-only research from committee configuration

**Files:**
- Modify: `platform/api/clue_api/entity_research_provider_wiring.py:361-367`
- Test: `tests/api/test_account_research_fleet_launch_r6_db.py` (append)

Today the committee gate raises **unconditionally** for every account job (`EntityResearchProductionCompositionError("R6 account research requires enabled no-reveal Sumble committee acquisition")`), even when the job's selection carries no committee sources (audit gap #5, contract §3.3 row 4 spirit).

- [ ] **Step 1: Failing test** — compose `ProductionAccountResearchProviderActions` with `sumble_committee_acquisition_enabled=False` (reuse the file's exact inline-Settings pattern at `:303-328`) against a job whose `authorization.selection.committee_source_keys == ()`: expect bindings to resolve with `discover_buying_committee` present as an `_UnavailableProviderAction` (governed `provider_not_selected` rejection), not a composition error. Second assertion: with committee sources selected and the flag off, composition still raises (fail-visible stays).
- [ ] **Step 2: Move the gate:**

```python
# entity_research_provider_wiring.py — replace the unconditional block at 361-367
        committee_requested = bool(context.selection.committee_source_keys)
        if committee_requested and (
            not self._settings.sumble_committee_acquisition_enabled
            or self._secrets.sumble_api_key is None
        ):
            raise EntityResearchProductionCompositionError(
                "committee-selecting account research requires enabled no-reveal "
                "Sumble committee acquisition"
            )
        if not committee_requested:
            committee_action: ProviderAction = _UnavailableProviderAction(
                "this run's confirmed directive selected no committee discovery"
            )
        else:
            committee_action = SumbleCommitteeSemanticResearchAction(...)  # existing construction 369-386
```

(Adapt names to the file's local variables when editing; the existing construction block at `:369-386` moves into the `else`.)

- [ ] **Step 3: Run → PASS**, plus `tests/api/test_sumble_committee_preparation_wiring_o2.py` unchanged.
- [ ] **Step 4: Commit** — `fix(wiring): account-only research composes without committee configuration (audit gap 5)`

### Task B6: Sumble structured actions materialize the owned fields

**Files:**
- Modify: `platform/api/clue_api/sumble_account_gaps.py` + `subsystems/research/clue_research/resolvers/sumble/__init__.py` (claim field mappings, only where a §3.1-owned field is missing)
- Test: `tests/api/test_sumble_account_gaps_s1.py` (append per-field materialization cases over recorded fixtures)

- [ ] **Step 1: Inventory** — read the Sumble organizations/jobs/tech normalization and claim materialization; list which of the owned fields already produce claims (`core.employee_count`, `core.hq_location`, … from Organizations; `account.hiring_velocity_eng` from Jobs; `core.primary_tech_stack` from Tech Stack) and which are dropped on the floor.
- [ ] **Step 2: Failing tests per missing field** — fixture response → expect a governed claim (`source_key` = the owning Sumble source, provider-returned provenance, evidence span from the payload, workspace-stamped).
- [ ] **Step 3: Extend the normalized→claim mapping** for each missing field; never invent values — absent payload keys stay honest-empty with an `unresolved_reasons` entry.
- [ ] **Step 4: Run → PASS. Commit** — `feat(sumble): organizations/jobs/tech materialize every §3.1-owned account field they can support`

### Task B7: derive `core.employee_range` and `core.revenue_band` from governed evidence

**Files:**
- Create: `platform/api/clue_api/account_field_derivation.py`
- Modify: the account job finalization path in `platform/api/clue_api/account_entity_research.py` (call the deriver before the coverage row is written)
- Test: `tests/api/test_account_field_derivation.py`

Contract §3.1 rows 5 and 8: "Reuse or derive from governed employee-count / revenue evidence."

- [ ] **Step 1: Failing tests** — given a fresh governed `core.employee_count` claim (value 1 200) and no `core.employee_range` claim, the deriver writes an `core.employee_range` claim whose value is the canonical band; the claim carries `provenance_kind=ClaimProvenanceKind.PLATFORM_INFERRED`, the *source claim's* `source_url`/`evidence_span`/tier, and never `ExtractionMethod.HUMAN`. Same for `core.annual_revenue` → `core.revenue_band`. When the source claim is absent or stale, no claim is written and the field lands in `unresolved_field_keys` with reason `derivation_source_missing`.
- [ ] **Step 2: Implement** — reuse the existing band vocabulary: the Websets enrichment path already maps a provider `core.revenue_band` (`platform/api/clue_api/exa_websets_materialization.py:353-383`); read the registered band enumerations from the field registry rather than inventing new buckets. Deterministic thresholds live in this one module.
- [ ] **Step 3: Wire into finalization** so a job that acquired `core.employee_count` settles `core.employee_range` in the same run; idempotent on `(entity, field, run)` like every claim write.
- [ ] **Step 4: Run → PASS. Commit** — `feat(research): deterministic employee-range/revenue-band derivation from governed evidence`

### Task B8: end-to-end 21-field settle proof

**Files:**
- Test: `tests/api/test_comprehensive_account_execution_db.py` (new)

- [ ] **Step 1: Write the acceptance test** (DB-backed, provider doubles, following `tests/api/test_account_entity_research_fresh_skip_db.py` fixtures): seed a discovered account with fresh Websets claims for the 7 discovery-written fields (`exa_websets_materialization.py:272-316` vocabulary); confirm a comprehensive directive (Task B4); launch (Task B1); drive the job with recorded Exa Deep + Sumble doubles; assert on the final coverage row:
  - `set(completed) ∪ set(unresolved) ∪ {skipped existing_claim_fresh}` == all 21 fields — nothing silently vanished;
  - discovery-fresh fields appear as `existing_claim_fresh` skips (reuse, no re-buy);
  - Exa-owned fields split into ≥2 bundles (assert on the acquisition plan's bundle count for 9+ Exa fields);
  - a deliberately-empty provider double leaves its field in `unresolved_field_keys` with an honest reason, not a fabricated value.
- [ ] **Step 2: Run → PASS. Commit** — `test(api): all 21 account fields reach settled attempted/satisfied state per account (contract §11-B exit)`

**Slice B exit gate:** `make check` + `make db-smoke` green; founder browser test: a normal "research this account" chat request compiles to 21 fields (visible in the directive confirmation card), the run settles, and the account profile shows the newly acquired `core.*`/Sumble facts or honest empties.

---

# Slice C — live account progress

Contract §11-C + §4: durable task projection over detached fleet state; the existing card streams/refreshes from it; the progress bar advances as accounts settle. Explicitly **no** provider-coverage diagnostics UI.

**Existing machinery (recon):** the projection already exists — `research_tasks_for_action_refs` (`platform/projections/clue_projections/research_tasks.py:116`) counts queued/running/blocked/completed/partial/failed live from `entity_research_job` and already unions account fleets + contact launches; `task_part_from_run` (`platform/api/clue_api/chat/turn_parts.py:384`) maps it to the card wire. The defects: (1) it has **no HTTP surface** — its only caller is the one-shot turn-close snapshot (`turn_stream.py:908-924`); (2) `needs_review` is folded into `partial` while the contract demands it distinctly; (3) the card is stream-only — a reload beyond `REHYDRATED_TURNS = 3` (`use-project-chat-controller.ts:71`) loses it entirely; (4) the turn SSE closes at the terminal turn event (`chat/stream.py:435,454`), so post-turn progress cannot ride the existing stream. The design: **poll a durable read**, following the established email-lookup polling pattern (`use-email-lookup-controller.ts`, 3 s re-armed timeout) — no new streaming channel.

### Task C1: split `needs_review` out of `partial` end to end

**Files:**
- Modify: `platform/projections/clue_projections/research_tasks.py` (`ResearchTaskCounts:39`, `_TASKS_SQL:71`), `platform/api/clue_api/chat/turn_parts.py:210-220` (wire mapping), `apps/frontend/src/features/projects/model/chat-parts.ts:239-268` (`TaskCountsWireSchema`, `ChatTaskCounts`), `apps/frontend/src/features/projects/model/research-task.ts` (counts + summary strings)
- Test: `tests/api/test_lane_d5_gate_read_and_rich_parts_db.py` (extend), `apps/frontend/src/features/projects/model/research-task.test.ts` (extend)

- [ ] **Step 1: Failing backend test** — a run with one job terminal `finalization_outcome='needs_review'` reports `counts.needs_review == 1` and `counts.partial == 0` (today both fold into `partial`).
- [ ] **Step 2: SQL + model** — in `_TASKS_SQL`, split the terminal bucket: `partial` = `finalization_outcome IN ('exhausted','budget_stopped')`, new `needs_review` = `finalization_outcome = 'needs_review'`; add the field to `ResearchTaskCounts`, the turn-part mapping, the Zod schema (`needsReview`), and the model's settled arithmetic (`settled = completed + partial + needsReview`). **Visual-parity rule applies:** the card renders exactly the copy and states the dummy frontend's designed card already has — the split count lives in the API/model, and the existing card visuals absorb it through the current state mapping (needs-review runs keep whatever state the design already renders for partially-successful runs). Before touching any visible string, compare `chat-research-task.tsx` output against the dummy frontend's card; if the design has no distinct needs-review copy, do not invent one — ask the founder.
- [ ] **Step 3: Run backend + frontend tests → PASS.**
- [ ] **Step 4: Commit** — `feat(progress): needs_review is a first-class task count (contract §4)`

### Task C2: durable HTTP task read for a thread

**Files:**
- Modify: `platform/api/clue_api/chat/router.py` (new route), `platform/api/clue_api/chat/schemas.py` (wire model)
- Create: `platform/projections/clue_projections/thread_research_tasks.py`
- Test: `tests/api/test_thread_research_tasks_db.py`

**Interfaces:**
- Produces: `GET /projects/{project_id}/threads/{thread_id}/research-tasks` → `{ "tasks": [TaskWire, ...] }`, where `TaskWire` is shape-compatible with `ChatTaskPart` (`partId`, `revision`, `state`, `title`, `runRef`, `counts`, plus `fieldProgress: {completed, unresolved} | null`). `revision` = `max(entity_research_job_event.event_seq)` over the run's jobs (globally monotonic identity column — migration `022b1154b3aa:280` — so a fresher poll always outranks the turn-close snapshot revision in the transcript reducer's highest-revision-wins merge).
- Consumes: `research_tasks_for_action_refs` (C1 shape), `derive_turn_action_ref`, `read_account_coverage_in_run` (`platform/api/clue_api/account_research_coverage.py:103`).

- [ ] **Step 1: Failing DB test** — seed a thread with a turn that launched a 3-account fleet (reuse the Lane-D5 seeding helpers at `tests/api/test_lane_d5_gate_read_and_rich_parts_db.py:731`); flip one job to terminal-completed; call the route; assert `counts == {total:3, queued:2, running:0, …, completed:1, …}`, that a second poll after a second settle **increases `revision`**, and that a thread with no launches returns `tasks: []`. Auth: same `PERMISSION_THREAD_WRITE`/read principal checks as the sibling gates route (`router.py:1300`).
- [ ] **Step 2: Implement the projection** — `thread_research_tasks(conn, *, workspace_id, project_id, thread_id)`: select the thread's turn ids (the turn table the gates/turns reads already query), map to `derive_turn_action_ref(turn_id)`, delegate to `research_tasks_for_action_refs`, decorate each with `revision` (one `SELECT max(e.event_seq) FROM entity_research_job_event e JOIN entity_research_job j USING (job_id) WHERE j.research_run_id = :run_id`) and `fieldProgress` (sum of `len(completed_field_keys)` / `len(unresolved_field_keys)` over the latest coverage row per settled job — account runs only, `null` for contact runs until Slice F).
- [ ] **Step 3: Route + wire model** in `router.py`/`schemas.py`, mirroring the gates route's dependency wiring.
- [ ] **Step 4: Run → PASS. Commit** — `feat(chat): durable research-task read for a thread — the live source the card polls`

### Task C3: the card polls the durable read

**Files:**
- Create: `apps/frontend/src/features/projects/hooks/use-research-task-poller.ts`, `apps/frontend/src/features/projects/data/chat-research-tasks.repository.ts`
- Modify: `apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts` (mount the poller; feed results into the transcript's task aggregation), `apps/frontend/src/features/projects/data/chat-repositories.ts` (+ DI), `apps/frontend/src/features/projects/model/chat-parts.ts` (parse the wire)
- Test: `apps/frontend/src/features/projects/hooks/use-research-task-poller.test.ts`, extend `model/research-task.test.ts`

- [ ] **Step 1: Failing model test** — a polled task snapshot with a higher revision replaces the stream snapshot for the same `runRef.objectId` via `aggregateResearchTasks` (`model/research-task.ts`); a lower-revision poll result never regresses the card.
- [ ] **Step 2: Repository** — `listThreadResearchTasks(projectId, threadId)` against the C2 route, Zod-parsed with `TaskCountsWireSchema` (+ `needsReview`, `fieldProgress`).
- [ ] **Step 3: Poller hook** — clone the email-lookup controller pattern (`use-email-lookup-controller.ts`): `POLL_DELAY_MS = 3_000`, re-armed `window.setTimeout` while any task is non-terminal (`ACTIVE`/`BLOCKED` states in `model/research-task.ts:71-80`), cleared on unmount, stops when every task settles, 401 → the existing sign-in redirect.
- [ ] **Step 4: Mount in the chat controller:** start polling (a) on thread load — this **also fixes cold-load loss**: the durable read re-materializes cards for runs whose turns fell outside `REHYDRATED_TURNS`; and (b) whenever a stream `part.created` task part arrives. Polled tasks flow into the same transcript state the stream parts use, so the existing card component (`chat-research-task.tsx`) is **unchanged** — no visual redesign.
- [ ] **Step 5: Run frontend gate** — `npm run design-system:build && npm run lint && npm run build`, plus the `tsx --test` unit suites touched.
- [ ] **Step 6: Commit** — `feat(frontend): research task card follows durable fleet state via 3s poll; cards survive reload`

### Task C4: settle-advance acceptance proof

**Files:**
- Test: `tests/api/test_thread_research_tasks_db.py` (append)

- [ ] **Step 1:** one test driving three seeded jobs through `queued → leased → running → terminal(completed | needs_review | failed)` via the job-event ledger, polling the C2 route after each transition, asserting the counts sequence is monotone and truthful at every step (never `Queued — 0 of N` after any job leaves `queued`).
- [ ] **Step 2: Commit** — `test(chat): task read advances truthfully at every job transition (contract §11-C exit)`

### Task C5: chat transcript pagination — newest-first initial load, upward cursor scrollback

Founder-ratified scope addition (2026-08-18): the audit's chat-loading defect is fixed alongside Slice C. Today the durable messages read returns the **oldest 50** messages and the frontend makes one request and never follows the pagination cursor (`platform/projections/clue_projections/threads.py:586`, `apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts:281`) — so in a thread past 50 messages, recent user messages vanish on reload while streamed assistant output stays visible. Both user messages in the audited thread were durably stored (rows 59/61); this is purely a read-direction + cursor-consumption defect. **No data-model change, no new UI components** — the fix is ordering, cursor plumbing, and scroll behavior on the existing message list (visual-parity rule applies: the list looks identical, it just loads the right end first).

**Files:**
- Modify: `platform/projections/clue_projections/threads.py` (message page ordering + backward cursor), `platform/api/clue_api/chat/router.py:1244` (`GET /projects/{project_id}/threads/{thread_id}/messages` — accept the backward-page parameter), `platform/api/clue_api/chat/schemas.py` (`MessageListResponse` cursor field naming, only if absent)
- Modify: `apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts` (initial newest-page load + land at bottom; scroll-top → fetch preceding page, prepend, preserve scroll offset), `apps/frontend/src/features/projects/data/chat-messages.repository.ts` (cursor-aware fetch), `apps/frontend/src/features/projects/model/chat-transcript.ts` (prepend merge; durable/optimistic/streamed dedupe by message/turn identity — the reducer's existing identity guards are the merge seam)
- Test: `tests/api/test_chat_thread_surface_db.py` (append), `apps/frontend/src/features/projects/model/chat-transcript.test.ts` (append)

- [ ] **Step 1: Read the current pagination contract** — `threads.py` message query + cursor shape, the router's query params, and the repository's fetch. Record whether a cursor is already returned (the audit says it is returned and ignored) and its ordering semantics before changing anything.
- [ ] **Step 2: Failing backend test** — seed a thread with 120 messages; the default page returns the **newest** 50 in ascending display order with a `before`-style cursor; requesting with that cursor returns the preceding 50; walking cursors to exhaustion yields all 120 exactly once; a thread under one page returns everything with no cursor.
- [ ] **Step 3: Implement the backend ordering/cursor** — newest-first page selection (`ORDER BY … DESC LIMIT 50`, then reverse for ascending display order within the page), keyset cursor on the existing message ordering key (no OFFSET). Keep the old oldest-first parameterization working if any other consumer uses it (Step 1 inventory decides; if none, the default simply flips).
- [ ] **Step 4: Failing frontend test** — a >50-message transcript state hydrated from the newest page contains the latest user message; prepending an older page never duplicates a message already present from the stream projection or optimistic send (dedupe by message/turn identity); prepend does not reorder existing entries.
- [ ] **Step 5: Implement the frontend** — initial load fetches the newest page and lands at the bottom; a scroll-to-top sentinel on the **existing** message list fetches the preceding page and prepends while preserving the user's scroll position; repeat until the cursor is exhausted. No new visual components, no spinners or headers the dummy frontend doesn't have — if the dummy build shows nothing during scrollback fetch, show nothing.
- [ ] **Step 6: Run** — backend suite + frontend gate (`npm run design-system:build && npm run lint && npm run build`) → PASS.
- [ ] **Step 7: Commit** — `fix(chat): newest-first transcript load with upward cursor pagination; user messages survive reload in long threads`

**Slice C exit gate:** backend + frontend gates green; founder browser test: launch a multi-account run, close the turn, watch the card advance to settled without any interaction; reload mid-run and see the same live card; reload a >50-message thread and see the newest messages (including your own latest prompts) with older history loading on upward scroll.

---

# Slice D — Sumble committee and agent role inference

Contract §11-D + §5: enable Sumble Teams/People discovery (flag landed in A); preserve identity lineage (already enforced — `DurableSumbleCommitteeInputResolver`, `platform/api/clue_api/sumble_committee_inputs.py:78-303`, resolves the sealed batch, directive pins, and the exact matched Sumble organization from the S1 snapshot); have the **account agent** persist role/confidence/reasoning/evidence as agent-derived inference; show the committee without new gates.

**Current truth being corrected (recon):** role inference today happens *inside* `discover_committee` as a worker leaf-LLM call (`infer_role` + `gate_role`, `subsystems/research/clue_research/profiling/committee/worker.py:426-451`), and its provenance fallback stamps `ExtractionMethod.HUMAN` / tier 1 / no URL / no span whenever a candidate lacks a grounding URL or title (`_provenance_params`, `worker.py:97-116`) — the false-human-provenance defect (audit gap #9). `needs_review` is a hardcoded `0` (`worker.py:503-511`). The contract's §5.2 flow moves the judgment to the account agent, which already runs the job as a governed deepagent with the account research, ICP pins, product context, and buying-unit scope in its context (`platform/api/clue_api/account_entity_research_composition.py`, catalog `platform/agents/catalog/entity-research/account/v1/`).

### Task D1: kill the false-HUMAN provenance fallback (independent, smallest, first)

**Files:**
- Modify: `subsystems/research/clue_research/profiling/committee/worker.py:97-116`
- Test: `tests/profiling/committee/test_worker.py` (append)

- [ ] **Step 1: Failing test** — a candidate with a title but **no** grounding URL yields role/persona claims with `extraction_method is ExtractionMethod.LLM_SYNTHESIS`, `source_tier == SourceTier(4)`, `evidence_span == f"title: {title}"`, `source_url is None`; a candidate with neither URL nor title yields **no role/persona claims at all** (the member survives via its discovery claim; role honestly absent). Assert `ExtractionMethod.HUMAN` appears in zero claims written by the run.
- [ ] **Step 2: Implement** — `_provenance_params` returns the LLM_SYNTHESIS/tier-4 tuple whenever a non-empty title exists (URL optional; span is the promotion requirement, and the title span satisfies it); returns `None` when title-less, and `_write_role_and_persona` skips the two claim writes on `None`. Update the docstring: the M6.3 HUMAN/tier-1 convention is retired here per contract §5.2 ("must not create new false human provenance").
- [ ] **Step 3:** run the committee suite (`uv run pytest tests/profiling/committee -x`) — `test_professional_materialization_c1.py:200` (asserts LLM_SYNTHESIS) stays green.
- [ ] **Step 4: Commit** — `fix(committee): role/persona claims are never stamped HUMAN; ungrounded candidates keep honest empty roles`

### Task D2: split discovery from role inference — the agent infers

**Files:**
- Modify: `subsystems/research/clue_research/profiling/committee/worker.py` (`discover_committee` gains `role_inference: Literal["worker_llm","agent_deferred"] = "worker_llm"`), `subsystems/research/clue_research/profiling/committee/results.py` (`CommitteeMemberRef.role_on_committee/persona` become optional-absent for deferred members; `needs_review` becomes the count of members without a role inference)
- Modify: `platform/api/clue_api/sumble_entity_research_tools.py` (`SumbleCommitteeSemanticResearchAction.execute` passes `role_inference="agent_deferred"`; the projection at `:1291-1360` tolerates roleless members)
- Test: `tests/profiling/committee/test_worker.py`, `tests/api/test_account_entity_research_r5_db.py`

- [ ] **Step 1: Failing worker test** — `discover_committee(..., role_inference="agent_deferred")` admits/identity-resolves members, writes discovery-provenance + professional-fact claims exactly as today, writes **zero** role/persona claims, makes **zero** gateway calls (assert on a counting fake gateway), and returns `needs_review == len(members)`.
- [ ] **Step 2: Implement the mode** — branch around the role block (`worker.py:426-451`); `"worker_llm"` preserves today's behavior for every existing caller/test.
- [ ] **Step 3: Production action passes `"agent_deferred"`**; adjust the member projection integrity rule so a deferred member without role claims is legal while the People-facts requirement (`:1321-1324`) stays.
- [ ] **Step 4: Run committee + r5 suites → PASS. Commit** — `feat(committee): discovery/identity separated from role judgment (contract §5.2 step 1-2)`

### Task D3: the `record_committee_role_inferences` engine tool

**Files:**
- Modify: `platform/api/clue_api/account_entity_research.py` (new engine tool binding beside `account_engine_tool_bindings`, `:1406+`), `platform/agents/clue_agents/account_entity_research.py` (input model), `platform/api/clue_api/account_entity_research_composition.py` (`_ACCOUNT_TOOL_NAMES:49-59` + resolver validation)
- Create: `platform/agents/catalog/entity-research/account/v2/{profile.md,prompt.md,skill.md}` (copy v1; prompt adds the inference step; skill states the honesty rules)
- Modify: `platform/api/clue_api/account_research_fleet_launch.py:592-593` (`agent_profile_ref="agent-profile:account-research:v2"` + new sha via `account_research_profile_sha256`)
- Test: `tests/api/test_account_entity_research_r5_db.py` (append), `tests/agents/test_entity_research_tools_r4.py` (tool-surface freeze update)

**Interfaces:**

```python
class CommitteeRoleInference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    contact_entity_id: UUID
    role: Persona                      # the closed enum — no free-text roles
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=2_000)
    evidence_claim_ids: tuple[UUID, ...] = Field(min_length=1, max_length=16)

class RecordCommitteeRoleInferencesInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    inferences: tuple[CommitteeRoleInference, ...] = Field(min_length=1, max_length=64)
```

- [ ] **Step 1: Failing DB test** — after a deferred-mode committee discovery, the agent tool call: (a) refuses a `contact_entity_id` outside the run's discovered members (typed governed rejection); (b) refuses an `evidence_claim_id` that is not one of that contact's own claims from this account's research (no cross-contact evidence); (c) on success writes `contact.role_on_committee` + `contact.persona` claims with `ExtractionMethod.LLM_SYNTHESIS`, `SourceTier(4)`, `ClaimProvenanceKind.PLATFORM_INFERRED`, `evidence_span` = the cited claim's span (fallback: the member's `title:` span), value `{"role", "confidence", "plausible": true, "rationale"}` per the frozen `_ROLE_VALUE_SCHEMA` (`profiling/committee/fields.py:60-71`); idempotent on `(contact, field, run)`; (d) writes **no** claim for members the agent omits (they stay honestly roleless and count in `needs_review`); (e) `ExtractionMethod.HUMAN` count across the run remains zero.
- [ ] **Step 2: Implement the tool** — reuse the worker's `_write_committee_claim` writer path (export it or lift into a shared helper in the same package) so claim shape/idempotency/stamping stay single-sourced. Per annotation 13, **no plausibility gate**: `plausible` is stamped `True` structurally (the schema requires the key) and `gate_role`/`role_plausible` are not invoked on this path. Recompute the coverage row's committee fields after the write so `committee_status`/`needs_review` reflect the inferences.
- [ ] **Step 3: Surface the tool** — append to `_ACCOUNT_TOOL_NAMES`; bind in `account_engine_tool_bindings`; catalog v2 prompt gains the explicit step: *"after `discover_buying_committee` returns members, infer each member's committee role from the project's existing account research, approved ICP, product context, buying-unit scope, and the member's professional evidence; call `record_committee_role_inferences` citing the exact evidence claim ids; never invent a role for a member whose evidence you cannot cite"*. Launcher pins v2 ref+sha.
- [ ] **Step 4: Run** — r5 suite, runtime r3 suite, tool-authority audit → PASS.
- [ ] **Step 5: Commit** — `feat(agents): account agent records committee role inferences as governed agent-derived claims (contract §5.2)`

### Task D4: honest `needs_review` accounting + display continuity

**Files:**
- Modify: `subsystems/research/clue_research/profiling/committee/results.py`, `platform/api/clue_api/account_entity_research.py:874-895` (no logic change expected — verify), contact-eligibility continuity test in `tests/api/test_r11_committee_bridge.py`
- Test: `tests/api/test_r11_committee_bridge.py` (append)

- [ ] **Step 1: Failing bridge test** — an agent-inferred member (D3 claims) resolves through `ContactEligibilityResolver._resolve_contact_claims` (`platform/api/clue_api/contact_eligibility.py:495-556`) exactly like a worker-inferred member did: STRONG-bound role+persona pair, `plausible=true`, role==persona → the member serves to the contacts read. A roleless member is absent from the *eligibility* committee but still present in discovery (`committee_member_ids`) — assert both, because the contract requires showing every discovered member (the frontend contacts list reads members; role renders empty).
- [ ] **Step 2:** verify `_committee_coverage_status` needs no change (member-count basis unchanged); wire the worker's real `needs_review` (D2) through `WorkerResult.detail` and the coverage row's `review_flags` (append `"committee_roles_uninferred"` when > 0 — projection data only, **no UI gate**, per annotations 10/12).
- [ ] **Step 3: Run → PASS. Commit** — `feat(committee): honest needs-review accounting; roleless members remain visible`

### Task D5: slice acceptance test

**Files:**
- Test: `tests/api/test_committee_agent_inference_acceptance_db.py` (new)

- [ ] **Step 1:** one DB acceptance flow with Sumble doubles: comprehensive account run (Slice B path) → committee discovery (deferred mode) → agent inference tool → coverage row `committee_status='complete'`, members + roles in the contacts read, zero HUMAN-method role claims, lineage intact (`organization_identity_ref` present on the request row, run-lineage stamped). Run → PASS.
- [ ] **Step 2: Commit** — `test(api): committee discovery + agent role inference end to end (contract §11-D exit)`

**Slice D exit gate:** `make check` green; founder browser test: request committee research on a researched account; members appear under the account with roles, confidence and reasoning visible where the existing UI already shows them; DB spot-check shows `llm_synthesis` provenance on role claims.

---

# Slice E — contact launch reachability

Contract §11-E + §6: complete the explicit selected-contact approval/launch path; add account-tagged committee expansion into an exact immutable contact set; remove LinkedIn as the single eligibility prerequisite.

**Current truth (recon):** `approve_contact_research_selection@2` exists with `require_human_authority` preconditions (`platform/api/clue_api/entity_research_launch_tools.py:558-596`) but is granted to nobody (`C6_AGENT_TOOL_AUTHORITY["approve_contact_research_selection"] = ()`, `agent_registry_wiring.py:53-56`) and is not in `_HUMAN_ONLY_TOOLS` (`:347-361`) — so no UI/controller path can mint the selection receipt that `launch_contact_research@1` requires (audit gap #12). The repo already has the exact precedent to fix this: `LaunchSelectedAccountResearchTool` (`entity_research_launch_tools.py:127-390`) — a HEAD_OF_ABM-granted tool whose `source_turn_ref` is a `TRUSTED_TURN_FIELD` the engine matches against `ctx.action_ref` (`:189-193`), letting the server re-derive the *exact* user-selected set from the turn's durable `context_refs` (validated at submission by `validated_context_refs`, `platform/api/clue_api/chat/composer_context.py:106-217`, and persisted with the submission). The user's authenticated turn **is** the human authority (§6.1 step 3).

### Task E1: shared supported-identity predicate — LinkedIn becomes one binding among several

**Files:**
- Create: `platform/api/clue_api/contact_identity_support.py`
- Modify (call sites, replacing LinkedIn-only checks):
  - `platform/api/clue_api/contact_research_selection.py:276` (`or not contact.linkedin_url`)
  - `platform/api/clue_api/contact_research_fleet_launch.py:477` (extend the `linkedin_url or verified_email` pair)
  - `platform/api/clue_api/contact_entity_research.py:182` (identity-lock eligibility) and `:237` (anchor recording gains a `sumble_person_anchor` arm)
  - `platform/api/clue_api/frontend_read/contacts.py:684` + `platform/api/clue_api/frontend_read/bulk_actions.py:710` (email-lookup targets)
  - `platform/api/clue_api/exa_contact_compiler.py:515` (target lock accepts name + employer + strong non-LinkedIn identity; `canonical_profile_url` at `:380` stays optional-empty)
- Test: `tests/api/test_contact_identity_support.py`

**Interfaces:**

```python
async def contact_supported_identity(
    conn: AsyncConnection, *, workspace_id: str, contact_entity_id: UUID
) -> SupportedIdentity | None:
    """Contract §6.3: a contact is launch-eligible when ANY holds —
    canonical linkedin_url; canonical verified_email; a STRONG-bound
    identity claim (e.g. core.discovery_provenance from sumble_people
    with its organization lineage); or a STRONG account/contact binding
    claim accepted by the identity service. None == not eligible."""
```

`SupportedIdentity` is a frozen dataclass `{kind: Literal["linkedin","verified_email","sumble_person","strong_binding"], anchor_ref: str}` — the anchor feeds the identity lock so replay stays exact.

- [ ] **Step 1: Failing tests** — four fixtures, one per binding kind, each with `linkedin_url=None` except the first; assert eligibility for all four and `None` for a contact with only a weak name alias. Then per call site: the previously-refusing path now admits the `verified_email`-only and `sumble_person`-only contacts (e.g. the automatic materializer test from `tests/contact_research/test_c6_contact_selection_db.py` seeding, and an email-lookup target build from `tests/api/test_frontend_contact_email_lookup_db.py` seeding).
- [ ] **Step 2: Implement the predicate** (identity columns first — `subsystems/research/clue_research/identity/entities.py` strong keys; then one claims query for STRONG-bound `core.discovery_provenance`/binding claims), then mechanically replace each call site. At the Exa compiler, keep the fail-closed same-name behavior: without a profile URL the compiled request must carry name + canonical employer, and the parser's same-name rejection stays authoritative.
- [ ] **Step 3:** run the touched suites (`tests/contact_research/`, `tests/api/test_contact_research_fleet_launch_r7_db.py`, `tests/api/test_frontend_contact_email_lookup*.py`, `tests/contact_research/test_c3_exa_contact_compiler.py`) → PASS.
- [ ] **Step 4: Commit** — `feat(contacts): supported-identity predicate replaces every LinkedIn-only eligibility gate (contract §6.3)`

### Task E2: `launch_selected_contact_research@1` — the reachable explicit journey

**Files:**
- Modify: `platform/api/clue_api/entity_research_launch_tools.py` (new tool beside `LaunchSelectedAccountResearchTool`), `platform/api/clue_api/agent_registry_wiring.py` (grant `(AgentRole.HEAD_OF_ABM,)`), profile v37 → **v38** (new tool row + schema shas), `platform/api/clue_api/chat/composer_context.py:41` pin
- Test: `tests/api/test_launch_selected_contact_research_db.py` (new)

**Interfaces:**

```python
class LaunchSelectedContactResearchInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_turn_ref: str = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})
    expansion: Literal["explicit_contacts", "account_committee"] = "explicit_contacts"
    account_entity_id: str | None = None   # required iff expansion == "account_committee"
```

Behavior (mirroring `LaunchSelectedAccountResearchTool` clause by clause):
1. refuse unless `ctx.action_ref == inputs.source_turn_ref` (trusted-turn equality, `:189-193` pattern);
2. refuse when `settings.budget_controls_enabled` (this path is the budget-off pilot journey, `:184-188` pattern);
3. `explicit_contacts`: re-read the turn's durable `context_refs`; the exact selected contact ids (each already validated to belong to a selected account at submission — `composer_context.py:213-217`) become the frozen target set; refuse an empty set;
4. `account_committee`: resolve the tagged account's **current governed committee snapshot** via the R11.5 chain (`default_claim_reference_source()` → `committee_member_ids`, `platform/api/clue_api/contact_eligibility.py:279-288`), refuse when no committee exists (honest miss, no fallback);
5. filter the set through `contact_supported_identity` (E1) — refuse only when *zero* contacts qualify, listing the ineligible ids in the typed rejection detail;
6. build the `ContactResearchSelection` receipt for the exact set (fields per the active policy pin — Slice F raises the defaults; until then the receipt honestly reflects the current pin), persist with approval `approved_by = ctx` human principal (the turn's authenticated user id) and `approved_at = turn submission time` via `store_contact_research_selection(conn, selection, account_run_id=..., approval=...)` — **this is the human-authority receipt**: the user's own selected set + user-authored request, recorded server-side, per §6.1 step 3 ("the frontend/controller records the user's action as the human authority"). `approve_contact_research_selection@2` remains ungranted and untouched;
7. launch via the existing contact fleet launcher under the same `source_action_ref` (one user-visible task).

- [ ] **Step 1: Failing DB tests** — (a) explicit journey: seed a turn with two selected contacts in `context_refs`; tool invocation with the matching `source_turn_ref` creates one selection receipt whose `targets` are exactly those two contacts, an approval row carrying the human user id, and contact jobs; (b) a forged `source_turn_ref` ≠ `ctx.action_ref` is refused before any write; (c) replay with the same operation id is idempotent (no second receipt/run); (d) a contact the user never selected can never enter the receipt (assert exact-set equality — §12 row 4's "no unrequested contacts").
- [ ] **Step 2: Implement; grant; promote profile v38** (single version bump carrying both B4's v37 content and this row if slices land in order — adjust to "next free version" at implementation time and update both pins).
- [ ] **Step 3: Run** — new file + `tests/api/test_agent_registry_wiring.py` + authority audit → PASS.
- [ ] **Step 4: Commit** — `feat(contacts): trusted-turn selected-contact launch — explicit journey reaches a durable human-authority receipt (contract §6.1)`

### Task E3: account-tagged committee expansion

**Files:**
- Test: `tests/api/test_launch_selected_contact_research_db.py` (append)
- (Implementation landed inside E2's tool — this task proves the second journey and its edge cases.)

- [ ] **Step 1: Failing tests** — (a) seed an account with an M8D committee (D5 fixtures): `expansion="account_committee"` freezes exactly the current `committee_member_ids` (minus identity-ineligible ones, which are listed in the receipt's rejection detail) into the receipt; (b) a later committee change does **not** mutate the frozen receipt (immutability — assert receipt equality after inserting a new member and re-reading); (c) an account with no committee coverage refuses with a typed "no governed committee snapshot" rejection (honest miss, §5.1); (d) the account ref must appear in the turn's `context_refs` (a tagged account, not an arbitrary id).
- [ ] **Step 2: Run → PASS. Commit** — `feat(contacts): account-tagged committee expansion into an exact immutable selection receipt (contract §6.2)`

### Task E4: steering + skill so the agent completes the journeys

**Files:**
- Modify: the head-of-abm steering skill that owns contact research (locate the active skill naming `launch_contact_research`; extend or add a section) → new skill version; profile bump if the skill pin changes
- Test: scripted-conversation gate in `tests/agents/test_o3_account_deep_behavior.py` style (append one scenario)

- [ ] **Step 1:** skill text: *"when the user has attached specific contacts and asks for research, call `launch_selected_contact_research` with `expansion='explicit_contacts'` in the same turn; when the user tags an account and asks for its buying committee to be researched, use `expansion='account_committee'`; never ask the user to re-select members individually; never invoke `launch_contact_research` without a durable selection receipt."*
- [ ] **Step 2:** scripted test: a turn with attached contacts + "research these" reaches the tool with the right expansion (fake model scripted like the existing O3 gates).
- [ ] **Step 3: Commit** — `feat(agents): steering for both contact-research journeys`

**Slice E exit gate:** `make check` green; founder browser test: (1) select two contacts → Add to chat → "research these contacts" → research starts, receipt visible in DB with the founder's user id as approver; (2) tag an account → "research this account's buying committee" → exact current members frozen and launched; (3) a contact with no LinkedIn but a Sumble identity launches.

---

# Slice F — comprehensive contact execution and progress

Contract §11-F + §7 + §8: correct the Sumble-vs-Exa provider-slot routing; run all 15 fields across the exact selected set with internal batching; enable real contact-channel lookup; add contact/channel progress to the live task projection.

**Current truth (recon):** production wires **both** contact slots to the same Exa-only builder — `RunScopedContactResearchProviderActions(deep=contacts.build, enrichment=contacts.build)` (`entity_research_provider_wiring.py:630-634`) — while the runtime authority check makes `enrich_contact` with Exa sources structurally impossible (`contact_entity_research.py:1073-1076`: deep must be exactly `{exa_deep}`, enrichment must exclude `exa_deep`). So structured enrichment is currently *unreachable*, not merely misrouted (audit gap #14). The policy already names the split (`professional_source_plan = ("sumble_people","sumble_teams")`, `personal_facet_source_plan = ("exa_deep",)` — `libs/clue-core/clue_core/contact_research.py:100-101`), and a reuse-first Sumble adapter exists in the *preparation* seam (`ExistingCommitteeContactAdapter`, `platform/api/clue_api/contact_research_preparation.py:339-460`) but was never given a fleet action.

### Task F1: `SumbleContactSemanticEnrichmentAction` — the real structured slot

**Files:**
- Modify: `platform/api/clue_api/sumble_entity_research_tools.py` (new action class beside `SumbleAccountSemanticEnrichmentAction:377`)
- Test: `tests/api/test_sumble_contact_enrichment_action_db.py` (new)

Behavior, per job invocation of `enrich_contact` with professional field keys:
1. **Reuse first** — professional claims already written by committee discovery (`_write_professional_fact` output: STRONG binding, `ExtractionMethod.API`, sourced from People) satisfy their fields with zero spend (the `ExistingCommitteeContactAdapter` logic, lifted to run against the job's field set);
2. remaining fields → one Sumble People exact-person acquisition through the existing coordinator/transport machinery (`SumbleV9CommitteeClient`; person resolved via the stored strong identity — LinkedIn, email match via `people_email_match_request` (`resolvers/sumble/people.py:262`), or the durable Sumble person lineage from discovery — never a fuzzy name-only match);
3. normalize → write the six professional field claims (`contact.current_title`, `contact.job_function`, `contact.job_level`, `contact.team_membership`, `contact.current_location`, `contact.organization_relationship`) with STRONG binding + provider-returned provenance + snapshot/operation lineage (the M8C C1 lineage trigger applies — stamp `record_run_lineage`);
4. an unresolvable person or absent payload key → honest `unresolved` with a reason, never a fabricated value; no contact reveals (`assert_no_team_contact_reveals` stays in force).

- [ ] **Step 1: Failing tests** — (a) reuse: a contact with existing committee-written title/function claims settles those fields with zero transport calls (counting fake transport); (b) acquisition: missing `contact.current_location` resolves via a recorded People fixture into a STRONG/API claim with exact lineage refs; (c) no-match → all remaining fields unresolved with `person_not_resolved`; (d) claims idempotent on `(contact, field, run)`.
- [ ] **Step 2: Implement the action** (compose from the existing coordinator + normalizers; no new provider surface).
- [ ] **Step 3: Run → PASS. Commit** — `feat(sumble): structured contact enrichment action — reuse-first People/Teams professional facts`

### Task F2: route the slots correctly

**Files:**
- Modify: `platform/api/clue_api/entity_research_provider_wiring.py` (new `ProductionSumbleContactEnrichmentProviderActions` builder mirroring the Exa one at `:431`; flag gate `sumble_account_gap_enrichment_enabled`-style: requires `sumble_committee_acquisition_enabled`-independent People access → gate on `settings.sumble_account_gap_enrichment_enabled is irrelevant here` — gate on the Sumble key + a fields check; fail-visible `EntityResearchProductionCompositionError` when structured fields are selected and the key is missing), and the composition at `:630-634`:

```python
    contact_providers = RunScopedContactResearchProviderActions(
        deep=contacts.build,               # Exa Deep — the nine contact.facet.* fields
        enrichment=sumble_contacts.build,  # Sumble Teams/People — the six professional fields
        conn_factory=conn_factory,
    )
```

- Test: `tests/api/test_entity_research_cutover_r10.py` (append routing assertions)

- [ ] **Step 1: Failing test** — resolve bindings for a contact job selecting both field families: `research_contact_deep` binds an Exa action, `enrich_contact` binds the Sumble action (assert on class identity), and the runtime authority check (`contact_entity_research.py:1073-1076`) passes for both tool calls — the previously-impossible `enrich_contact` invocation now executes.
- [ ] **Step 2: Implement; run; commit** — `fix(wiring): enrich_contact routes to Sumble Teams/People, research_contact_deep stays Exa (contract §7.1, audit gap 14)`

### Task F3: 15-field comprehensive selection without truncation

**Files:**
- Modify: `libs/clue-core/clue_core/contact_research.py:96-97` (`max_selected_contacts` default 3 → 20 — the model ceiling; `max_fields_per_contact` default 8 → 15), `platform/api/clue_api/contact_research_selection.py:290-295` (field election: professional fields are elected by *ownership*, not by claims-already-exist, now that F2 makes them acquirable) and the E2 tool's target builder (all 15 fields, source authority per `CONTACT_STRUCTURED_FIELDS`/`CONTACT_DEEP_FIELDS` + the policy source plans)
- Test: `tests/contact_research/test_c0_contracts.py` (pin the new defaults), `tests/api/test_launch_selected_contact_research_db.py` (append)

- [ ] **Step 1: Failing tests** — (a) the E2 receipt for one contact carries exactly 15 `field_keys` with `field_source_authority` splitting 6→`sumble_people`/`sumble_teams`, 9→`exa_deep`; (b) a professional field with no existing claim is **included** (the old claims-must-exist election excluded it); (c) policy pin defaults freeze at 20/15.
- [ ] **Step 2: Implement; run the whole `tests/contact_research/` suite (policy-pin shas change — update the frozen fixtures deliberately, citing the contract).**
- [ ] **Step 3: Commit** — `feat(contacts): 15-field comprehensive contact profile is the normal request (contract §7.1)`

### Task F4: internal batching behind one user task

**Files:**
- Modify: `platform/api/clue_api/entity_research_launch_tools.py` (E2 tool: partition targets into receipts of ≤ `max_selected_contacts`, launched under one shared `source_action_ref`)
- Modify: `platform/projections/clue_projections/thread_research_tasks.py` (C2 projection: aggregate runs sharing a `source_action_ref` into **one** task wire — counts summed, revision = max)
- Test: `tests/api/test_launch_selected_contact_research_db.py` (append), `tests/api/test_thread_research_tasks_db.py` (append)

- [ ] **Step 1: Failing tests** — 27 selected contacts → 2 receipts (20 + 7), 27 contact jobs total, all sharing the turn's `source_action_ref`; the C2 route returns **one** task with `counts.total == 27`; replay creates nothing new.
- [ ] **Step 2: Implement partition + aggregation. Run → PASS.**
- [ ] **Step 3: Commit** — `feat(contacts): bounded internal batches behind one durable user task (contract §7.1)`

### Task F5: real contact channels — product-default email lookup + honest observed states

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (`INTEGRATION_PILOT_OVERLAY` gains `"contact_channel_enrichment_enabled": True, "frontend_contact_email_lookup_enabled": True`), `platform/api/clue_api/product_path_preflight.py` (`_REQUIREMENTS` gains the email-lookup rows: both keys required when the lookup flag is on)
- Modify: `platform/api/clue_api/entity_research_provider_wiring.py:546-548` — the channel-enrichment composition binds the **real** reveal adapters (Sumble People email-match + Exa Websets — the two `ContactEmailLookupService` providers, reused) with the channel state machine capped at `OBSERVED`: `ContactChannelValidation` rows record `reachability=NOT_CHECKED`, `identity_corroboration` as actually computed, and `delivery_eligible` stays `False` (its rule already requires VALIDATED/VERIFIED — `contact_research.py:381-392`)
- Test: `tests/contact_research/test_c5_contact_channel_enrichment.py` (append), `tests/test_config_settings.py` (overlay assertions flip), `tests/integration/test_r11_lane_f_acceptance.py:707` (update: the *default* path still asserts off; add a pilot-path assertion)

**Recorded design decision (founder attention flag — §8/§9 tension):** the permitted provider set (§2.1) contains **no independent deliverability validator**, and the fail-closed authorization model refuses an `allowed=True` reveal without a disjoint validation source (`contact_research.py:414-437`). We therefore enable channels in **observed-only mode**: real adapters, durable provider-observed values labeled exactly `OBSERVED`/unverified, never promoted (`promote_contact_verified_email` untouched), never `delivery_eligible`. This implements §8's bullets ("honest about observed…"; "missing strict validation must not silently turn a real observed address into fake verified data") without fabricating validation. Buying a commercial validator later slots into the existing `channel_validator` seam (`sources/seeds.py:135-146`) with no rework. The §9 row "On with a concrete validator/provider binding" is satisfied by the concrete *provider* binding; the concrete *validator* remains an explicit, named deferral for the founder to ratify.

- [ ] **Step 1: Failing tests** — (a) pilot overlay resolves both channel flags on and preflight demands both provider keys; (b) channel enrichment with the real-adapter binding stores an observed email with `ContactChannelState.OBSERVED`, `reachability=NOT_CHECKED`, `delivery_eligible is False`; (c) no code path writes `VALIDATED`/`VERIFIED_IDENTITY` (grep-tripwire test over the new module: the enum members are only ever *read*); (d) with a provider double returning nothing → honest `unavailable`, no mock value.
- [ ] **Step 2: Implement; email lookup reachability from both journeys is already the existing UI** (per-contact button + bulk action, `frontend_read/contacts.py:704,733`, `bulk_actions.py:604`) — now eligible for non-LinkedIn contacts via E1; verify with one appended endpoint test.
- [ ] **Step 3: Run → PASS. Commit** — `feat(channels): product-default real email lookup; channel enrichment in honest observed-only mode (contract §8)`

### Task F6: contact and channel progress on the live task

**Files:**
- Modify: `platform/projections/clue_projections/gates.py:166` (`_LAUNCHES_SQL` gains the `entity_research_contact_launch` union — today gates only see account fleets), `platform/projections/clue_projections/thread_research_tasks.py` (contact tasks: `fieldProgress` from contact jobs' coverage; `channelLookups: {pending, settled} | null` from `contact_email_lookup` rows keyed to the launch's contacts)
- Modify: `apps/frontend/src/features/projects/model/research-task.ts` (+ wire schema) — contact tasks reuse the same designed card verbatim (subject-count copy exactly as the dummy frontend renders it); channel-lookup state rides **only** the existing designed email-lookup UI on contact rows — `channelLookups` and `fieldProgress` stay API-only data with no card slot, no new component, and no source/date captions (visual-parity rule)
- Test: `tests/api/test_thread_research_tasks_db.py` (append), frontend model tests

- [ ] **Step 1: Failing tests** — a contact launch appears in the thread task read with truthful per-contact counts advancing across job transitions; the gates read now reports the launch (audit's `_LAUNCHES_SQL` omission closed); email-lookup rows in flight reflect in `channelLookups.pending`.
- [ ] **Step 2: Implement; run backend + frontend gates. Commit** — `feat(progress): contact-by-contact and channel-lookup progress on the durable task read (contract §4)`

### Task F7: slice acceptance test

- [ ] **Step 1:** `tests/api/test_comprehensive_contact_execution_db.py` — E2 explicit launch of 2 contacts → drive jobs with Sumble + Exa doubles → assert: all 15 fields per contact settled attempted/satisfied; 6 professional fields carry Sumble lineage, 9 facets carry Exa lineage; observed email stored honestly; task read reaches terminal truthful counts. Run → PASS.
- [ ] **Step 2: Commit** — `test(api): comprehensive contact execution end to end (contract §11-F exit)`

**Slice F exit gate:** backend + frontend gates green; founder browser test: select contacts → research → watch per-contact progress; profiles fill with structured + deep facts; email lookup returns a real observed (unverified-labeled) address.

---

# Slice G — frontend reads, handoff, and real-provider acceptance

Contract §11-G + §12: enable C7 reads and production handoff; render account/committee/contact/channel results in existing surfaces; run paid provider canaries and capture browser → API → provider → database evidence.

### Task G1: activate the read/handoff flags in the overlay

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (`INTEGRATION_PILOT_OVERLAY` gains `"c7_research_view_read_enabled": True, "c7_snapshot_compose_enabled": True, "c7_production_handoff_enabled": True`), `tests/test_config_settings.py` (flip the phased assertions from A1)
- Test: `tests/api/test_c7_activation.py` (existing default-off freeze stays; append a pilot-path composition test)

- [ ] **Step 1:** flip overlay + tests; boot-path proof: `projections_app.py:930-948` wiring guard passes with the flags on (components compose — `tests/api/test_c7_production_readers.py` patterns); handoff composition (`run_composition.py:581,620`) composes without raising.
- [ ] **Step 2: Run → PASS. Commit** — `feat(config): integration-pilot overlay completes contract §9 — C7 reads, snapshot compose, production handoff`

### Task G2: render-path verification + the one latent composition defect

**Files:**
- Modify: `libs/clue-core/clue_core/research_view.py:334-335` (the [C7×core] backlog defect: a plain `contact.*` claim born `identity_binding=NULL` with a `use_class` fails `ResearchStatement` validation and 404s the whole contact view; fix = drop the non-displayable statement, never fail composition)
- Test: `tests/` C7 serving suite (the repro recorded in `_memory/2026-08-09-lane-e-e2-complete.md`)

- [ ] **Step 1: Failing test from the recorded repro** — insert the mixed-pair claim; compose the contact view; expect a served view without the statement (today: composition failure).
- [ ] **Step 2: Implement the statement-drop; run the C7 suites → PASS.** (In scope because Slice F's Sumble enrichment increases plain-`contact.*` claim traffic; every *our* writer stamps both fields, but the serving surface must not be one hand-written claim away from a 404 during founder acceptance.)
- [ ] **Step 3:** verify each §12 journey's read path against existing frontend surfaces with DB-seeded state (accounts list/detail, contacts + roles, channel states, C7 research views, handoff read) — one integration test per journey where a gap exists, none where FI-2 suites already cover it.
- [ ] **Step 3b: visual-parity audit (first-priority rule).** Side-by-side comparison of the **contact research details, buying-committee details, and contact details pages** against the dummy frontend at `/Users/aryankeshri/conductor/repos/clue-frontend/`: with real researched data flowing, the rendered pages must show exactly the fields, layout, and copy the dummy build shows — no extra fields surfaced from the richer backend payload, no source/date captions added under connected fields, no new components. Every backend field with no designed slot is inventoried in the acceptance note as API-served/not-displayed (a founder wire/hide/design-request ruling list), never wired unilaterally.
- [ ] **Step 4: Commit** — `fix(c7): a non-displayable statement is dropped, never a composed-view failure`

### Task G3: paid canaries + the browser acceptance matrix

**Files:**
- Create: `_memory/2026-XX-XX-comprehensive-research-browser-acceptance.md` (dated at execution)

- [ ] **Step 1:** stand up the isolated acceptance runtime per the recorded conventions (`_memory/2026-08-16-combined-browser-acceptance.md`): fresh named DB `clue_comprehensive_<YYYYMMDD>_<seq>`, separate artifact/agent-workspace roots, `CLUE_PRODUCT_PATH=integration_pilot`, real keys in the local ignored `.env` only.
- [ ] **Step 2:** execute the §12 matrix — all seven journeys (full account profile; committee discovery; explicit contact research; account-tagged committee research; contact channels incl. **one paid successful email-lookup canary**; live progress; C7 + handoff). For each: browser evidence, exact API/event evidence, provider evidence (literal HTTP status lines + reconciled units/cents), durable DB rows — quoted verbatim ids, seed-state vs journey-created state distinguished, zero secrets in the note.
- [ ] **Step 3:** any journey that fails stops the slice at that boundary: record the defect, fix, re-run that journey. The founder performs the manual pass; the agent drives inspection of API/provider/DB in parallel.
- [ ] **Step 4: Commit** — `docs(memory): comprehensive research browser acceptance — §12 matrix evidence`

### Task G4: definition-of-done audit

- [ ] **Step 1:** walk contract §14's eleven bullets against the delivered state; for each, cite the proving test or acceptance evidence line. Confirm §10: none of the deferred providers/planners/gates/UI crept in (Task A4 tripwires + a manual diff review of `entity_research_provider_wiring.py`, `sources/seeds.py`).
- [ ] **Step 2:** append the audit table to the acceptance memory note; update `docs/FI-comprehensive-account-contact-research-contract.md` status line from "implementation pending" to the dated done/partial state. Commit — `docs: contract §14 definition-of-done audit`

**Slice G exit gate:** the §14 checklist fully cited; founder sign-off on the acceptance note.

---

# Decision ledger — ratified by the founder, 2026-08-18

The four interpretation calls this plan flagged were put to the founder and ruled on; they are now binding.

1. **A: activation mechanism — RATIFIED.** `CLUE_PRODUCT_PATH=integration_pilot` overlay (checked-in defaults, per-flag env still wins) rather than flipping global `Settings` defaults or a tracked env file; keeps every conservative-deployment default and its frozen tests intact while making activation a one-variable, checked-in fact. Flags whose composition raises before their owning slice (channels → F; C7 → G) join the overlay in that slice, not in A.
2. **D: role inference moves into the account agent — RATIFIED.** `agent_deferred` discovery + `record_committee_role_inferences`, per the literal §5.2 flow. D1 (false-HUMAN provenance fix) still lands first and independently.
3. **D/§5.2: ungrounded candidates carry no role claim — RATIFIED.** Founder: not every contact needs to display a role claim. Members stay visible through their discovery claims; roles stay honestly empty; no always-promotable fallback and no display-layer substitute.
4. **F: channels run observed-only — RATIFIED.** Founder's wording, binding: *"We can find and display a real provider-returned email now, clearly marked unverified. We cannot call it validated, promote it as identity truth, or authorize it for delivery until an independent validator is added."* Real adapters, states capped at `OBSERVED`, `promote_contact_verified_email` untouched, nothing `delivery_eligible`; the paid §8 canary is the real Sumble/Exa email lookup; a purchased validator later drops into the existing `channel_validator` seam with no rework.
5. **Frontend visual parity — NEW BINDING RULE (founder, 2026-08-18), first priority.** See the Global Constraints entry: strict visual parity with the dummy frontend at `/Users/aryankeshri/conductor/repos/clue-frontend/`, strongest on the contact research details, buying-committee details, and contact details pages. Backend serves every researched field; frontend wires only the fields the designed components already display; no new components/fields/visualizations, no source/date captions under newly connected fields; every proposed visual addition is asked of the founder before being added.

6. **Chat pagination defect — RATIFIED into scope (founder, 2026-08-18).** The audit's chat-loading defect (oldest-50 initial page, cursor never consumed) is fixed alongside Slice C as **Task C5**: newest-first initial load landing at the bottom, upward keyset-cursor scrollback prepending older pages, durable/optimistic/streamed dedupe by message/turn identity. No new UI components — behavior only, under the visual-parity rule.

7. **Explicit Account research is not tier-gated — RATIFIED (founder, 2026-08-19).** Fit/intent and numeric `high` / `low` tiers remain prioritization metadata. An attributable user turn that explicitly selects an Account, together with the directive's exact Account scope, authorizes account research and buying-committee discovery whether the signal tier is high, low, or absent. A directive execution tier such as `standard` is a separate effort vocabulary and never has to equal the signal tier. Budget accounting, privacy policy, provider availability, exact scope, and durable authority receipts remain enforced.

# Slice-completion protocol (applies to every slice)

1. All slice tasks committed; `make check` green; `make db-smoke` green when a migration landed; frontend gate green when `apps/frontend` changed.
2. A short `_memory/` session note: what landed, decisions, deviations, failures observed.
3. Founder manual browser test of the slice's exit-gate journey.
4. Only after founder acceptance does the next slice start (contract §11's hard rule).
