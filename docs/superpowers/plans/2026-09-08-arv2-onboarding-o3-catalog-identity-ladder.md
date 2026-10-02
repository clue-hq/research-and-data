# ARV2 Onboarding O3 follow-up — Catalog Identity Ladder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A re-run of onboarding never mints a second product row (and therefore a second research document) for an offering the brand already has, unless a person or a high-confidence, evidence-backed decision says it is genuinely new.

**Architecture:** The catalog synchronizer resolves each lineup entry through a four-stage ladder: fingerprint replay (exists) → exact spelling key on name and aliases (exists) → one batched model reconciliation per run for the leftovers, with each entry's official page URL as evidence and automatic merge only at high confidence → alias write-back on every match so the catalog converges. The reconciler is a lane-owned OpenRouter call through R1's `ProviderCaller` (ledger row, raw record), injected into the driver at composition behind a flag. The lineup request to Exa gains one system-prompt sentence and two schema descriptions (validated in the playground 2026-09-08). Everything decided by the model is recorded on the lineage row with its confidence and reason, so the product-set gate (O6) can show and undo it.

**Tech Stack:** Python 3.12, SQLAlchemy async `text()` SQL, Alembic, R1 `clue_api.arv2` clients (`ProviderCaller`, `openrouter_chat_request`), pydantic, pytest with `rollback_conn`.

**Spec:** `docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` §3 (the Exa schema), §5 (synchronizer), §10 (standing rule); `docs/specs/ARV2-ONBOARDING-PLAN.md` §4.1; founder rulings 2026-09-08 recorded in `_memory/2026-09-07-arv2-onboarding-o3-fleet-driver.md` (addenda) and the proof of concept in this plan's §"Evidence". Facts file: none — every signature is quoted inline below.

## Evidence (why this shape)

Four live runs on one workspace grew the product rows 19 → 28 through name drift (`Referrals AI Agent` / `Referral Management AI Agent` on one page; `Aura™ AI Scribe`; `AI FrontDesk Agent` cited to the homepage). A proof of concept over the four stored catalogs (`/tmp/o3-dedupe-poc/`, 2026-09-08) showed: exact spelling alone merges only the mark/spacing cases; a model given the page URLs as evidence merges every drift pair and keeps the two genuinely new offerings, identically on `openai/gpt-5-mini` and `x-ai/grok-4.6` (28 → 18 rows, no wrong merge); the one wrong merge seen (a partner program) disappeared once the prompt stated what page evidence means. The playground trial of the reworded Exa prompt listed each page exactly once within a call, but names still drift *between* calls (page title vs heading), so the model stage stays necessary. Founder rulings: no generic-token stoplist (a one-company heuristic); a shared page is evidence, never an automatic key (many sites present several products on one page); automatic merge only for deterministic stages and high-confidence model decisions; everything else is created and flagged for the gate.

## Global Constraints

- **Standing rule (catalog contract §10):** no Client-KB version, readiness decision or Stage-0 pin anywhere on this path.
- **Import guard:** `clue_api.arv2` imports only `clue_*` libs and `clue_research.claimstore`; the reconciler lives in `clue_api/arv2/onboarding_reconcile.py` and uses the lane's own OpenRouter request builders (`clue_api/arv2/openrouter.py`) through `ProviderCaller` — never `clue_gateway` and never a provider SDK.
- **Money:** every reconciler call is one `ProviderCaller.call` with a `SpendEstimate`, a raw record and a ledger row (R1 law 1); one call per onboarding run, batched; the estimate is `Decimal("0.01")`. No live test in the suite; the live proof is Task 6 (founder-triggered).
- **Fingerprints are frozen.** `_fingerprint` hashes `name`, `short_description`, `aliases`, `POLICY_VERSION` — do NOT add `official_url` to it; existing lineage rows must keep replaying.
- **Automatic merge only** for: fingerprint replay, exact spelling key, and model decisions with `confidence == "high"`. Medium/low "same" decisions CREATE the row and record `model_unsure` with the suggested product and reason. Never rename, merge or archive a product row.
- **Alias write-back never renames:** `add_product_aliases` appends to `product.aliases`, deduplicated by the spelling key, never touches `name`.
- **No stoplist.** `normalize_identity` keeps every word (founder ruling).
- **Alembic:** hash id off the single head `a3602967bb73` (after the R2 merge, 2026-09-08); reversible; smoke on the throwaway `clue_o4_agent` only (`uv run alembic downgrade a3602967bb73 && upgrade head` after applying).
- **Tests:** offline suites via `uv run pytest tests/arv2 --ignore-glob='*_live.py'`; DB tests on `clue_o4_agent`; never `make check` or a broad pytest with keys in `.env`.
- **Commits:** local only, never push; no AI attribution; one commit per task with the message given.

---

## File Structure

| Path | Responsibility |
|---|---|
| `alembic/versions/<hash>_arv2_onboarding_lineage_reconcile.py` | **Create.** Widen the lineage state CHECK (`model_reused`, `model_unsure`); add `reconcile_confidence`, `reconcile_reason` columns. |
| `libs/clue-spine/clue_spine/spine.py` | **Modify.** `add_product_aliases(conn, *, product_id, workspace_id, aliases) -> Product`. |
| `libs/clue-config/clue_config/settings.py`, `.env.example` | **Modify.** `onboarding_catalog_reconcile_enabled`, `onboarding_reconcile_model`. |
| `platform/api/clue_api/arv2/onboarding_reconcile.py` | **Create.** `CatalogReconciler` protocol, `ReconcileDecision`, `ExistingProduct`, `OpenRouterCatalogReconciler`, `RECONCILE_SYSTEM_PROMPT`, `reconcile_output_schema()`. |
| `platform/api/clue_api/arv2/onboarding_lineage.py` | **Modify.** `CatalogProduct.official_url`; the ladder in `synchronize_catalog(..., reconciler=None)`; alias write-back; new `ProductLink` fields. |
| `platform/api/clue_api/arv2/onboarding_documents.py` | **Modify.** `product_catalog_document` keeps `official_url` per entry in the front matter (verify; it already does per the stored catalogs). |
| `platform/api/clue_api/arv2/onboarding_driver.py` | **Modify.** `LINEUP_SYSTEM_PROMPT` sentence; `reconciler` kwarg threaded into `_catalog_sync`; `CatalogProduct(official_url=...)` from the front matter. |
| `platform/api/clue_api/arv2/exa_client.py` | **Modify.** Two descriptions in `product_catalog_output_schema()`. |
| `docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` | **Modify.** §3 descriptions; §5 the ladder; §6 lineage states. |
| `platform/api/clue_api/fleet_main.py` | **Modify.** Compose `OpenRouterCatalogReconciler` behind the flag; pass to `_build_onboarding_handler`. |
| `platform/api/clue_api/arv2/README.md`, `_memory/…` | **Modify/Create.** |
| Tests | `tests/db/test_arv2_onboarding_lineage_reconcile_migration.py`, `tests/clue_spine/test_product_aliases_db.py`, `tests/arv2/test_onboarding_reconcile.py`, `tests/arv2/test_onboarding_lineage_db.py` (extend), `tests/arv2/test_onboarding_driver.py` (extend), `tests/arv2/test_onboarding_settings.py` (extend), `tests/api/test_fleet_wiring.py` (extend). |

---

### Task 1: Lineage states + reconcile columns (migration) and the alias writer (spine)

**Files:**
- Create: `alembic/versions/<hash>_arv2_onboarding_lineage_reconcile.py`
- Modify: `libs/clue-spine/clue_spine/spine.py`
- Test: `tests/db/test_arv2_onboarding_lineage_reconcile_migration.py`, `tests/clue_spine/test_product_aliases_db.py`

**Interfaces:**
- Produces: lineage `resolution_state` admits `'created' | 'alias_reused' | 'lineage_reused' | 'model_reused' | 'model_unsure'` (all with `product_id NOT NULL`) and `'unresolved_ambiguous'` (`product_id NULL`); nullable columns `reconcile_confidence text` (CHECK in `('high','medium','low')` or NULL) and `reconcile_reason text`. `add_product_aliases(conn, *, product_id: str, workspace_id: str, aliases: Sequence[str]) -> Product` — appends the aliases not already present (compared with `normalize_identity`-style folding: NFKC, casefold, alphanumerics only), keeps order, never touches `name`, returns the row; raises `ValueError` when the product is not in the workspace.

- [ ] **Step 1: Failing tests**

```python
# tests/db/test_arv2_onboarding_lineage_reconcile_migration.py
"""The lineage states the reconciler writes, and its confidence/reason columns (O3 identity ladder)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_db import db_lifespan

from .conftest import run_async


@pytest.mark.usefixtures("require_db")
def test_the_lineage_state_check_admits_the_model_states_and_the_reconcile_columns_exist() -> None:
    async def scenario() -> tuple[dict[str, str], set[str]]:
        async with db_lifespan() as engine, engine.connect() as conn:
            cons = await conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) AS d FROM pg_constraint "
                    "WHERE conrelid = 'onboarding_product_lineage'::regclass"
                )
            )
            cols = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'onboarding_product_lineage'"
                )
            )
            return {str(r.conname): str(r.d) for r in cons}, {str(r.column_name) for r in cols}

    constraints, columns = run_async(scenario())
    state = constraints["onboarding_product_lineage_state"]
    for s in ("created", "alias_reused", "lineage_reused", "model_reused", "model_unsure", "unresolved_ambiguous"):
        assert s in state
    assert {"reconcile_confidence", "reconcile_reason"} <= columns
    assert "'high'" in constraints["onboarding_product_lineage_reconcile_confidence"]
```

```python
# tests/clue_spine/test_product_aliases_db.py
"""`add_product_aliases`: append-only, folded-deduplicated, never renames."""

from __future__ import annotations

import pytest

from clue_spine import add_product_aliases, create_product, get_product
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_aliases_append_without_duplicates_and_the_name_never_moves() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-spine-aliases"
            project = await seed_project(conn, ws, name="aliases")
            product = await create_product(conn, brand_id=project.brand_id, workspace_id=ws, name="Aura AI Scribe", aliases=("Aura",))
            updated = await add_product_aliases(conn, product_id=product.product_id, workspace_id=ws, aliases=("Aura™ AI Scribe", "aura ai scribe", "Aura", "AI FrontDesk"))
            assert updated.name == "Aura AI Scribe"
            # "aura ai scribe" folds onto the name, "Aura" is already there → only two new aliases
            assert updated.aliases == ("Aura", "Aura™ AI Scribe", "AI FrontDesk")
            assert (await get_product(conn, product.product_id)).aliases == updated.aliases
            with pytest.raises(ValueError):
                await add_product_aliases(conn, product_id=product.product_id, workspace_id="ws-other", aliases=("x",))

    run_async(scenario())
```

(Adjust the expected tuple if you decide the name itself should also be excluded when it folds equal — the rule is: an alias is added only when its folded form matches neither the name nor an existing alias.)

- [ ] **Step 2: Run to verify failure** — `set -a; source .env; set +a` (worktree `.env` → `clue_o4_agent`) then `uv run pytest tests/db/test_arv2_onboarding_lineage_reconcile_migration.py tests/clue_spine/test_product_aliases_db.py -v` → FAIL (constraint text lacks the states; `ImportError: add_product_aliases`).

- [ ] **Step 3: Migration**

```bash
uv run alembic heads   # a3602967bb73
uv run alembic revision -m "arv2 onboarding lineage reconcile"
```

```python
def upgrade() -> None:
    op.execute("ALTER TABLE onboarding_product_lineage DROP CONSTRAINT onboarding_product_lineage_state")
    op.execute(
        """
        ALTER TABLE onboarding_product_lineage ADD CONSTRAINT onboarding_product_lineage_state CHECK (
            (resolution_state IN ('created', 'alias_reused', 'lineage_reused', 'model_reused', 'model_unsure')
                AND product_id IS NOT NULL)
            OR (resolution_state = 'unresolved_ambiguous' AND product_id IS NULL))
        """
    )
    op.execute("ALTER TABLE onboarding_product_lineage ADD COLUMN reconcile_confidence text")
    op.execute("ALTER TABLE onboarding_product_lineage ADD COLUMN reconcile_reason text")
    op.execute(
        "ALTER TABLE onboarding_product_lineage ADD CONSTRAINT onboarding_product_lineage_reconcile_confidence "
        "CHECK (reconcile_confidence IS NULL OR reconcile_confidence IN ('high', 'medium', 'low'))"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM onboarding_product_lineage WHERE resolution_state IN ('model_reused', 'model_unsure')) THEN
                RAISE EXCEPTION 'cannot downgrade the identity ladder while model-decided lineage rows exist';
            END IF;
        END $$
        """
    )
    op.execute("ALTER TABLE onboarding_product_lineage DROP CONSTRAINT onboarding_product_lineage_reconcile_confidence")
    op.execute("ALTER TABLE onboarding_product_lineage DROP COLUMN reconcile_reason")
    op.execute("ALTER TABLE onboarding_product_lineage DROP COLUMN reconcile_confidence")
    op.execute("ALTER TABLE onboarding_product_lineage DROP CONSTRAINT onboarding_product_lineage_state")
    op.execute(
        """
        ALTER TABLE onboarding_product_lineage ADD CONSTRAINT onboarding_product_lineage_state CHECK (
            (resolution_state IN ('created', 'alias_reused', 'lineage_reused') AND product_id IS NOT NULL)
            OR (resolution_state = 'unresolved_ambiguous' AND product_id IS NULL))
        """
    )
```

Note: the table's trigger is `BEFORE UPDATE` (append-only edits); `ALTER TABLE` is unaffected.

- [ ] **Step 4: Spine writer** (in `libs/clue-spine/clue_spine/spine.py`, next to `create_product`; export it in `clue_spine/__init__.py`)

```python
def _alias_fold(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", value.translate(_MARK_TABLE)).casefold() if ch.isalnum())


_MARK_TABLE = str.maketrans("", "", "™®©℠")


async def add_product_aliases(
    conn: AsyncConnection, *, product_id: str, workspace_id: str, aliases: Sequence[str]
) -> Product:
    """Append observed spellings to a product's aliases. Never renames; never duplicates a spelling
    that folds onto the name or an existing alias (marks, case, spacing and punctuation ignored)."""
    product = await get_product(conn, product_id)
    if product is None or product.workspace_id != workspace_id:
        raise ValueError("product is not in this workspace")
    seen = {_alias_fold(product.name)} | {_alias_fold(a) for a in product.aliases}
    merged = list(product.aliases)
    for alias in aliases:
        folded = _alias_fold(alias)
        if alias.strip() and folded and folded not in seen:
            merged.append(alias.strip())
            seen.add(folded)
    if merged != list(product.aliases):
        await conn.execute(
            text("UPDATE product SET aliases = CAST(:aliases AS jsonb) WHERE product_id = :id AND workspace_id = :ws"),
            {"aliases": serialize_value_json(merged), "id": product_id, "ws": workspace_id},
        )
    refreshed = await get_product(conn, product_id)
    assert refreshed is not None
    return refreshed
```

- [ ] **Step 5: Apply, run, smoke, commit**

`uv run alembic upgrade head && uv run alembic downgrade a3602967bb73 && uv run alembic upgrade head && uv run pytest tests/db/test_arv2_onboarding_lineage_reconcile_migration.py tests/clue_spine/test_product_aliases_db.py tests/db/test_arv2_onboarding_kind_migration.py -v && uv run ruff check libs/clue-spine alembic/versions tests/db tests/clue_spine && uv run mypy libs/clue-spine`

```bash
git add alembic/versions/*_arv2_onboarding_lineage_reconcile.py libs/clue-spine/clue_spine/spine.py libs/clue-spine/clue_spine/__init__.py tests/db/test_arv2_onboarding_lineage_reconcile_migration.py tests/clue_spine/test_product_aliases_db.py
git commit -m "feat(db,spine): onboarding lineage admits model_reused/model_unsure with reconcile confidence+reason; add_product_aliases appends observed spellings without renaming"
```

---

### Task 2: Settings, env parity, and the reconciler module (offline)

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (after `onboarding_persona_evidence_enabled`, line ~357), `.env.example` (after `CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED`, line ~160), local `.env` (parity)
- Create: `platform/api/clue_api/arv2/onboarding_reconcile.py`
- Test: `tests/arv2/test_onboarding_settings.py` (extend `ONBOARDING_SETTING_DEFAULTS`), `tests/arv2/test_onboarding_reconcile.py`

**Interfaces:**
- Settings: `onboarding_catalog_reconcile_enabled: bool = True` (env `CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED`), `onboarding_reconcile_model: str = "openai/gpt-5-mini"` (env `CLUE_ONBOARDING_RECONCILE_MODEL`).
- `ExistingProduct(product_id: str, name: str, aliases: tuple[str, ...], official_url: str | None, description: str)` (frozen dataclass).
- `ReconcileDecision(candidate: str, decision: Literal["same_as_existing","same_as_candidate","new_product"], product_id: str | None, candidate_name: str | None, confidence: Literal["high","medium","low"], reason: str)`.
- `class CatalogReconciler(Protocol)`: `async def reconcile(self, *, existing: Sequence[ExistingProduct], candidates: Sequence[CatalogProduct]) -> tuple[ReconcileDecision, ...]` — one decision per candidate, in order; NEVER raises (a failure returns every candidate as `new_product` / `low` / reason `reconciler_unavailable: <error>`).
- `OpenRouterCatalogReconciler(*, caller_factory: Callable[[], ProviderCaller], api_key: SecretStr, model: str, base_url: str, timeout_s: float = 120.0)`.
- `RECONCILE_SYSTEM_PROMPT`, `reconcile_output_schema() -> dict`.

- [ ] **Step 1: Failing tests**

```python
# tests/arv2/test_onboarding_reconcile.py
"""The catalog reconciler: fixed prompt + strict schema, decisions validated, never raises."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from pydantic import SecretStr

from clue_api.arv2.onboarding_lineage import CatalogProduct
from clue_api.arv2.onboarding_reconcile import (
    RECONCILE_SYSTEM_PROMPT,
    ExistingProduct,
    OpenRouterCatalogReconciler,
    reconcile_output_schema,
)

EXISTING = (
    ExistingProduct("prd_1", "Referrals AI Agent", (), "https://x.io/referral-management", "AI referral-management product."),
    ExistingProduct("prd_2", "Aura AI Scribe", ("Aura",), "https://x.io/ambient", "Ambient clinical documentation."),
)
CANDIDATES = (
    CatalogProduct(name="Referral Management AI Agent", short_description="Automates referral processing.", aliases=(), official_url="https://x.io/referral-management"),
    CatalogProduct(name="HEDIS AI Workflows", short_description="HEDIS screening coordination.", aliases=(), official_url="https://x.io/hedis"),
    CatalogProduct(name="Referral Mgmt Agent", short_description="Automates referral processing.", aliases=(), official_url=None),
)


def _answer(decisions: list[dict]) -> dict:
    return {"choices": [{"message": {"content": json.dumps({"decisions": decisions})}}],
            "usage": {"cost": 0.0012, "prompt_tokens": 900, "completion_tokens": 200}, "id": "gen_x"}


def test_the_request_carries_the_fixed_prompt_the_strict_schema_and_both_lists(make_caller, scripted_transport) -> None:
    transport = scripted_transport(status=200, body=_answer([
        {"candidate": "Referral Management AI Agent", "decision": "same_as_existing", "product_id": "prd_1", "candidate_name": None, "confidence": "high", "reason": "same page and job"},
        {"candidate": "HEDIS AI Workflows", "decision": "new_product", "product_id": None, "candidate_name": None, "confidence": "high", "reason": "distinct page"},
        {"candidate": "Referral Mgmt Agent", "decision": "same_as_candidate", "product_id": None, "candidate_name": "Referral Management AI Agent", "confidence": "medium", "reason": "same description"},
    ]))
    reconciler = OpenRouterCatalogReconciler(caller_factory=lambda: make_caller(transport), api_key=SecretStr("k"), model="openai/gpt-5-mini", base_url="https://openrouter.ai/api/v1")
    decisions = asyncio.run(reconciler.reconcile(existing=EXISTING, candidates=CANDIDATES))
    body = transport.requests[0].json_body
    assert body["model"] == "openai/gpt-5-mini" and body["temperature"] == 0
    assert body["messages"][0] == {"role": "system", "content": RECONCILE_SYSTEM_PROMPT}
    payload = json.loads(body["messages"][1]["content"])
    assert [p["product_id"] for p in payload["products_on_file"]] == ["prd_1", "prd_2"]
    assert [c["name"] for c in payload["candidates"]] == [c.name for c in CANDIDATES]
    assert body["response_format"]["json_schema"]["schema"] == reconcile_output_schema()
    assert [d.decision for d in decisions] == ["same_as_existing", "new_product", "same_as_candidate"]
    assert decisions[0].product_id == "prd_1" and decisions[2].candidate_name == "Referral Management AI Agent"


def test_an_invalid_reference_or_missing_candidate_degrades_to_new_low(make_caller, scripted_transport) -> None:
    transport = scripted_transport(status=200, body=_answer([
        {"candidate": "Referral Management AI Agent", "decision": "same_as_existing", "product_id": "prd_404", "candidate_name": None, "confidence": "high", "reason": "x"},
        # HEDIS omitted entirely; Referral Mgmt points at itself
        {"candidate": "Referral Mgmt Agent", "decision": "same_as_candidate", "product_id": None, "candidate_name": "Referral Mgmt Agent", "confidence": "high", "reason": "x"},
    ]))
    reconciler = OpenRouterCatalogReconciler(caller_factory=lambda: make_caller(transport), api_key=SecretStr("k"), model="m", base_url="https://o")
    decisions = asyncio.run(reconciler.reconcile(existing=EXISTING, candidates=CANDIDATES))
    assert [(d.candidate, d.decision, d.confidence) for d in decisions] == [
        ("Referral Management AI Agent", "new_product", "low"), ("HEDIS AI Workflows", "new_product", "low"), ("Referral Mgmt Agent", "new_product", "low")]
    assert all(d.reason.startswith("reconciler_invalid") for d in decisions)


def test_a_provider_failure_never_raises(make_caller, scripted_transport) -> None:
    transport = scripted_transport(status=500, body={"error": "boom"})
    reconciler = OpenRouterCatalogReconciler(caller_factory=lambda: make_caller(transport), api_key=SecretStr("k"), model="m", base_url="https://o")
    decisions = asyncio.run(reconciler.reconcile(existing=EXISTING, candidates=CANDIDATES))
    assert len(decisions) == 3 and all(d.decision == "new_product" and d.confidence == "low" and d.reason.startswith("reconciler_unavailable") for d in decisions)


def test_with_no_existing_products_and_one_candidate_no_call_is_made(make_caller, scripted_transport) -> None:
    transport = scripted_transport(status=200, body=_answer([]))
    reconciler = OpenRouterCatalogReconciler(caller_factory=lambda: make_caller(transport), api_key=SecretStr("k"), model="m", base_url="https://o")
    decisions = asyncio.run(reconciler.reconcile(existing=(), candidates=CANDIDATES[:1]))
    assert transport.requests == [] and [d.decision for d in decisions] == ["new_product"]
```

`make_caller` / `scripted_transport`: reuse the R1 test fixtures that build a `ProviderCaller` over memory sinks with a scripted `HttpResponse` (read `tests/arv2/conftest.py` and `tests/arv2/test_live_foundation.py::make_caller`; if no scripted transport fixture exists, add `scripted_transport` to `tests/arv2/conftest.py`: an object with `.requests: list[HttpRequest]` whose `send(request)` records and returns the canned `HttpResponse(status, headers, body)`). A `ProviderCaller` needs `now=`; the fixture supplies it.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/arv2/test_onboarding_reconcile.py -v` → `ModuleNotFoundError`.

- [ ] **Step 3: Settings + env**

```python
    # Catalog identity ladder (O3 follow-up, founder ruling 2026-09-08): after the fingerprint and
    # exact-spelling stages, one batched model call per run decides "same offering or new" for the
    # leftovers, with each entry's official page as evidence; automatic merge only at high
    # confidence. Env: ``CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED``.
    onboarding_catalog_reconcile_enabled: bool = True
    # OpenRouter model for that call (validated 2026-09-08 on gpt-5-mini and grok-4.6; the small
    # one is faster and a fraction of a cent). Env: ``CLUE_ONBOARDING_RECONCILE_MODEL``.
    onboarding_reconcile_model: str = "openai/gpt-5-mini"
```

`.env.example` (after the persona-evidence line): `# One batched model call per run reconciles lineup entries the spelling key cannot match (page URL as evidence; automatic merge only at high confidence).` / `CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED=true` / `# OpenRouter model for that call.` / `CLUE_ONBOARDING_RECONCILE_MODEL=openai/gpt-5-mini`. Add both to the local `.env` (parity). Extend `ONBOARDING_SETTING_DEFAULTS` in `tests/arv2/test_onboarding_settings.py` with both.

- [ ] **Step 4: The module**

```python
# platform/api/clue_api/arv2/onboarding_reconcile.py
"""Stage three of the catalog identity ladder: one batched model call per run that decides, for
every lineup entry the fingerprint and spelling stages could not place, whether it is the SAME
offering as a product on file (or as an earlier candidate in the same batch) or a genuinely NEW
one — with each entry's official page as evidence. Validated 2026-09-08 on the four Insight Health
catalogs (28 → 18 rows, no wrong merge, identical on gpt-5-mini and grok-4.6).

The model never merges anything by itself: it returns decisions with a confidence, and the
synchronizer applies only ``high`` automatically; the rest become rows flagged for the gate.
The call goes through R1's ``ProviderCaller`` (estimate → raw record → ledger row) and this module
NEVER raises: any failure is a full set of ``new_product``/``low`` decisions with the reason.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import SecretStr

from clue_api.arv2.calls import CallSpec, ProviderCaller, SpendEstimate
from clue_api.arv2.onboarding_lineage import CatalogProduct
from clue_api.arv2.openrouter import (
    openrouter_chat_request,
    openrouter_cost_reader,
    openrouter_halt_rule,
    openrouter_message_text,
)
from clue_obs import get_logger

log = get_logger("clue_api.arv2.onboarding_reconcile")

__all__ = [
    "RECONCILE_SYSTEM_PROMPT", "CatalogReconciler", "ExistingProduct", "OpenRouterCatalogReconciler",
    "ReconcileDecision", "reconcile_output_schema",
]

Decision = Literal["same_as_existing", "same_as_candidate", "new_product"]
Confidence = Literal["high", "medium", "low"]

RECONCILE_SYSTEM_PROMPT = (
    "You reconcile a seller's product catalog. Given the products already on file (id, name, aliases, "
    "official page URL, description) and candidate entries just discovered, decide for EACH candidate "
    "whether it is the SAME offering as one on file, the SAME offering as an EARLIER candidate in this "
    "list, or a genuinely NEW offering. Judge by what the offering is. Evidence rules: (1) the same "
    "official_url is strong evidence of the same offering — but some companies present several offerings "
    "on one page, so if the descriptions describe different jobs they are different products even on one "
    "page; (2) different product-specific pages are strong evidence of different offerings; a homepage, "
    "pricing or listing URL is not evidence either way; (3) wording differences alone (spacing, 'AI', "
    "'Agent', trademark marks, word order) never make a new product. Never invent products. Answer with "
    "exactly one decision per candidate, in the candidates' order. Return JSON only."
)
_ESTIMATE = SpendEstimate(usd=Decimal("0.01"))


@dataclass(frozen=True)
class ExistingProduct:
    product_id: str
    name: str
    aliases: tuple[str, ...]
    official_url: str | None
    description: str


@dataclass(frozen=True)
class ReconcileDecision:
    candidate: str
    decision: Decision
    product_id: str | None
    candidate_name: str | None
    confidence: Confidence
    reason: str


class CatalogReconciler(Protocol):
    async def reconcile(
        self, *, existing: Sequence[ExistingProduct], candidates: Sequence[CatalogProduct]
    ) -> tuple[ReconcileDecision, ...]: ...


def reconcile_output_schema() -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False, "required": ["decisions"],
        "properties": {"decisions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["candidate", "decision", "product_id", "candidate_name", "confidence", "reason"],
            "properties": {
                "candidate": {"type": "string"},
                "decision": {"type": "string", "enum": ["same_as_existing", "same_as_candidate", "new_product"]},
                "product_id": {"type": ["string", "null"]},
                "candidate_name": {"type": ["string", "null"]},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "reason": {"type": "string"},
            }}}},
    }


def _fallback(candidates: Sequence[CatalogProduct], reason: str) -> tuple[ReconcileDecision, ...]:
    return tuple(ReconcileDecision(c.name, "new_product", None, None, "low", reason) for c in candidates)


class OpenRouterCatalogReconciler:
    def __init__(self, *, caller_factory: Callable[[], ProviderCaller], api_key: SecretStr, model: str,
                 base_url: str, timeout_s: float = 120.0) -> None:
        self._caller_factory = caller_factory
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout_s = timeout_s

    async def reconcile(self, *, existing: Sequence[ExistingProduct], candidates: Sequence[CatalogProduct]) -> tuple[ReconcileDecision, ...]:
        if not candidates:
            return ()
        if not existing and len(candidates) == 1:
            return (ReconcileDecision(candidates[0].name, "new_product", None, None, "high", "nothing on file to compare with"),)
        payload = {
            "products_on_file": [{"product_id": p.product_id, "name": p.name, "aliases": list(p.aliases), "official_url": p.official_url, "description": p.description} for p in existing],
            "candidates": [{"name": c.name, "official_url": c.official_url, "description": c.short_description} for c in candidates],
        }
        request = openrouter_chat_request(
            base_url=self._base_url, api_key=self._api_key, model=self._model,
            messages=[{"role": "system", "content": RECONCILE_SYSTEM_PROMPT}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            response_format={"type": "json_schema", "json_schema": {"name": "reconciliation", "strict": True, "schema": reconcile_output_schema()}},
            temperature=0, timeout_s=self._timeout_s,
        )
        spec = CallSpec(provider="openrouter", operation="chat/completions", label="catalog-reconcile", request=request,
                        estimate=_ESTIMATE, cost_reader=openrouter_cost_reader, halt_rule=openrouter_halt_rule)
        try:
            result = await asyncio.to_thread(self._caller_factory().call, spec)
            if result.response.status != 200:
                raise RuntimeError(f"openrouter status {result.response.status}")
            raw = json.loads(openrouter_message_text(result.response.body))
            decisions = raw["decisions"]
        except Exception as error:  # noqa: BLE001 — a step outcome for the synchronizer, never a raise
            log.warning("onboarding_reconcile.unavailable", reason=str(error)[:200])
            return _fallback(candidates, f"reconciler_unavailable: {str(error)[:120]}")
        return _validate(decisions, existing=existing, candidates=candidates)


def _validate(raw: object, *, existing: Sequence[ExistingProduct], candidates: Sequence[CatalogProduct]) -> tuple[ReconcileDecision, ...]:
    """One decision per candidate, references checked; anything malformed is new/low, never a raise."""
    by_candidate: dict[str, dict[str, Any]] = {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("candidate"), str):
                by_candidate.setdefault(item["candidate"], item)
    ids = {p.product_id for p in existing}
    out: list[ReconcileDecision] = []
    for index, candidate in enumerate(candidates):
        item = by_candidate.get(candidate.name)
        if item is None:
            out.append(ReconcileDecision(candidate.name, "new_product", None, None, "low", "reconciler_invalid: no decision returned")); continue
        decision, confidence = item.get("decision"), item.get("confidence")
        reason = str(item.get("reason") or "")[:500]
        if confidence not in ("high", "medium", "low") or decision not in ("same_as_existing", "same_as_candidate", "new_product"):
            out.append(ReconcileDecision(candidate.name, "new_product", None, None, "low", "reconciler_invalid: malformed decision")); continue
        if decision == "same_as_existing":
            if item.get("product_id") not in ids:
                out.append(ReconcileDecision(candidate.name, "new_product", None, None, "low", "reconciler_invalid: unknown product id")); continue
            out.append(ReconcileDecision(candidate.name, "same_as_existing", str(item["product_id"]), None, confidence, reason)); continue
        if decision == "same_as_candidate":
            earlier = {c.name for c in candidates[:index]}
            if item.get("candidate_name") not in earlier:
                out.append(ReconcileDecision(candidate.name, "new_product", None, None, "low", "reconciler_invalid: candidate reference is not an earlier candidate")); continue
            out.append(ReconcileDecision(candidate.name, "same_as_candidate", None, str(item["candidate_name"]), confidence, reason)); continue
        out.append(ReconcileDecision(candidate.name, "new_product", None, None, confidence, reason))
    return tuple(out)
```

Check `CallSpec`'s exact field names in `clue_api/arv2/calls.py` (`halt_rule` may be named differently or optional) and `openrouter_message_text`'s argument (body object vs response). `CatalogProduct.official_url` is added in Task 3 — for this task add the field now in `onboarding_lineage.py` (`official_url: str | None = None`, last, so positional construction in existing tests keeps working) and nothing else there.

- [ ] **Step 5: Run, lint, commit**

`uv run pytest tests/arv2/test_onboarding_reconcile.py tests/arv2/test_onboarding_settings.py tests/arv2/test_import_guard.py -v && uv run ruff check platform/api/clue_api/arv2 tests/arv2 libs/clue-config && uv run ruff format --check platform/api/clue_api/arv2 tests/arv2 && uv run mypy platform/api/clue_api/arv2`

```bash
git add libs/clue-config/clue_config/settings.py .env.example platform/api/clue_api/arv2/onboarding_reconcile.py platform/api/clue_api/arv2/onboarding_lineage.py tests/arv2/test_onboarding_reconcile.py tests/arv2/test_onboarding_settings.py tests/arv2/conftest.py
git commit -m "feat(arv2): catalog reconciler — one batched OpenRouter call per run (fixed prompt, strict decision schema, page URLs as evidence, validated references, never raises) + the two identity-ladder settings"
```

---

### Task 3: The ladder in the synchronizer, with alias write-back

**Files:**
- Modify: `platform/api/clue_api/arv2/onboarding_lineage.py`
- Test: `tests/arv2/test_onboarding_lineage_db.py` (extend), `tests/arv2/test_onboarding_lineage.py` (extend)

**Interfaces:**
- `synchronize_catalog(conn, *, workspace_id, brand_id, document_id, products: Sequence[CatalogProduct], reconciler: CatalogReconciler | None = None) -> tuple[ProductLink, ...]`.
- `ProductLink` gains `reconcile_confidence: str | None = None`, `reconcile_reason: str | None = None` (both `None` for deterministic stages).
- Stage order per entry: (1) lineage row for this document/ordinal → mirror it; (2) prior lineage by fingerprint → `lineage_reused`; (3) exact key against name+aliases of existing rows → one hit `alias_reused` (+ alias write-back when the observed name folds to a new spelling), several hits `unresolved_ambiguous`; (4) leftovers collected. After the loop: if leftovers and `reconciler` is not None → ONE `reconciler.reconcile(existing=<rows as ExistingProduct incl. descriptions from the run's own catalog when the row was minted this run, else "">, candidates=leftovers)`; apply in candidate order: `same_as_existing`+`high` → `model_reused` on that product + alias write-back; `same_as_candidate`+`high` → the product the earlier candidate resolved to (or was minted as) → `model_reused` + alias; any `same_*` below high → mint a new row, state `model_unsure`, `reconcile_confidence`, `reconcile_reason` = `"suggested: <product name or candidate> — <reason>"`; `new_product` → mint, state `created`, confidence/reason recorded when the model said so. No reconciler → today's behaviour (mint, `created`). Descriptions for `ExistingProduct` come from the current catalog document's own entries when available, else empty string.
- Alias write-back uses `clue_spine.add_product_aliases`; the observed name is added when its fold differs from the row's name and aliases.

- [ ] **Step 1: Failing tests** (extend `tests/arv2/test_onboarding_lineage_db.py`; a `ScriptedReconciler` records calls and returns scripted decisions)

```python
class ScriptedReconciler:
    def __init__(self, decisions): self.decisions = tuple(decisions); self.calls = []
    async def reconcile(self, *, existing, candidates):
        self.calls.append((tuple(p.name for p in existing), tuple(c.name for c in candidates)))
        return self.decisions


def test_the_model_stage_merges_only_high_confidence_and_flags_the_rest() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-ladder"
            brand_id, doc_id = await _catalog_document(conn, ws)
            referrals = await create_product(conn, brand_id=brand_id, workspace_id=ws, name="Referrals AI Agent")
            entries = [
                CatalogProduct("Referral Management AI Agent", "Automates referral processing.", (), "https://x.io/referral-management"),
                CatalogProduct("HEDIS AI Workflows", "HEDIS coordination.", (), "https://x.io/hedis"),
                CatalogProduct("Aura Anywhere", "Mobile scribe.", (), "https://x.io/aura-anywhere"),
            ]
            reconciler = ScriptedReconciler([
                ReconcileDecision("Referral Management AI Agent", "same_as_existing", referrals.product_id, None, "high", "same page"),
                ReconcileDecision("HEDIS AI Workflows", "new_product", None, None, "high", "own page"),
                ReconcileDecision("Aura Anywhere", "same_as_existing", referrals.product_id, None, "medium", "guess"),
            ])
            links = await synchronize_catalog(conn, workspace_id=ws, brand_id=brand_id, document_id=doc_id, products=entries, reconciler=reconciler)
            assert reconciler.calls == [(("Referrals AI Agent",), ("Referral Management AI Agent", "HEDIS AI Workflows", "Aura Anywhere"))]
            assert (links[0].resolution_state, links[0].product_id, links[0].reconcile_confidence) == ("model_reused", referrals.product_id, "high")
            assert (links[1].resolution_state, links[1].reconcile_confidence) == ("created", "high")
            assert links[2].resolution_state == "model_unsure" and links[2].product_id not in (None, referrals.product_id)
            assert links[2].reconcile_reason.startswith("suggested: Referrals AI Agent")
            assert "Referral Management AI Agent" in (await get_product(conn, referrals.product_id)).aliases
            rows = (await conn.execute(text("SELECT resolution_state, reconcile_confidence, reconcile_reason FROM onboarding_product_lineage WHERE document_id = :d ORDER BY entry_ordinal"), {"d": doc_id})).mappings().all()
            assert [r["resolution_state"] for r in rows] == ["model_reused", "created", "model_unsure"]
            # the next run resolves the alias at stage 3 without the model
            reconciler2 = ScriptedReconciler([])
            doc2 = await _second_document(conn, ws, brand_id)
            again = await synchronize_catalog(conn, workspace_id=ws, brand_id=brand_id, document_id=doc2, products=entries[:1], reconciler=reconciler2)
            assert again[0].resolution_state == "alias_reused" and reconciler2.calls == []

    run_async(scenario())


def test_same_as_candidate_resolves_within_one_run_and_a_silent_reconciler_keeps_todays_behaviour() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o3-ladder-batch"
            brand_id, doc_id = await _catalog_document(conn, ws)
            entries = [
                CatalogProduct("AI Front Desk", "Clinic phone operations.", (), "https://x.io/frontdesk"),
                CatalogProduct("AI FrontDesk Agent", "Clinic phone operations.", (), None),
            ]
            reconciler = ScriptedReconciler([
                ReconcileDecision("AI Front Desk", "new_product", None, None, "high", "first"),
                ReconcileDecision("AI FrontDesk Agent", "same_as_candidate", None, "AI Front Desk", "high", "same job, no page"),
            ])
            links = await synchronize_catalog(conn, workspace_id=ws, brand_id=brand_id, document_id=doc_id, products=entries, reconciler=reconciler)
            assert links[0].resolution_state == "created" and links[1].resolution_state == "model_reused"
            assert links[1].product_id == links[0].product_id
            assert len(await list_products(conn, brand_id)) == 1
            # no reconciler → both minted, exactly as before this plan
            doc2 = await _second_document(conn, ws, brand_id)
            plain = await synchronize_catalog(conn, workspace_id=ws, brand_id=brand_id, document_id=doc2, products=[CatalogProduct("Something Else", "x", (), None)])
            assert plain[0].resolution_state == "created" and plain[0].reconcile_confidence is None

    run_async(scenario())
```

Write `_second_document(conn, ws, brand_id)` in the test module (a new `lineup` step + `open_document` at `product/catalog.md`, the way `test_a_second_document_creates_its_own_lineage_but_reuses_products_by_name` does). Pure test (offline file): `ProductLink` default fields are `None`; a first-run batch with `existing=()` and one candidate is never sent to the reconciler by the synchronizer (it calls only when leftovers are non-empty AND (existing rows exist OR more than one leftover)).

- [ ] **Step 2: Run to verify failure** — the new tests fail on `TypeError: unexpected keyword 'reconciler'`.

- [ ] **Step 3: Implement the ladder** — restructure `synchronize_catalog` into: `_existing_rows()`, `_deterministic_stage(entry) -> ProductLink | None (+ alias write-back)`, `_model_stage(leftovers)`, `_mint(entry, state, confidence, reason)`, `_record(lineage row INSERT with the two new columns)`. Keep the document-scope check and the fingerprint guard from today. `existing` passed to the reconciler includes rows minted earlier in this call (with the entry's own description) so `same_as_candidate` can also be expressed as `same_as_existing` by the model — accept either. Every merge (stages 3 and 4) calls `add_product_aliases(conn, product_id=, workspace_id=, aliases=(entry.name, *entry.aliases))`.

- [ ] **Step 4: Run, ruff, mypy, commit**

`uv run pytest tests/arv2/test_onboarding_lineage.py tests/arv2/test_onboarding_lineage_db.py tests/arv2/test_onboarding_reconcile.py tests/arv2/test_import_guard.py -v && uv run ruff check platform/api/clue_api/arv2 tests/arv2 && uv run ruff format --check platform/api/clue_api/arv2 tests/arv2 && uv run mypy platform/api/clue_api/arv2`

```bash
git add platform/api/clue_api/arv2/onboarding_lineage.py tests/arv2/test_onboarding_lineage_db.py tests/arv2/test_onboarding_lineage.py
git commit -m "feat(arv2): catalog identity ladder — fingerprint, exact spelling, then one batched model reconciliation with page evidence (high-confidence merges only; the rest flagged model_unsure); every match writes the observed spelling as an alias"
```

---

### Task 4: The Exa request text, the catalog document's URL, and the driver/composition seams

**Files:**
- Modify: `platform/api/clue_api/arv2/onboarding_driver.py` (`LINEUP_SYSTEM_PROMPT`; `CatalogProduct(official_url=...)` in `_lineup`; `reconciler` kwarg → `_catalog_sync` → `self._sync(..., reconciler=self._reconciler)`), `platform/api/clue_api/arv2/exa_client.py` (`product_catalog_output_schema` descriptions), `platform/api/clue_api/arv2/onboarding_documents.py` (verify `official_url` survives into `front_matter["products"][i]`; add it if the mapper drops it), `platform/api/clue_api/fleet_main.py` (compose), `docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md` (§3 descriptions, §5 ladder, §6 lineage states), `platform/api/clue_api/arv2/README.md`
- Test: `tests/arv2/test_onboarding_driver.py` (extend), `tests/arv2/test_exa_client.py` or wherever the schema is pinned (update the two descriptions), `tests/api/test_fleet_wiring.py` (extend)

- [ ] **Step 1: The Exa text (validated in the playground 2026-09-08)**

`LINEUP_SYSTEM_PROMPT` becomes:

```
Prefer pages on the company's own domain; list every distinct product page; keep integrations and partner programs separate from standalone products; never invent an offering; when unsure of a field, omit it. For each offering, give official_url as the page on the company's own domain where that offering is presented (a page may present several offerings), and give name exactly as that page writes it for the offering, keeping the page's own spelling, spacing and capitalisation. If an offering has no page of its own on the company's domain, omit official_url rather than citing the homepage or a listing page.
```

`product_catalog_output_schema()` — `name.description`: `"The offering's name exactly as its official_url page writes it, keeping that page's spelling, spacing and capitalisation."`; `official_url.description`: `"The page on the company's own domain where this offering is presented; a page may present several offerings. Not the homepage, a pricing page or a blog post. Omit only if no such page exists."` Property set and `required` unchanged. Update the pinned test and the contract §3 text.

- [ ] **Step 2: Driver + composition**

- `OnboardingRunWorkHandler.__init__(..., reconciler: CatalogReconciler | None = None)`; `_catalog_sync` passes `reconciler=self._reconciler` into `self._sync(...)`. In `_lineup`, build `CatalogProduct(name=..., short_description=..., aliases=..., official_url=entry.get("official_url") if isinstance(entry.get("official_url"), str) else None)`.
- The handler takes `reconciler_factory: Callable[[UUID], CatalogReconciler] | None = None` (run id in): `_catalog_sync` builds `reconciler = self._reconciler_factory(scope.run_id)` when a factory is present and passes `reconciler=` into `self._sync(...)`; otherwise `reconciler=None`. The per-run factory exists because a `ProviderCaller` is one-per-step state under `arv2_raw_root/onboarding/<run_id>/catalog-reconcile/` (the O3 rule).
- `fleet_main._build_onboarding_handler(..., reconciler_factory=)`: when `settings.onboarding_catalog_reconcile_enabled` and `secrets.openrouter_api_key` is set, the factory is `lambda run_id: OpenRouterCatalogReconciler(caller_factory=lambda: build_onboarding_provider_caller(settings, run_id=run_id, step_label="catalog-reconcile"), api_key=<the secret>, model=settings.onboarding_reconcile_model, base_url=GatewayConfig().base_url)` (`GatewayConfig` from `clue_config.gateway`). When the flag is off or the key is missing the factory is `None` and the handler logs `onboarding.reconciler_not_composed` once at composition (the sync then runs without a model stage — today's behaviour).
- Offline driver test: with a scripted `reconciler_factory` recording the run id, `_catalog_sync` passes a non-`None` reconciler to the injected `synchronize_catalog` double (assert the kwarg); without a factory the double receives `reconciler=None`. Fleet wiring test: flag on + no OpenRouter key → handler composes with `reconciler_factory is None`; flag on + key → a factory is present.

- [ ] **Step 3: Docs** — contract §5 gets the ladder (four stages, what merges automatically, `model_unsure` semantics, alias write-back), §6 the two new states and columns, §3 the descriptions; README's O3 section gets a "Catalog identity ladder" paragraph. Also record in `apps/frontend/docs/api-contracts/projects.md`'s product-set pointer that a `model_unsure` lineage row is "flagged for the gate" (one sentence; the gate UI is O6's).

- [ ] **Step 4: Run, commit**

`uv run pytest tests/arv2 --ignore-glob='*_live.py' tests/api/test_fleet_wiring.py -q && uv run ruff check platform/api/clue_api/arv2 platform/api/clue_api/fleet_main.py tests && uv run mypy platform/api/clue_api/arv2 platform/api/clue_api/fleet_main.py`

```bash
git add platform/api/clue_api/arv2/onboarding_driver.py platform/api/clue_api/arv2/exa_client.py platform/api/clue_api/arv2/onboarding_documents.py platform/api/clue_api/fleet_main.py docs/specs/ARV2-PRODUCT-CATALOG-CONTRACT.md platform/api/clue_api/arv2/README.md apps/frontend/docs/api-contracts/projects.md tests
git commit -m "feat(arv2): lineup asks Exa for the page's own name and page (never the homepage); the catalog carries official_url; the driver composes the per-run catalog reconciler behind CLUE_ONBOARDING_CATALOG_RECONCILE_ENABLED; contract §3/§5/§6 updated"
```

---

### Task 5: Standing-rule checklist, memory note

- [ ] Greps (zero hits): `grep -rn "client_kb_version\|readiness_decision\|project_run_stage0_pins\|evaluate_stage0_readiness" platform/api/clue_api/arv2/onboarding_reconcile.py platform/api/clue_api/arv2/onboarding_lineage.py`; `uv run alembic heads` → one line.
- [ ] `_memory/2026-09-08-arv2-onboarding-o3-catalog-identity-ladder.md`: the evidence (POC numbers), the ladder, the founder rulings (no stoplist; page = evidence not key; auto-merge only deterministic + high; rest flagged), what is composed, the migration id, test counts, "live proof NOT run — Task 6 is founder-triggered"; `_memory/README.md` pointer. Commit: `memory: O3 catalog identity ladder close-out`.

---

### Task 6: Live proof (founder-triggered; ~$3 per run)

- [ ] A fresh workspace + brand + principal on `clue_semarang`; run 1 → count product rows and lineage states; run 2 → expect zero new rows from drift (every re-spelling `alias_reused`/`lineage_reused`/`model_reused`), any `model_unsure` rows listed with their reasons; the reconciler's ledger row under `arv2_raw_root/onboarding/<run_id>/catalog-reconcile/`. Evidence under `.context/arv2-onboarding-o3-ladder-acceptance/`; numbers into the memory note; commit the note only.
