# ARV2 D2 — the display module (A4 + S4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the claim rows D1 loaded into persisted, claim-cited page copy: one Luna call per section, the section recipes and prompts as content, the sensitivity floor, `display_block` persistence with generate-once / recipe-scoped invalidation, the evidence resolver, and the activity event — proven on Zafran's overview, insights and Nick Fisher pages with zero unsafe leaks.

**Architecture:** A new subpackage `platform/api/clue_api/arv2/display/` inside the ARV2 lane. Content (recipes, prompts) is data in two modules Shashank owns going forward; the machinery reads it. The gather step reads **live claims** (not the merge — a field like `contact.facet.voice_quote` holds 26 facts, and display is a fact list, not a single current truth) through `clue_research.claimstore.claims_for_entities`, filters them by recipe/flag/use-class, dedupes near-duplicates, and hands the model short aliases (`c1…cN`) instead of uuids. The runner sends one chat-completions call per section through the lane's `ProviderCaller` (stable prefix + section suffix), parses the JSON into the contract-v1 `ResearchSection` shape, resolves aliases and contact names back to ids, computes priority, and runs the floor. Persistence writes one `display_block` row per section (superseding the live row), staleness is recipe-scoped, and the page orchestrator runs all missing sections of a page in parallel via `asyncio.to_thread` with one caller per section. A CLI generates and persists the Zafran pages against the worktree database.

**Tech Stack:** Python 3.13, SQLAlchemy async (`text()` SQL), pydantic v2 for the model reply shape, the ARV2 `ProviderCaller`/`ScriptedTransport`/memory sinks, OpenRouter chat-completions (`openai/gpt-5.6-luna`), pytest with the `tests/claimstore` DB harness.

**Spec:** `docs/specs/ARV2-MASTER-PLAN.md` v1.6 §2, §4, §6 (contract v1 shapes), §7 (the display layer — binding); `docs/specs/ARV2-DATA-SOURCE-MAP.md` v1.1 §3.3–3.4, §3.6, §3.8, §3.9, §4 (the display-block path); `docs/specs/ARV2-WORK-SPLIT.md` A4 + S4 (§6.5); `.context/frontend-page-content/README.md` §2–§3b (recipes, the prompt, the control-test decisions); `.context/display-layer-control-test/REPORT.md` (the measured rulings). Presentation truth: the dummy frontend's Zod models `src/features/accounts/model/research-display.ts` at `clue-frontend` `integration/live-backend-v1` @ `84f8ee7`.

## Global Constraints

1. **Import guard (lane rule).** Every module under `platform/api/clue_api/arv2/` imports only `clue_api.arv2.*`, the allow-listed internal packages in `tests/arv2/test_import_guard.py::ALLOWED_INTERNAL_PREFIXES` (`clue_core`, `clue_config`, `clue_storage`, `clue_db`, `clue_research.claimstore`, `clue_research.identity`, `clue_research.membership`, …), stdlib and third-party libraries — never `clue_api.*` outside the lane and never a quarantined module. If a new dependency is needed, extend the allowlist in the same commit and say why in the test.
2. **Every provider call goes through `ProviderCaller.call`** (`clue_api.arv2.calls`) with `provider="openrouter"`, `openrouter_cost_reader`, `openrouter_halt_rule`, a `SpendEstimate` before the wire. No module opens a socket of its own. `ScriptedTransport` is the lane's one test double; live behaviour is tested live and skips (never mocks) without a key.
3. **Flags.** Every new `Settings` field appears in `.env.example` with its default in the same commit, and in `tests/arv2/test_settings.py::ARV2_SETTING_DEFAULTS`. Model ids are env settings, never hard-coded in the runner.
4. **No secrets anywhere but the local `.env`.** Never in code, fixtures, reports, `.context/`, `_memory/`, commit messages or `.artifacts/` metadata. Raw records and ledgers go under `Settings.arv2_raw_root` (`.artifacts/arv2`, git-ignored).
5. **Database.** Only the worktree's throwaway Postgres: `postgresql+asyncpg://clue:clue@localhost:55060/clue` (container `clue-pg-managua`; at head `3742d1281a10`; carries the D1 answer key: 294 claims under `ws_arv2_answer_key`). DB tests use `tests/claimstore/conftest.py::rollback_conn` and roll back. Never a shared database. Never `make check` or a broad `pytest` with real keys in the environment — focused suites only; the two wider passes run with `--ignore-glob='*_live.py'`.
6. **Master plan §2 principle 2 and §7:** judgment annotates, it never vetoes. The **single hard rule** is the floor: an `outreach_safe=false` claim cited outside a restricted section regenerates that section once, then the offending item is dropped. A page is never blocked; an empty section is a real answer (`empty: true`, no model call).
7. **Master plan §7 generation rules:** one call per section; all sections of a page in parallel; **default reasoning effort** (never `low`); stable prefix (system + client + subject + the section list + the claims) then the section suffix; the three fixed lines in the system prompt (never type claim ids into prose; write dates as "17 June 2026"; the personal-hobby hook at most once per page); the model never sees a URL or a domain; `sendLine` is a separate field, never inside quotation marks.
8. **Contract v1 is the dummy's Zod (`research-display.ts`).** `ResearchSection {key, h1, empty, items[], intro[]?, restricted, defaultOpen, emptyMessage?}`; `ResearchItem {id, h2, body[], sendLine|null, contactRefs[], inlineLead?, fitDisposition?, subject?, priority 1|2|3, newSinceLastVisit}`; `ResearchSentence {text, claimIds[], segments[]?}`; `ResearchContactReference {accountId, contactId, name, title?, persona?}`; `ResearchSendLine {channel, text, claimIds[]}`. `h1` is served bare (no counts). `claimIds` are claim uuid strings.
9. **Standing rule (2026-09-07): no old-lane gate may block a new-lane path.** The display module reads `claim`, `display_block`, `display_section_recipe`, `entity_research_account_coverage`, `account_entity`, `contact_entity`, `brand`; it never imports or calls Client-KB, readiness, Stage-0 pin or `display_allowed` machinery. Re-check at close-out.
10. **Commits.** One or more well-scoped commits per task, no `Co-Authored-By`/AI attribution, never push. Testing cadence (founder, D1 ruling carried over): focused tests per task; one wider offline pass after Task 5; one at close-out.
11. **Content ownership.** `display/recipes.py` and `display/prompts.py` are the S4 content files Shashank owns after this plan lands; every other module is A4 machinery. Keep them free of machinery so they can be edited without touching code paths.

---

## Decisions this plan takes (each overturnable by the founder; recorded in the ledger)

1. **Display reads live claims, not the merge.** `current_values` collapses `(entity, field)` to one winner; display needs every live fact. The gather step uses `claims_for_entities` (live, retention-safe, workspace-scoped). Eligibility mirrors the merge posture without the cardinality collapse: when `Settings.verification_enabled` is true, unverified tier-4 claims are excluded (parity with `active_merge_policy().require_verified_tier4`); otherwise every live claim is eligible.
2. **Short aliases in the prompt.** Each claim in a call is presented as `c1…cN` (stable order: priority, field_key, collected_at, id); the runner maps aliases back to uuids. Unknown aliases are dropped and counted; a uuid never reaches the model, so the "ids typed in prose" defect cannot surface a uuid.
3. **Section keys are contract v1** (kebab-case, fixed): insights `buying-signals`, `money-and-momentum`, `tools-they-already-use`, `how-they-sell`, `contact-insights`, `context-only`; overview `what-they-do`, `why-they-fit`, `why-now`, `buying-committee`, `how-to-approach`, `watch-outs`; contact `why-this-person`, `problem-right-now`, `openers`, `angles`, `do-not-mention`. (`how-to-approach`, `watch-outs`, `problem-right-now`, `why-now` are the keys the dummy already switches on; the dummy's slugged `what-zafran-does` becomes `what-they-do` at the D4 re-lift.)
4. **Restricted-section input** = every `outreach_safe=false` live claim of the subject (for a contact page: the contact **and** its account) ∪ the recipe's allowed keys regardless of flag. Non-restricted input = allowed keys, `outreach_safe=true` only. `use_class = sensitive` claims never enter any section (the floor's special-category rule, fail-closed).
5. **Account pages expand to the committee.** For an account-page recipe that names `contact.*` keys, those keys are gathered over the account's committee members: `committee_member_ids` of the latest `entity_research_account_coverage` row (`ORDER BY created_at DESC, coverage_id DESC LIMIT 1`); when no coverage row exists, every `contact_entity` under the account that has ≥1 live claim. Every claim payload carries `subject` (the person's name) so the model can attribute.
6. **Near-duplicate dedupe is per flag group.** Within one `field_key` and one `outreach_safe` value, two claims are duplicates when the normalised rendered text of one contains the other's or their token Jaccard ≥ 0.7; keep the one with the longer `evidence_span`, then the earlier `collected_at`. A safe/unsafe twin pair is **kept as two rows** (the safe one may feed outreach sections, the unsafe one the restricted ones) — the store-level "one fact, one flag" fix is R-side. Deduped ids are recorded in `checks`.
7. **Client context is a setting for now.** `CLUE_ARV2_DISPLAY_CLIENT_PITCH` (default the Clue one-liner) supplies `client.what_we_sell`; `client.name` is the workspace's brand name. Track O's company-overview artifact replaces the setting when O3 lands.
8. **Evidence resolver is pure.** `sourceDomain` = host lower-cased, `www.` stripped; `faviconUrl` = `https://www.google.com/s2/favicons?domain={domain}&sz=32` when there is a domain (the frontend-spec's stated source; the frontend may still proxy) else `null`; `title` = the first of `value_json.title` / `.source_title` / `.page_title` when the value is an object, else `null`; `quote` = `evidence_span` or `null` with `researchExcerpt = render_value_text(...)`; `verificationKind = "record"` when `extraction_method = api` and `source_url IS NULL`, else `"verified"`; `verifiedAt = date(observed_at or collected_at)`; `publishedAt = value_json.published / .date` when it parses as a date, else `null`; `mediaTimestamp = value_json.media_timestamp`; `provider = source_key`. No network.
9. **Block body stores the section body plus the checks.** `body_json = {"intro": [...], "items": [...], "checks": {...}, "cited_flags": {claimId: outreach_safe}, "cost_usd": "…", "call": {…}}`; `key/h1/restricted/defaultOpen` come from the recipe at read time; `empty` is computed. `prompt_version = f"{PROMPT_VERSION}+{recipe.instruction_version}"`, `recipe_version = RECIPE_VERSION`.
10. **Off-recipe and unknown citations are annotations.** Such ids are removed from `claimIds` and counted in `checks`; a sentence left uncited is kept and counted as `uncited_sentences`. Only the unsafe-outside-restricted case triggers the regenerate-once-then-drop rule.
11. **The regenerate call is the same prompt plus one line** appended to the suffix naming the forbidden aliases (`"Your previous draft cited c7, c9 which must not appear in this section. Rewrite without them."`).
12. **Activity.** Every page generation writes one `account_activity_event` (`kind='summary'`, actor `clue`, `text = "Overview written" | "Insights written" | "Contact page written"`, `action = "{page} generated"` on first generation and `"{page} regenerated"` when any section was superseded), against the account (a contact page's event goes to its account, `ref_json = {"contact_id": …}`).

---

## File structure

```
platform/api/clue_api/arv2/display/
  __init__.py        exports
  recipes.py         S4 CONTENT: SectionRecipe, SYSTEM_RECIPES, RECIPE_VERSION, PAGES, recipes_for, load_display_recipes, read_recipes
  prompts.py         S4 CONTENT: PROMPT_VERSION, SYSTEM_PROMPT, SECTION_INSTRUCTIONS, build_messages, RESPONSE_FORMAT
  render.py          render_value_text, DisplayClaim, claim_payload (alias table), dedupe_near_duplicates
  gather.py          SubjectRef, ClientContext, resolve_subject, committee_members, gather_section_input
  runner.py          LunaSectionRunner (ProviderCaller), reply models, parse_reply, SectionDraft
  floor.py           FloorReport, check_floor, apply_floor, verbatim_annotations
  blocks.py          live_blocks, insert_block, stale_sections, compose_display_block
  evidence.py        EvidenceRef, resolve_evidence, source_domain, favicon_url
  page.py            ensure_page (parallel), regenerate_sections, record_page_written
scripts/generate_arv2_display.py
tests/arv2/display/{__init__,test_recipes,test_prompts,test_render,test_gather_db,test_runner,test_floor,test_blocks_db,test_evidence,test_page_db,test_display_live}.py
```

---

### Task 1: Settings, recipes (S4 content), and the recipe seeder

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (after `sensitivity_floor_enabled`)
- Modify: `.env.example` (after `CLUE_SENSITIVITY_FLOOR_ENABLED=true`)
- Modify: `tests/arv2/test_settings.py::ARV2_SETTING_DEFAULTS`
- Create: `platform/api/clue_api/arv2/display/__init__.py`, `platform/api/clue_api/arv2/display/recipes.py`
- Modify: `platform/api/clue_api/arv2_wiring.py` (append `load_display_recipes` to `RESEARCH_PACK_LOADERS`)
- Modify: `platform/api/clue_api/arv2/answer_key_loader.py::_load_packs` docstring only if needed (it already iterates `RESEARCH_PACK_LOADERS`, so recipes seed with the packs)
- Test: `tests/arv2/display/__init__.py`, `tests/arv2/display/test_recipes.py`

**Interfaces:**
- Produces: `Settings.arv2_display_model: str = "openai/gpt-5.6-luna"`, `Settings.arv2_display_timeout_s: float = 240.0`, `Settings.arv2_display_max_parallel: int = 8`, `Settings.arv2_display_client_pitch: str = "AI-native ABM: account and committee research, personalised content, brand-aligned artifacts, scaled per account"`.
- Produces: `SectionRecipe` (frozen dataclass: `page: Literal["overview","insights","contact"]`, `section_key: str`, `h1: str`, `position: int`, `allowed_field_keys: tuple[str, ...]`, `restricted: bool = False`, `default_open: bool = False`, `instruction_version: str = "v1"`, `narrative: bool = False`, `workspace_id: str = ""`), `RECIPE_VERSION = 1`, `PAGES = ("overview", "insights", "contact")`, `SYSTEM_RECIPES: tuple[SectionRecipe, ...]`, `RESTRICTED_SECTION_KEYS = frozenset({"context-only", "watch-outs", "do-not-mention"})`, `def recipes_for(page) -> tuple[SectionRecipe, ...]` (system rows, position order), `async def load_display_recipes(conn) -> None` (upsert the system rows: `INSERT … ON CONFLICT (page, section_key, workspace_id) DO UPDATE SET h1, position, allowed_field_keys, restricted, default_open, instruction_version`), `async def read_recipes(conn, page, *, workspace_id) -> tuple[SectionRecipe, ...]` (system rows overridden by same-`section_key` workspace rows, ordered by position).
- `narrative` is a **code-side** flag (not a column): `what-they-do` and `why-they-fit` are narrative sections whose prose goes to `intro[]`; every other section is item-only. The prompts module reads it.

- [ ] **Step 1: Settings + `.env.example` + defaults test**

`settings.py`, after `sensitivity_floor_enabled`:

```python
    # --- ARV2 display layer (D2; master plan §7) -----------------------------------------------
    # OpenRouter model id for the section writer. The control test (2026-09-04) rejected every
    # cheaper model on the two non-negotiables. Env: ``CLUE_ARV2_DISPLAY_MODEL``.
    arv2_display_model: str = "openai/gpt-5.6-luna"
    # Per-section HTTP timeout. A page's sections run in parallel, so this bounds the first open.
    # Env: ``CLUE_ARV2_DISPLAY_TIMEOUT_S``.
    arv2_display_timeout_s: float = 240.0
    # How many sections of one page are in flight at once (one ProviderCaller each).
    # Env: ``CLUE_ARV2_DISPLAY_MAX_PARALLEL``.
    arv2_display_max_parallel: int = 8
    # ``client.what_we_sell`` in the display prompt, until Track O's company-overview artifact
    # supplies it (D2 decision 7). Env: ``CLUE_ARV2_DISPLAY_CLIENT_PITCH``.
    arv2_display_client_pitch: str = (
        "AI-native ABM: account and committee research, personalised content, "
        "brand-aligned artifacts, scaled per account"
    )
```

`.env.example`, after `CLUE_SENSITIVITY_FLOOR_ENABLED=true`:

```
# --- ARV2 display layer (D2; master plan §7) -----------------------------------
# OpenRouter model id for the per-section page writer (control test 2026-09-04: Luna only).
CLUE_ARV2_DISPLAY_MODEL=openai/gpt-5.6-luna
# Per-section HTTP timeout in seconds; sections of a page run in parallel.
CLUE_ARV2_DISPLAY_TIMEOUT_S=240
# Sections of one page in flight at once.
CLUE_ARV2_DISPLAY_MAX_PARALLEL=8
# The client's one-line pitch the prompt shows as client.what_we_sell (until the O3 artifact).
CLUE_ARV2_DISPLAY_CLIENT_PITCH=AI-native ABM: account and committee research, personalised content, brand-aligned artifacts, scaled per account
```

Add to `ARV2_SETTING_DEFAULTS` in `tests/arv2/test_settings.py`:

```python
    "arv2_display_model": "openai/gpt-5.6-luna",
    "arv2_display_timeout_s": 240.0,
    "arv2_display_max_parallel": 8,
    "arv2_display_client_pitch": (
        "AI-native ABM: account and committee research, personalised content, "
        "brand-aligned artifacts, scaled per account"
    ),
```

Check `test_env_example_documents_each_setting_with_its_default` still passes (it compares the `.env.example` line against the default's string form; `240.0` vs `240` — read that test and write the example value in the form it accepts, adjusting the test's number comparison only if it is strictly string-based; if so use `CLUE_ARV2_DISPLAY_TIMEOUT_S=240.0`).

Run: `uv run pytest tests/arv2/test_settings.py -q` → PASS.

- [ ] **Step 2: Write the failing recipe tests**

`tests/arv2/display/test_recipes.py`:

```python
"""S4 exit gate: every recipe key is a registered field; the page grammar is the master plan's."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_api.arv2.catalog_seed import ARV2_FIELD_KEYS
from clue_api.arv2.display.recipes import (
    PAGES,
    RECIPE_VERSION,
    RESTRICTED_SECTION_KEYS,
    SYSTEM_RECIPES,
    load_display_recipes,
    read_recipes,
    recipes_for,
)
from clue_research.claimstore.packs import CORE_PACK
from clue_research.profiling.committee.fields import COMMITTEE_PACK
from clue_research.profiling.fields import DEEP_PROFILING_PACK
from tests.claimstore.conftest import migrated_db, require_claimstore_db, rollback_conn  # noqa: F401
from tests.db.conftest import run_async

EXPECTED_H1S = {
    "insights": [
        "Buying signals", "Money & momentum", "Tools they already use",
        "How they sell, and who they win", "Contact insights", "Context only",
    ],
    "overview": [
        "What they do", "Why they fit", "Why now", "Buying committee", "How to approach", "Watch-outs",
    ],
    "contact": ["Why this person", "Their problem right now", "Openers", "Angles", "Do not mention"],
}


def _static_registered_keys() -> set[str]:
    keys = set(ARV2_FIELD_KEYS)
    for pack in (CORE_PACK, DEEP_PROFILING_PACK, COMMITTEE_PACK):
        keys.update(field.field_key for field in pack)
    return keys


def test_page_grammar_is_the_master_plans() -> None:
    for page in PAGES:
        rows = recipes_for(page)
        assert [r.h1 for r in rows] == EXPECTED_H1S[page]
        assert [r.position for r in rows] == list(range(len(rows)))
        assert all("(" not in r.h1 and "·" not in r.h1 for r in rows), "h1 is served bare"


def test_restricted_sections_are_exactly_the_three() -> None:
    restricted = {r.section_key for r in SYSTEM_RECIPES if r.restricted}
    assert restricted == RESTRICTED_SECTION_KEYS == {"context-only", "watch-outs", "do-not-mention"}


def test_every_recipe_key_is_a_registered_field_statically() -> None:
    registered = _static_registered_keys()
    missing = {
        (r.page, r.section_key, key)
        for r in SYSTEM_RECIPES
        for key in r.allowed_field_keys
        if key not in registered
    }
    assert not missing, f"unregistered recipe keys: {sorted(missing)}"


def test_every_recipe_has_keys_and_versions() -> None:
    assert RECIPE_VERSION == 1
    for r in SYSTEM_RECIPES:
        assert r.allowed_field_keys, (r.page, r.section_key)
        assert len(set(r.allowed_field_keys)) == len(r.allowed_field_keys), "no duplicate keys"
        assert r.instruction_version == "v1"
        assert r.workspace_id == ""


@pytest.mark.usefixtures("require_claimstore_db")
def test_recipes_seed_idempotently_and_a_workspace_row_overrides() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await load_display_recipes(conn)
            await load_display_recipes(conn)  # second run is a no-op upsert
            n = (await conn.execute(text("SELECT count(*) FROM display_section_recipe"))).scalar_one()
            assert n == len(SYSTEM_RECIPES)
            await conn.execute(
                text("INSERT INTO workspace (workspace_id, name) VALUES ('ws_r', 'ws_r') ON CONFLICT DO NOTHING")
            )
            await conn.execute(
                text(
                    "INSERT INTO display_section_recipe (page, section_key, workspace_id, h1, position, "
                    "allowed_field_keys, restricted, default_open, instruction_version) VALUES "
                    "('contact', 'openers', 'ws_r', 'Openers', 2, ARRAY['contact.facet.hobby'], false, true, 'v1-ws')"
                )
            )
            rows = await read_recipes(conn, "contact", workspace_id="ws_r")
            openers = next(r for r in rows if r.section_key == "openers")
            assert openers.allowed_field_keys == ("contact.facet.hobby",)
            assert openers.instruction_version == "v1-ws"
            assert [r.h1 for r in rows] == EXPECTED_H1S["contact"]
            system = await read_recipes(conn, "contact", workspace_id="ws_other")
            assert next(r for r in system if r.section_key == "openers").instruction_version == "v1"

    run_async(_run())
```

Run: `uv run pytest tests/arv2/display/test_recipes.py -q` → FAIL (module missing).

- [ ] **Step 3: Write `recipes.py` (the S4 content)**

The allowed keys per section. Every key below is registered today (108 rows in `field_definition` after the packs + `ARV2_PACK`); if the static test names one that is not, fix the recipe, never register a new field from here.

```python
"""S4 CONTENT — the section recipes: which field keys feed which section of which page.

Owned by Shashank after D2 (ARV2-WORK-SPLIT.md §1.1). Recipes are config: the system rows here
are upserted into ``display_section_recipe`` with ``workspace_id = ''``; a workspace row with the
same ``(page, section_key)`` overrides the system row for that workspace. A custom variable is one
more key appended to a recipe. Machinery lives in the sibling modules, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

Page = Literal["overview", "insights", "contact"]
PAGES: tuple[Page, ...] = ("overview", "insights", "contact")
RECIPE_VERSION = 1
RESTRICTED_SECTION_KEYS = frozenset({"context-only", "watch-outs", "do-not-mention"})


@dataclass(frozen=True)
class SectionRecipe:
    page: Page
    section_key: str
    h1: str
    position: int
    allowed_field_keys: tuple[str, ...]
    restricted: bool = False
    default_open: bool = False
    instruction_version: str = "v1"
    narrative: bool = False  # code-side: prose goes to intro[] (what-they-do, why-they-fit)
    workspace_id: str = ""


_UNSAFE_CONTEXT = ("account.reputation_risk", "account.resonance.attrition_signal")

SYSTEM_RECIPES: tuple[SectionRecipe, ...] = (
    # ---- insights -----------------------------------------------------------------------------
    SectionRecipe("insights", "buying-signals", "Buying signals", 0, (
        "account.open_requisitions", "account.hiring_velocity", "account.abm_program_maturity",
        "account.strategic_moves", "account.operational_pain", "account.resonance.buying_culture",
    ), default_open=True),
    SectionRecipe("insights", "money-and-momentum", "Money & momentum", 1, (
        "account.recent_funding", "account.total_funding", "core.annual_revenue", "core.revenue_band",
    )),
    SectionRecipe("insights", "tools-they-already-use", "Tools they already use", 2, (
        "account.gtm_tooling_stack", "core.primary_tech_stack", "core.tech_stack_categorised",
        "contact.facet.publications",
    )),
    SectionRecipe("insights", "how-they-sell", "How they sell, and who they win", 3, (
        "account.named_customers", "account.claimed_customer_logos", "account.claimed_outcomes_metrics",
        "account.resonance.public_frustrations", "account.resonance.eng_blog_tone",
    )),
    SectionRecipe("insights", "contact-insights", "Contact insights", 4, (
        "contact.persona", "contact.current_title", "contact.facet.recent_post",
        "contact.facet.publications", "contact.facet.voice_quote", "contact.facet.certifications",
        "contact.facet.career_history",
    )),
    SectionRecipe("insights", "context-only", "Context only", 5, _UNSAFE_CONTEXT, restricted=True),
    # ---- overview -----------------------------------------------------------------------------
    SectionRecipe("overview", "what-they-do", "What they do", 0, (
        "core.company_about", "account.product_packaging", "account.claimed_outcomes_metrics",
        "account.named_customers", "core.founded_year", "core.hq_location", "core.employee_count",
        "core.industry", "account.total_funding", "account.recent_funding",
    ), default_open=True, narrative=True),
    SectionRecipe("overview", "why-they-fit", "Why they fit", 1, (
        "core.hq_location", "account.recent_funding", "account.total_funding",
        "account.open_requisitions", "account.hiring_velocity", "account.abm_program_maturity",
        "account.gtm_tooling_stack", "account.named_customers", "account.operational_pain",
        "core.employee_count", "contact.current_title",
    ), default_open=True, narrative=True),
    SectionRecipe("overview", "why-now", "Why now", 2, (
        "account.open_requisitions", "account.hiring_velocity", "account.strategic_moves",
        "account.recent_funding", "account.abm_program_maturity",
    )),
    SectionRecipe("overview", "buying-committee", "Buying committee", 3, (
        "contact.persona", "contact.role_on_committee", "contact.current_title",
        "contact.facet.certifications", "contact.facet.career_history", "contact.network_statistics",
    )),
    SectionRecipe("overview", "how-to-approach", "How to approach", 4, (
        "contact.persona", "contact.role_on_committee", "contact.current_title",
        "contact.facet.certifications", "account.gtm_tooling_stack", "account.abm_program_maturity",
        "account.claimed_outcomes_metrics", "account.named_customers", "account.open_requisitions",
        "account.hiring_velocity", "account.resonance.buying_culture",
    )),
    SectionRecipe("overview", "watch-outs", "Watch-outs", 5, _UNSAFE_CONTEXT, restricted=True),
    # ---- contact ------------------------------------------------------------------------------
    SectionRecipe("contact", "why-this-person", "Why this person", 0, (
        "contact.current_title", "contact.persona", "contact.role_on_committee", "contact.headline",
        "contact.job_function", "contact.job_level", "contact.facet.career_history",
        "contact.facet.publications", "contact.facet.self_summary",
        "account.open_requisitions", "account.abm_program_maturity",
    ), default_open=True),
    SectionRecipe("contact", "problem-right-now", "Their problem right now", 1, (
        "account.abm_program_maturity", "account.hiring_velocity", "account.open_requisitions",
        "account.gtm_tooling_stack", "account.operational_pain",
        "contact.facet.recent_post", "contact.facet.publications",
    ), default_open=True),
    SectionRecipe("contact", "openers", "Openers", 2, (
        "contact.facet.hobby", "contact.facet.voice_quote", "contact.facet.recent_post",
        "contact.facet.publications", "contact.facet.career_history", "contact.facet.hooks",
        "contact.facet.openers", "contact.member_badges", "account.abm_program_maturity",
    ), default_open=True),
    SectionRecipe("contact", "angles", "Angles", 3, (
        "contact.facet.publications", "contact.facet.voice_quote", "contact.facet.recent_post",
        "contact.facet.stated_interests", "contact.facet.communication_style",
        "contact.facet.conference_talk", "contact.facet.public_appearances", "contact.facet.hooks",
        "account.claimed_outcomes_metrics", "account.gtm_tooling_stack", "account.operational_pain",
        "account.open_requisitions",
    )),
    SectionRecipe("contact", "do-not-mention", "Do not mention", 4, _UNSAFE_CONTEXT,
                  restricted=True, default_open=True),
)
```

Then `recipes_for`, `load_display_recipes` (one `INSERT … ON CONFLICT (page, section_key, workspace_id) DO UPDATE` per system row, `workspace_id = ''`), and `read_recipes` (SELECT both `workspace_id IN ('', :ws)`; build the system list, replace by `section_key` where a workspace row exists, keep the system `narrative` flag by `section_key`, order by `position`). Rows read from the database become `SectionRecipe` with `narrative` looked up from the system tuple by `section_key`.

- [ ] **Step 4: Wire the seeder**

In `platform/api/clue_api/arv2_wiring.py::register_arv2_wiring`, append `load_display_recipes` after `load_arv2_pack` (guard against double-append like the existing code does). The `display_section_recipe` table exists from `65fb2128c904`, so the loader path (`answer_key_loader._load_packs`) and the fleet/projections entrypoints seed it for free.

`display/__init__.py`: export `SectionRecipe, SYSTEM_RECIPES, RECIPE_VERSION, PAGES, RESTRICTED_SECTION_KEYS, recipes_for, load_display_recipes, read_recipes` (later tasks extend it).

- [ ] **Step 5: Run the tests and the import guard**

Run: `set -a; source .env; set +a; uv run pytest tests/arv2/display/test_recipes.py tests/arv2/test_settings.py tests/arv2/test_import_guard.py -q` → PASS. Also `uv run ruff check platform/api/clue_api/arv2/display tests/arv2/display && uv run ruff format --check platform/api/clue_api/arv2/display tests/arv2/display`.

- [ ] **Step 6: Seed the recipes into the worktree DB and commit**

```bash
set -a; source .env; set +a
uv run python - <<'EOF'
import asyncio
from clue_db import db_lifespan
from clue_api.arv2.display.recipes import load_display_recipes
async def main():
    async with db_lifespan("postgresql+asyncpg://clue:clue@localhost:55060/clue") as engine:
        async with engine.begin() as conn:
            await load_display_recipes(conn)
asyncio.run(main())
EOF
psql postgresql://clue:clue@localhost:55060/clue -Atc "select page, count(*) from display_section_recipe group by 1 order by 1"
git add libs/clue-config/clue_config/settings.py .env.example tests/arv2/test_settings.py platform/api/clue_api/arv2/display platform/api/clue_api/arv2_wiring.py tests/arv2/display
git commit -m "feat(arv2 d2): display settings + the S4 section recipes as config rows"
```

---

### Task 2: Prompts (S4 content), value rendering, the alias payload, near-duplicate dedupe

**Files:**
- Create: `platform/api/clue_api/arv2/display/prompts.py`, `platform/api/clue_api/arv2/display/render.py`
- Test: `tests/arv2/display/test_prompts.py`, `tests/arv2/display/test_render.py`

**Interfaces:**
- Consumes: `SectionRecipe`, `recipes_for` (Task 1); `clue_core.Claim`; `clue_api.arv2.text.normalize_for_match`.
- Produces (`render.py`):
  - `def render_value_text(field_key: str, value_json: object) -> str` — a string is itself; an object with `text` returns `text` (the D1 media wrap); an object renders as `"key: value; key: value"` over sorted keys, skipping `None`/empty, nested lists joined with ", ", nested objects rendered recursively; a list renders its items joined with "; "; numbers/bools `str()`; result whitespace-collapsed, max 1200 chars with "…".
  - `@dataclass(frozen=True) class DisplayClaim: claim_id: str; field_key: str; value: str; quote: str | None; observed_at: str | None (ISO date); priority: int; outreach_safe: bool; subject: str | None; media_timestamp: str | None; use_class: str | None; source_url: str | None (never sent to the model); entity_id: str; extraction_method: str; source_key: str | None; collected_at: datetime`
  - `def display_claim(claim: Claim, *, subject: str | None) -> DisplayClaim`
  - `def dedupe_near_duplicates(claims: Sequence[DisplayClaim], *, threshold: float = 0.7) -> tuple[list[DisplayClaim], dict[str, str]]` — returns kept claims and `{dropped_id: kept_id}` (decision 6).
  - `def alias_table(claims: Sequence[DisplayClaim]) -> tuple[list[dict[str, object]], dict[str, str]]` — payload rows `{"id": "c1", "fieldKey", "value", "quote", "observedAt", "priority", "outreachSafe", "subject", "mediaTimestamp"}` (omit `None` values) in the order priority asc, field_key, collected_at asc, claim_id; and `{"c1": claim_id}`.
- Produces (`prompts.py`): `PROMPT_VERSION = "display-v1"`, `SYSTEM_PROMPT: str`, `FIXED_LINES: tuple[str, str, str]`, `SECTION_INSTRUCTIONS: dict[tuple[str, str], str]` (one per `(page, section_key)`), `RESPONSE_FORMAT = {"type": "json_object"}`, `def section_descriptor(recipe) -> dict`, `def build_messages(*, page, subject: Mapping, client: Mapping, recipes: Sequence[SectionRecipe], target: SectionRecipe, claim_rows: Sequence[Mapping], forbidden_aliases: Sequence[str] = ()) -> list[dict[str, str]]` — `[{"role":"system", …}, {"role":"user", …}]` where the user content is `PREFIX + SUFFIX`: prefix = `# PAGE\n{json page/subject/client}\n\n# ALL SECTIONS OF THIS PAGE (context only — you will be told which one to write)\n{json descriptors}\n\n# CLAIMS (this is everything you know)\n{json claim_rows}`; suffix = `\n\n# WRITE ONLY THIS SECTION NOW: {key}\n{json descriptor with instruction}\n{regenerate line if forbidden_aliases}\nReturn {"section": <this one section>}.`; `def prefix_of(messages) -> str` (the user content up to `# WRITE ONLY THIS SECTION NOW`) for the stable-prefix test.

- [ ] **Step 1: Failing tests**

`tests/arv2/display/test_prompts.py`:

```python
from clue_api.arv2.display.prompts import (
    FIXED_LINES, PROMPT_VERSION, SECTION_INSTRUCTIONS, SYSTEM_PROMPT, build_messages, prefix_of,
)
from clue_api.arv2.display.recipes import SYSTEM_RECIPES, recipes_for

CLIENT = {"name": "Clue", "what_we_sell": "AI-native ABM"}
SUBJECT = {"kind": "contact", "name": "Nick Fisher", "persona": "economic_buyer", "account": "Zafran Security"}
ROWS = [{"id": "c1", "fieldKey": "contact.facet.hobby", "value": "cocktail YouTuber", "priority": 1, "outreachSafe": True}]


def test_the_three_fixed_lines_are_in_the_system_prompt() -> None:
    assert len(FIXED_LINES) == 3
    for line in FIXED_LINES:
        assert line in SYSTEM_PROMPT
    assert "17 June 2026" in SYSTEM_PROMPT
    assert "at most once per page" in SYSTEM_PROMPT.lower() or "at most once" in SYSTEM_PROMPT
    assert "never" in SYSTEM_PROMPT.lower() and "url" in SYSTEM_PROMPT.lower()
    assert PROMPT_VERSION == "display-v1"


def test_every_recipe_has_an_instruction() -> None:
    assert {(r.page, r.section_key) for r in SYSTEM_RECIPES} == set(SECTION_INSTRUCTIONS)
    for (page, key), instruction in SECTION_INSTRUCTIONS.items():
        assert len(instruction) > 40, (page, key)
        if page == "contact" and key not in {"do-not-mention"}:
            assert "sendLine" in instruction, (page, key)
        if key == "why-they-fit":
            assert "fitDisposition" in instruction
        if key in {"what-they-do", "why-they-fit"}:
            assert "intro" in instruction


def test_prefix_is_identical_across_sections_and_only_the_suffix_changes() -> None:
    recipes = recipes_for("contact")
    a = build_messages(page="contact", subject=SUBJECT, client=CLIENT, recipes=recipes, target=recipes[0], claim_rows=ROWS)
    b = build_messages(page="contact", subject=SUBJECT, client=CLIENT, recipes=recipes, target=recipes[2], claim_rows=ROWS)
    assert a[0] == b[0] and a[0]["role"] == "system"
    assert prefix_of(a) == prefix_of(b)
    assert a[1]["content"] != b[1]["content"]
    assert "# WRITE ONLY THIS SECTION NOW: openers" in b[1]["content"]
    assert "http" not in a[1]["content"].lower()


def test_regenerate_line_names_the_forbidden_aliases() -> None:
    recipes = recipes_for("contact")
    m = build_messages(page="contact", subject=SUBJECT, client=CLIENT, recipes=recipes, target=recipes[2], claim_rows=ROWS, forbidden_aliases=["c7", "c9"])
    assert "c7, c9" in m[1]["content"] and "must not appear" in m[1]["content"]
```

`tests/arv2/display/test_render.py`:

```python
from datetime import UTC, datetime
from clue_api.arv2.display.render import DisplayClaim, alias_table, dedupe_near_duplicates, render_value_text


def test_media_wrapped_values_render_their_text() -> None:
    assert render_value_text("contact.facet.voice_quote", {"text": "It is a side hobby", "media_url": "https://x", "media_timestamp": "00:05"}) == "It is a side hobby"


def test_objects_and_lists_render_deterministically_without_urls_leaking_as_keys() -> None:
    v = {"what": "Cisco acquisition rumor", "status": "REFUTED", "empty": None}
    assert render_value_text("account.reputation_risk", v) == "status: REFUTED; what: Cisco acquisition rumor"
    assert render_value_text("x", ["a", {"b": 1}]) == "a; b: 1"
    assert render_value_text("x", 42) == "42"
    assert len(render_value_text("x", "y" * 5000)) <= 1201


def _dc(i: str, value: str, *, safe: bool = True, quote: str | None = None, field: str = "contact.facet.hobby", ts: int = 0) -> DisplayClaim:
    return DisplayClaim(claim_id=i, field_key=field, value=value, quote=quote, observed_at=None, priority=2, outreach_safe=safe, subject=None, media_timestamp=None, use_class=None, source_url=None, entity_id="e", extraction_method="api", source_key=None, collected_at=datetime(2026, 9, 1, tzinfo=UTC).replace(second=ts))


def test_near_duplicates_collapse_within_a_flag_group_but_not_across() -> None:
    a = _dc("a", "cocktail YouTuber (side hobby)")
    b = _dc("b", "Cocktail YouTuber, a side hobby, creator of the Cocktail Chemistry channel", quote="long quote here", ts=1)
    c = _dc("c", "Hosts Cocktail Chemistry videos as a side hobby, runs Patreon for support", safe=False)
    kept, dropped = dedupe_near_duplicates([a, b, c])
    assert {k.claim_id for k in kept} == {"b", "c"}
    assert dropped == {"a": "b"}


def test_alias_table_is_stable_and_never_carries_urls() -> None:
    rows, aliases = alias_table([_dc("z", "v1", ts=2), _dc("y", "v2", ts=1)])
    assert [r["id"] for r in rows] == ["c1", "c2"] and aliases == {"c1": "y", "c2": "z"}
    assert all("source_url" not in r and "sourceUrl" not in r for r in rows)
```

Run both → FAIL (modules missing).

- [ ] **Step 2: Write `prompts.py` (S4 content)**

`SYSTEM_PROMPT` starts from the control test's `SYSTEM` (`.context/display-layer-control-test/control_test.py:150`) with these changes, in this order:

1. Rule 3 becomes: "Every sentence lists the claim aliases (`c1`, `c2`, …) it is built from in `claimIds`. Never write a sentence with no claimId. Never type a claim alias, a URL or a domain name inside `h2`, `text` or `sendLine.text` — the frontend renders sources from `claimIds`."
2. Rule 2 keeps the verbatim rule and states: "`sendLine` is a separate field, never inside quotation marks in `text`."
3. Add the three FIXED_LINES verbatim as rules 8–10:
   - `FIXED_LINES[0] = "Never type claim ids or aliases into prose; they belong only in the claimIds arrays."`
   - `FIXED_LINES[1] = 'Write every date in words, as "17 June 2026"; never 2026-06-17 or 06/17/2026.'`
   - `FIXED_LINES[2] = "Use the personal-hobby hook at most once per page; if another section of this page already opens with it, do not."`
4. Add rule 11: "Optionally split a sentence into `segments` (clauses, each with its own claimIds); the segment texts joined with a space must equal the sentence text exactly."
5. The OUTPUT shape: `{"section":{"key":"<key>","empty":false,"intro":[{"text":"…","claimIds":["c1"]}],"items":[{"h2":"…","body":[{"text":"…","claimIds":["c1"],"segments":[…]}],"sendLine":{"channel":"In your email","text":"…","claimIds":["c1"]},"contactRefs":[{"name":"…"}],"subject":{"name":"…"},"fitDisposition":"support","priority":1}]}}` with the notes: `intro` only when the instruction asks for it; `sendLine` only where the instruction asks and `null` otherwise; `subject` only in Contact insights; `fitDisposition` only in Why they fit; `priority` 1|2|3 from the strongest claim used; `h2` ≤ 110 characters; body 2–5 sentences; return ONLY JSON.

`SECTION_INSTRUCTIONS` — one entry per `(page, section_key)`, each a paragraph. Write them from `frontend-page-content/README.md` §2–3 and the ZAFRAN-PAGES / FRONTEND-SPEC section bodies, in this voice (the operator has 15 seconds). Contact sections end with the sendLine rule and its channel label; restricted sections say what they are for. Required content per section:
- insights/buying-signals: hiring, requisitions, ABM maturity, strategic moves, buying culture; each item ends its body with "What it means for us: …"; name people in `contactRefs` when a claim names them.
- insights/money-and-momentum: funding rounds, totals, revenue band; dates in words.
- insights/tools-they-already-use: named tools, explicit absences ("no ABM platform named"), tool mentions in publications.
- insights/how-they-sell: named customers, proof points, target buyer, public frustrations; numbers verbatim.
- insights/contact-insights: one item per committee member, `subject: {"name": …}` set on each, h2 = the one thing about them; use only that person's claims for the item.
- insights/context-only: "Every fact here is `outreachSafe: false`. Write one item per fact: what it is, why it must not be used, in one or two sentences. No sendLine."
- overview/what-they-do: "Write `intro` as two paragraphs of prose (each paragraph one `intro` entry, 2–4 sentences, every sentence cited): what they sell and to whom, then founding/HQ/size/funding/customers. `items` must be `[]`."
- overview/why-they-fit: "Write `intro` as one sentence naming the overall picture, then one item per fit criterion; set `fitDisposition` to `support` for a satisfied criterion and `caveat` for an honest negative; h2 states the criterion."
- overview/why-now: "At most three items, the three strongest time-bound reasons, ordered by urgency; each body says what changed and when (dates in words)."
- overview/buying-committee: "One item per person, `contactRefs` = that person; h2 = name, title and persona in words; body = why they matter for this purchase."
- overview/how-to-approach: "Items: Lead with whom; The message; The proof to show; Tier and channels; Timing — only those the claims support."
- overview/watch-outs: same text as context-only.
- contact/why-this-person: role in the deal, category experience, how they think; every body ends with a use line as `sendLine` with channel `In your email` (or `In the platform` when it is advice to the operator rather than copy).
- contact/problem-right-now: the account's pain seen from this seat; `sendLine` channel `In your email`.
- contact/openers: "Each item is one opener; h2 names it; body explains why it is safe and strong; `sendLine` is the exact line to paste with channel `In your email`. The hobby opener, if any, once, first line only, never in the subject."
- contact/angles: "Each item is one channel angle: direct mail (`In the direct-mail brief`), landing page (`On the landing page` or `Brief the design agent with`), content, event (`For the event`); `sendLine` carries the brief."
- contact/do-not-mention: "Every fact here is `outreachSafe: false` for this person or their account; one item per fact; no sendLine. Add one final item without claims is NOT allowed — every item cites."

`build_messages` composes exactly as the interface says; `prefix_of` returns the user content split on `"\n\n# WRITE ONLY THIS SECTION NOW"`.

- [ ] **Step 3: Write `render.py`**

`render_value_text` per the interface; `display_claim(claim, subject=)` maps `Claim` → `DisplayClaim` (`quote = claim.evidence_span`, `observed_at` → ISO date string or `None`, `media_timestamp` from an object value's `media_timestamp`, `priority = claim.signal_priority`, `use_class = str(claim.use_class) if claim.use_class else None`). `dedupe_near_duplicates`: group by `(field_key, outreach_safe)`; normalise with `normalize_for_match(value)`; within a group, greedy: iterate claims sorted by (len(quote or "") desc, collected_at asc, claim_id); a candidate is dropped when for some kept claim in the group `a in b or b in a` (normalised, both non-empty) or `jaccard(tokens(a), tokens(b)) >= threshold`. `alias_table` per the interface.

- [ ] **Step 4: Run tests, lint, commit**

`uv run pytest tests/arv2/display/test_prompts.py tests/arv2/display/test_render.py -q` → PASS; ruff clean.

```bash
git add platform/api/clue_api/arv2/display/prompts.py platform/api/clue_api/arv2/display/render.py tests/arv2/display/test_prompts.py tests/arv2/display/test_render.py platform/api/clue_api/arv2/display/__init__.py
git commit -m "feat(arv2 d2): the S4 section prompts, value rendering, alias payload, near-duplicate dedupe"
```

---

### Task 3: Gather — subjects, committee expansion, the recipe input filter (DB)

**Files:**
- Create: `platform/api/clue_api/arv2/display/gather.py`
- Test: `tests/arv2/display/test_gather_db.py`

**Interfaces:**
- Consumes: `read_recipes`/`SectionRecipe` (T1); `display_claim`, `dedupe_near_duplicates`, `DisplayClaim` (T2); `clue_research.claimstore.claims_for_entities`, `clue_research.claimstore.tenancy.WorkspaceScope`; `clue_config.Settings`.
- Produces:
  - `@dataclass(frozen=True) class SubjectRef: kind: Literal["account","contact"]; id: str (uuid str); name: str; account_id: str; account_name: str; account_domain: str | None; persona: str | None = None; title: str | None = None` and `def to_prompt(self) -> dict` (`{"kind","name","persona"?,"title"?,"account"}` — no ids).
  - `@dataclass(frozen=True) class ClientContext: name: str; what_we_sell: str` + `def to_prompt(self) -> dict`.
  - `async def resolve_subject(conn, *, workspace_id, kind, subject_id) -> SubjectRef` — account: `account_entity` (`canonical_name`, `primary_domain`); contact: `contact_entity` join `account_entity`; `persona` = latest live `contact.persona` claim value (string), `title` = latest live `contact.current_title`. Raises `SubjectNotFound(Arv2Error)` (define in gather.py) when the row is not in the workspace.
  - `async def client_context(conn, *, workspace_id, settings) -> ClientContext` — `brand.name` for the workspace (first by `created_at`), else the workspace name; `what_we_sell = settings.arv2_display_client_pitch`.
  - `async def committee_members(conn, *, workspace_id, account_id) -> list[SubjectRef]` — decision 5.
  - `@dataclass(frozen=True) class SectionInput: recipe: SectionRecipe; claims: tuple[DisplayClaim, ...]; deduped: Mapping[str, str]; excluded_sensitive: int; excluded_unsafe: int; excluded_unverified: int` and property `empty -> bool`.
  - `async def gather_section_inputs(conn, *, workspace_id, subject: SubjectRef, recipes: Sequence[SectionRecipe], people: Sequence[SubjectRef], settings) -> list[SectionInput]` — ONE `claims_for_entities` read for all entities involved (subject + account for a contact page + `people` for an account page) with no field filter, then per recipe: pick claims by decision 4 (restricted: all unsafe claims of subject (+account for contact) ∪ allowed keys any flag; else allowed keys, safe only); apply verification-posture exclusion (decision 1) and the sensitive exclusion; `contact.*` keys on an account page come from `people`, on a contact page from the subject; `account.*`/`core.*` keys from the account; set `subject` on each `DisplayClaim` to the person's name for contact claims (and `None` for account claims); dedupe; sort by (priority, field_key, collected_at).

- [ ] **Step 1: Failing DB test**

`tests/arv2/display/test_gather_db.py` seeds through `LenientClaimWriter` inside `rollback_conn(seed_pack=False)` after `load_core_pack`, `load_deep_profiling_pack`, `load_committee_pack`, `load_arv2_pack`, `load_display_recipes` (import each directly in the test — the test is not bound by the lane's import guard). Seed: workspace `ws_g` (`seed_workspace`), a `brand` row (`INSERT INTO brand (brand_id, workspace_id, name) …` — check the table's NOT NULL columns first with `\d brand` and fill them), account "Zafran Security" `zafran.io`, contacts Nick (persona `economic_buyer`, title "VP of Marketing") and Vari (persona `champion`), claims:
  - account `account.open_requisitions` (safe, P1), `account.reputation_risk` (unsafe, P3, object value), `account.recent_funding` ×2 near-duplicate safe values, one `contact.facet.hobby` for Nick safe + one unsafe twin, one `contact.facet.voice_quote` media-wrapped for Nick, one `contact.facet.hobby` for Nick with `use_class=SENSITIVE` (`identity_binding=STRONG`), a tier-4 `llm_synthesis` `account.strategic_moves` (unverified).
  Assertions:
  - `resolve_subject` for Nick returns persona/title/account name; unknown id raises `SubjectNotFound`.
  - `committee_members` without a coverage row returns Nick and Vari (both have claims) and not a contact with zero claims.
  - `gather_section_inputs` for the contact page: `openers` contains the safe hobby and the voice quote (value == the wrapped `text`), not the unsafe twin, not the sensitive one; `do-not-mention` contains the unsafe twin and the account's `reputation_risk`, not the sensitive one; `problem-right-now` contains `account.open_requisitions` with `subject is None`.
  - For the account overview: `why-now` contains one `recent_funding` (deduped, `deduped` maps the dropped id) and, with `Settings(_env_file=None, verification_enabled=True)`, excludes `account.strategic_moves` (`excluded_unverified == 1`); with `verification_enabled=False` includes it. `buying-committee` carries Nick's and Vari's persona claims with `subject` set to their names.
  - `client_context` returns the brand name and the settings pitch.

- [ ] **Step 2: Implement `gather.py`**; **Step 3:** run `uv run pytest tests/arv2/display/test_gather_db.py -q` → PASS; import guard + ruff; commit `feat(arv2 d2): gather — subjects, committee expansion, the recipe input filter`.

---

### Task 4: The Luna section runner and the floor

**Files:**
- Create: `platform/api/clue_api/arv2/display/runner.py`, `platform/api/clue_api/arv2/display/floor.py`
- Test: `tests/arv2/display/test_runner.py`, `tests/arv2/display/test_floor.py`

**Interfaces:**
- Consumes: `build_messages`, `RESPONSE_FORMAT`, `PROMPT_VERSION` (T2); `alias_table`, `DisplayClaim` (T2); `SectionInput`, `SubjectRef`, `ClientContext` (T3); `ProviderCaller`, `CallSpec`, `SpendEstimate`, `CallCost` (`calls.py`); `openrouter_chat_request/_cost_reader/_halt_rule/_message_text` (`openrouter.py`); `parse_reply_text`-style parsing (write a local `_parse_json_object(text, raw_ref)` raising `RawParseError`, or import `clue_api.arv2.structuring_client.parse_reply_text`).
- Produces (`runner.py`):
  - Pydantic reply models (`extra="ignore"`): `ReplySentence {text: str; claimIds: list[str] = []; segments: list[ReplySegment] | None = None}`, `ReplySegment {text; claimIds}`, `ReplySendLine {channel: str; text: str; claimIds: list[str] = []}`, `ReplyRef {name: str}`, `ReplyItem {h2: str; body: list[ReplySentence]; sendLine: ReplySendLine | None = None; contactRefs: list[ReplyRef] = []; subject: ReplyRef | None = None; fitDisposition: Literal["support","caveat"] | None = None; priority: int | None = None}`, `ReplySection {key: str | None = None; empty: bool = False; intro: list[ReplySentence] = []; items: list[ReplyItem] = []}`, `Reply {section: ReplySection}` (also accept the control-test shape `{"sections":[…]}` by taking the first).
  - `@dataclass(frozen=True) class SectionDraft: section_key: str; intro: list[dict]; items: list[dict]; cited_claim_ids: list[str]; checks: dict; cost: CallCost | None; model: str; raw_refs: tuple[str, ...]` — items already in the **wire shape** (`id`, `h2`, `body[{text, claimIds, segments?}]`, `sendLine|null`, `contactRefs[{accountId, contactId, name, title?, persona?}]`, `subject?`, `fitDisposition?`, `priority`, `newSinceLastVisit: False`), uuids not aliases.
  - `class LunaSectionRunner: __init__(self, caller: ProviderCaller, *, api_key: SecretStr, base_url: str, model: str, timeout_s: float)`; `def write_section(self, *, page, subject: SubjectRef, client: ClientContext, recipes, section: SectionInput, people: Sequence[SubjectRef], forbidden_aliases: Sequence[str] = ()) -> SectionDraft` — builds `alias_table`, `build_messages`, `openrouter_chat_request(response_format=RESPONSE_FORMAT, max_tokens=DISPLAY_MAX_TOKENS=16000, timeout_s)` with **no `reasoning` and no `temperature`** (default effort — constraint 7), `CallSpec(provider="openrouter", operation="chat/completions", label=f"display-{page}-{section_key}", estimate=SpendEstimate(usd=DISPLAY_ESTIMATE_USD=Decimal("0.02")), extras={"page","section_key","subject_kind","subject_id"})`; parses; on `ValidationError`/`RawParseError` retries the call once (a second `CallSpec`, same messages) and if still bad returns a draft with `items=[]`, `checks["reply_invalid"]=True` (never raises for a bad reply; `ProviderHalted`/`ProviderTransportError` propagate); then `materialise(reply, section, aliases, people, subject)`:
    - alias → uuid on every `claimIds`; unknown aliases removed and counted in `checks["unknown_aliases"]`; ids whose claim is not in `section.claims` counted in `checks["off_recipe"]` and removed;
    - `segments` kept only if `" ".join(seg.text) == sentence.text` (else dropped, counted `checks["segments_dropped"]`);
    - `priority = min(claim.priority for cited claims)` else the model's value clipped to 1..3 else 3;
    - `contactRefs`/`subject` names resolved case-insensitively against `people` + the subject (`{accountId, contactId, name, title?, persona?}`); unresolved names dropped, counted `checks["unresolved_refs"]`;
    - `sendLine` kept only on `page == "contact"` and when text non-empty; `fitDisposition` kept only for `why-they-fit`; `intro` kept only when `recipe.narrative`;
    - `id = f"{section_key}-{n}"` (1-based);
    - `cited_claim_ids` = union over intro/body/segments/sendLine; `checks["uncited_sentences"]` count;
    - `checks["aliases"] = len(aliases)`, `checks["prompt_version"] = PROMPT_VERSION`.
- Produces (`floor.py`):
  - `@dataclass(frozen=True) class FloorReport: unsafe_outside_restricted: tuple[str, ...] (claim ids); offending_item_ids: tuple[str, ...]; ok: bool`
  - `def check_floor(draft: SectionDraft, section: SectionInput) -> FloorReport` — an id is a violation when `not section.recipe.restricted` and the claim's `outreach_safe is False` (look up in `section.claims` by id; ids not in the input were already removed by the runner).
  - `def apply_floor(draft, report) -> SectionDraft` — remove offending items (and offending intro sentences), recompute `cited_claim_ids`, set `checks["floor_dropped_items"]`.
  - `def verbatim_annotations(draft, section) -> dict` — for every span between straight or curly double quotes with ≥4 words in `h2`/`text`/`sendLine.text`: `substring_verdict(span, corpus)` where corpus = joined `value` + `quote` of the item's cited claims; counts `{"quotes": n, "exact": n, "partial": n, "not_found": n, "numbers": n, "numbers_missing": n}` where numbers are integers ≥ 13 in the text (commas stripped) not present in the corpus digits. Called by the page layer only when `settings.evidence_verbatim_check == "on"`; stored under `checks["verbatim"]`, else `checks["verbatim"] = None`.
  - `def forbidden_aliases_for(report, aliases_by_id: Mapping[str, str]) -> list[str]`.

- [ ] **Step 1: Failing tests** with `ScriptedTransport` + `MemoryRawSink` + `MemoryLedger`: build a `ProviderCaller(transport=ScriptedTransport([...]), raw_sink=MemoryRawSink(), ledger=MemoryLedger(), now=lambda: datetime.now(UTC))`; craft an OpenRouter-shaped 200 body `{"id":"gen-1","choices":[{"message":{"content": json.dumps(reply)}}],"usage":{"cost":0.0044}}` (look at `test_structuring_client.py` for the exact body shape the cost reader expects). Tests:
  - the request body has `model`, `usage.include`, `response_format`, no `reasoning`, no `temperature`; label is `display-contact-openers`; `draft.cost.cost_usd == Decimal("0.0044")`.
  - aliases resolve to uuids; unknown alias `c99` removed and counted; a claim outside the section input is counted `off_recipe` and removed; priority is the min claim priority; `contactRefs` "vari kaur" resolves to Vari's ids; `subject` resolves on `contact-insights`; `sendLine` dropped on an insights page; `fitDisposition` kept only on `why-they-fit`; ids are `openers-1`, `openers-2`.
  - a first invalid JSON reply then a valid one → two requests, one draft, `checks["reply_retried"] is True`; two invalid → `items == []`, `checks["reply_invalid"] is True`, no exception.
  - `check_floor` flags an unsafe claim cited in `openers` and not in `do-not-mention`; `apply_floor` drops the item and recomputes `cited_claim_ids`; `forbidden_aliases_for` returns the alias.
  - `verbatim_annotations`: a verbatim quote → `exact 1`; a paraphrase in quotes → `not_found 1`; the number 77 present, 999 missing → `numbers_missing 1`.

- [ ] **Step 2: Implement**; **Step 3:** `uv run pytest tests/arv2/display/test_runner.py tests/arv2/display/test_floor.py -q` → PASS; import guard; ruff; commit `feat(arv2 d2): the Luna section runner (one call, default effort, aliases) and the floor`.

---

### Task 5: Blocks, staleness, the evidence resolver (DB)

**Files:**
- Create: `platform/api/clue_api/arv2/display/blocks.py`, `platform/api/clue_api/arv2/display/evidence.py`
- Test: `tests/arv2/display/test_blocks_db.py`, `tests/arv2/display/test_evidence.py`

**Interfaces:**
- Consumes: `SectionRecipe`, `RECIPE_VERSION` (T1); `PROMPT_VERSION` (T2); `SectionDraft` (T4); `DisplayClaim`, `render_value_text` (T2); `clue_core.Claim`.
- Produces (`blocks.py`):
  - `@dataclass(frozen=True) class LiveBlock: display_block_id: str; section_key: str; body_json: dict; cited_claim_ids: tuple[str, ...]; model: str; prompt_version: str; recipe_version: int; generated_at: datetime`
  - `async def live_blocks(conn, *, workspace_id, subject_kind, subject_id, page) -> dict[str, LiveBlock]` (by section_key, `superseded_at IS NULL`).
  - `def block_body(draft: SectionDraft, section: SectionInput) -> dict` — decision 9: `{"intro", "items", "checks", "cited_flags": {id: outreach_safe}, "cost_usd": str|None, "call": {"ledger_row_id", "raw_ref", "provider_request_id"}|None}`.
  - `async def insert_block(conn, *, workspace_id, subject_kind, subject_id, page, recipe, draft, section, now) -> str` — `UPDATE display_block SET superseded_at = :now WHERE … AND section_key = :k AND superseded_at IS NULL` then `INSERT` (`model = draft.model`, `prompt_version = f"{PROMPT_VERSION}+{recipe.instruction_version}"`, `recipe_version = RECIPE_VERSION`, `cited_claim_ids = draft.cited_claim_ids::uuid[]`, `generated_at = :now`); returns the new id. Also `async def supersede_blocks(conn, *, workspace_id, subject_kind, subject_id, page, section_keys, now) -> int`.
  - `@dataclass(frozen=True) class Staleness: section_key: str; reasons: tuple[str, ...]` with reasons ∈ `{"new_claims", "superseded_citation", "flag_changed", "prompt_version", "recipe_version"}`.
  - `async def stale_sections(conn, *, workspace_id, subject_ids: Sequence[str], recipes, blocks: Mapping[str, LiveBlock]) -> list[Staleness]` — data-source-map §4 step 2 over **all** `subject_ids` (the subject plus its committee/account expansion): `EXISTS claim WHERE entity_id IN :ids AND field_key = ANY(:keys) AND workspace_id = :ws AND superseded_by IS NULL AND collected_at > :generated_at`; any cited id `superseded_by IS NOT NULL`; any cited id whose current `outreach_safe` differs from `cited_flags`; `block.prompt_version != f"{PROMPT_VERSION}+{recipe.instruction_version}"`; `block.recipe_version != RECIPE_VERSION`.
  - `def compose_display_block(page, recipes, blocks: Mapping[str, LiveBlock]) -> dict` — `{"page", "sections": [ResearchSection…]}` in recipe order: `key, h1, restricted, defaultOpen` from the recipe; `intro`, `items` from the block (or `[]`); `empty = block is None or (not items and not intro)`; no `emptyMessage`. Items pass through as stored (already wire-shaped). Also `def insight_summary(block: dict, committee_size: int) -> list[str]` → `[f"{n} insights", f"{m} people"]` (n = items across non-restricted sections).
- Produces (`evidence.py`): decision 8 — `source_domain(url) -> str | None`, `favicon_url(domain) -> str | None`, `@dataclass(frozen=True) class EvidenceRef` with the contract fields as snake_case + `def to_wire(self) -> dict` camelCase, `def resolve_evidence(claims: Sequence[Claim]) -> list[EvidenceRef]` (one per claim id, stable order by claim id), `async def evidence_for_ids(conn, *, workspace_id, claim_ids) -> list[EvidenceRef]` via `claims_by_ids` + `WorkspaceScope.for_workspace`.

- [ ] **Step 1: Failing tests.** `test_evidence.py` (pure): domain stripping (`https://www.YouTube.com/watch?v=1` → `youtube.com`), record kind for api+no url (`sourceUrl None`, `faviconUrl None`, `verificationKind "record"`), media-wrapped value → `quote` = evidence_span, `mediaTimestamp` from value, `researchExcerpt` only when `quote is None`, `verifiedAt` = ISO date of observed_at, `publishedAt` parses `value_json["published"]` `"2026-06-17"` else `None`, `to_wire` keys equal exactly `{"claimId","sourceUrl","sourceDomain","faviconUrl","title","quote","researchExcerpt"?,"publishedAt","verifiedAt","verificationKind","mediaTimestamp","provider","outreachSafe"}`. `test_blocks_db.py`: build a `SectionDraft` by hand (no model) for `openers` and insert; `live_blocks` returns it; inserting again supersedes (one live row, two rows total; partial unique index holds); `stale_sections` returns `[]` right after insert, then `new_claims` after a claim on an allowed key is written with a later `collected_at`, `superseded_citation` after `supersede_claim` on a cited id, `flag_changed` after `UPDATE claim SET outreach_safe = false` on a cited id, `prompt_version` when the recipe's `instruction_version` differs; `compose_display_block` yields 5 sections for the contact page with `empty` true for the four without blocks and `defaultOpen`/`restricted` from the recipes; `insight_summary` counts non-restricted items only.

- [ ] **Step 2: Implement**; **Step 3:** `uv run pytest tests/arv2/display/test_blocks_db.py tests/arv2/display/test_evidence.py -q` → PASS; import guard; ruff; commit `feat(arv2 d2): display_block persistence, recipe-scoped staleness, the evidence resolver`.

---

### Task 6: The page orchestrator, the activity event, the CLI

**Files:**
- Create: `platform/api/clue_api/arv2/display/page.py`, `scripts/generate_arv2_display.py`
- Modify: `platform/api/clue_api/arv2/display/__init__.py` (final exports)
- Test: `tests/arv2/display/test_page_db.py`

**Interfaces:**
- Consumes: everything above; `clue_config.Secrets`, `clue_config.GatewayConfig`; `FileRawSink`, `JsonlLedger`, `HttpxTransport`.
- Produces:
  - `RunnerFactory = Callable[[], LunaSectionRunner]` — `def default_runner_factory(settings: Settings, secrets: Secrets) -> RunnerFactory` (one `ProviderCaller` per runner: `HttpxTransport()`, `FileRawSink(Path(settings.arv2_raw_root)/"raw")`, `JsonlLedger(Path(settings.arv2_raw_root)/"ledger.jsonl")`, `now=lambda: datetime.now(UTC)`; api key `secrets.openrouter_api_key` (raise `Arv2Error("CLUE_OPENROUTER_API_KEY is unset")` when blank), `base_url = GatewayConfig().base_url`, `model = settings.arv2_display_model`, `timeout_s = settings.arv2_display_timeout_s`).
  - `@dataclass(frozen=True) class PageResult: page; subject: SubjectRef; display_block: dict (the wire shape); generated: tuple[str, ...]; regenerated: tuple[str, ...]; skipped_empty: tuple[str, ...]; stale_served: tuple[str, ...]; cost_usd: Decimal; checks: dict[str, dict]; evidence: list[dict] (wire); cited_claim_ids: tuple[str, ...]`
  - `async def ensure_page(conn, *, workspace_id, subject_kind, subject_id, page, settings, runner_factory, force: bool = False, regenerate_stale: bool = False) -> PageResult`:
    1. `subject = resolve_subject`; `client = client_context`; `recipes = read_recipes(page, workspace_id)`; `people = committee_members(account)` (account pages) or `[subject]` (contact page; also the contact's account is an expansion entity for restricted input).
    2. `blocks = live_blocks`; `stale = stale_sections(...)`; if `force`: every section is a miss (supersede all first); missing = recipes with no block (+ stale ones when `regenerate_stale`).
    3. `inputs = gather_section_inputs(...)` for the missing recipes; sections with `input.empty` → `skipped_empty` (no call, no block).
    4. Run the non-empty ones **in parallel**: `sem = asyncio.Semaphore(settings.arv2_display_max_parallel)`; each task: `runner = runner_factory()`; `draft = await asyncio.to_thread(runner.write_section, …)`; `report = check_floor(draft, input)`; if not ok: second `to_thread` call with `forbidden_aliases`, re-check, then `apply_floor`; if `settings.evidence_verbatim_check == "on"`: `checks["verbatim"] = verbatim_annotations(...)` else `None`; `checks["floor_regenerated"] = bool`.
    5. Persist each draft with `insert_block` (sequentially on `conn` — SQLAlchemy async connections are not shared across concurrent tasks; collect drafts first, then write), `record_page_written` (decision 12) once if anything was generated, `compose_display_block`, `evidence_for_ids` over the union of cited ids, return.
  - `async def record_page_written(conn, *, workspace_id, account_id, page, regenerated: bool, contact_id: str | None, now) -> None` — the `INSERT INTO account_activity_event` from decision 12 (`actor_kind='clue'`, `ref_json` with `contact_id` when given).
- `scripts/generate_arv2_display.py`: `--database-url` (required), `--workspace-id` (default `ws_arv2_answer_key`), `--account <domain>` (required), `--contact "<full name>"` (optional; selects the contact page), `--page overview|insights|contact|all` (default: `all` for an account = overview+insights; `contact` when `--contact` given), `--force`, `--regenerate-stale`, `--dry-run` (rollback), `--raw-root`. Prints JSON `{page: {display_block, generated, regenerated, skipped_empty, cost_usd, checks, evidence_count}}` and a one-line total cost. Uses `Settings()` + `Secrets()` (reads the local `.env`), `db_lifespan(url)`, one transaction, commit unless dry-run. Resolves `--account` → `account_entity.id` by `primary_domain` in the workspace; `--contact` → `contact_entity.id` by `full_name` under that account.

- [ ] **Step 1: Failing DB test** `test_page_db.py`: same seed as T3 (factor the seed into `tests/arv2/display/_seed.py` and import it from both tests); a `runner_factory` returning `LunaSectionRunner` over a `ScriptedTransport` whose script is a *function of the request* — implement a tiny `RoutingTransport` in the test that inspects `request` body's `# WRITE ONLY THIS SECTION NOW: <key>` and returns a canned reply per key (it is still the lane's one double, just keyed); include one reply that cites the unsafe twin inside `openers` on the first call and a clean one on the second. Assert: `ensure_page(contact)` → `generated` has the sections with input, `skipped_empty` names the ones without (e.g. `angles` if unseeded), `checks["openers"]["floor_regenerated"] is True`, no unsafe id cited outside `do-not-mention` in the composed block, `display_block["sections"]` in recipe order with `h1`s bare, one `account_activity_event` row `kind='summary'` for the account with `ref_json->>'contact_id'`, `evidence` has one entry per cited id and no `field_key`; second `ensure_page` → `generated == ()` and no new call (transport unused); write a new claim on an `openers` key → `stale_sections` reports it and `ensure_page(regenerate_stale=True)` regenerates only `openers` (one call) and the event says `regenerated`; `force=True` supersedes all live rows. Also `default_runner_factory` raises the typed error when the key is blank (`Secrets(_env_file=None, openrouter_api_key=SecretStr(""))`).

- [ ] **Step 2: Implement `page.py` and the script**; **Step 3:** `uv run pytest tests/arv2/display -q --ignore-glob='*_live.py'` → PASS; `uv run python scripts/generate_arv2_display.py --help`; import guard; ruff; mypy on the new package (`uv run mypy platform/api/clue_api/arv2/display` — must be clean); commit `feat(arv2 d2): page orchestrator (parallel sections, floor, persistence, activity) + generate_arv2_display CLI`.

---

### Task 7: Live exit gate, the three Zafran pages, records

**Files:**
- Create: `tests/arv2/display/test_display_live.py`
- Modify: `platform/api/clue_api/arv2/README.md` (a "D2 — the display module" section), `docs/specs/ARV2-MASTER-PLAN.md` §7 (a dated note: section keys = contract v1; live-claims-not-merge; aliases), `docs/specs/ARV2-DATA-SOURCE-MAP.md` §4 (replace "Gather `current_values(...)`" with the live-claims rule and a pointer to `display/gather.py`), `_memory/README.md`, create `_memory/2026-09-07-arv2-d2-display-module.md`.

- [ ] **Step 1: The live test** (skips without `CLUE_OPENROUTER_API_KEY`; skips when the answer key is not in the DB): inside `rollback_conn(seed_pack=False)`, `ensure_page` for **one** page — Nick Fisher's contact page (5 sections, ≈$0.03) — with `default_runner_factory(Settings(), Secrets())`; assert every section either generated or honestly empty, every `claimIds` entry is a uuid present in the evidence list, **zero** unsafe ids cited outside `do-not-mention` (`cited_flags` all true in non-restricted blocks), every contact-page item in `openers` has a `sendLine`, no `http` substring and no `c[0-9]+` alias pattern in any `h2`/`text`, `PageResult.cost_usd > 0`, and the ledger under `.artifacts/arv2/ledger.jsonl` gained `result` rows with `cost_source == "metered"`. Roll back (the persisted run is the script's job).

- [ ] **Step 2: Generate the three pages for real** against the worktree DB (persisted):

```bash
set -a; source .env; set +a
uv run python scripts/generate_arv2_display.py --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue --account zafran.io --page all > .artifacts/arv2/display-zafran-account.json
uv run python scripts/generate_arv2_display.py --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue --account zafran.io --contact "Nick Fisher" > .artifacts/arv2/display-nick-fisher.json
psql postgresql://clue:clue@localhost:55060/clue -Atc "select page, section_key, cardinality(cited_claim_ids), jsonb_array_length(body_json->'items'), (body_json->'checks'->>'floor_dropped_items') from display_block where superseded_at is null order by page, section_key"
psql postgresql://clue:clue@localhost:55060/clue -Atc "select count(*) from display_block b join lateral unnest(b.cited_claim_ids) c(id) on true join claim on claim.id = c.id where b.superseded_at is null and claim.outreach_safe = false and b.section_key not in ('context-only','watch-outs','do-not-mention')"
```

The last query must print `0` (the A4 exit gate). Record the per-page cost from the CLI output and the section counts in the memory note. Read the generated copy once for sanity (aliases in prose, dates in words, sendLines present) and record anything off as a follow-up — do not tune prompts in this task beyond fixing a defect that breaks the exit gate.

- [ ] **Step 3: Records.** README section (what each module owns, the eight decisions, how to run the script, the two S4 content files and who owns them); master plan + data source map notes; the memory note (tasks → commits, rulings, the real load numbers, cost, follow-ups: D3 wires `ensure_page` + `evidence_for_ids` into E2/E3/E5 and runs regeneration in the background; the 7-item standing-rule checklist result).

- [ ] **Step 4: Wider offline pass and close-out gate** (constraint 5): `uv run pytest tests/arv2 tests/claimstore tests/db/test_arv2_d1_migration.py tests/narrative/test_positioner.py -q --ignore-glob='*_live.py'` from this worktree (posture: the local `.env`), compare against the D1 close-out baseline (357 passed / 25 skipped / 1 known live-aggregate failure; the 12 known reds); `uv run ruff check . --statistics` (baseline 9), `uv run ruff format --check .` (10 pre-existing), `uv run mypy` (baseline: `ad_assets.py:149` only), `uv run lint-imports`, `uv run alembic heads` (one head `3742d1281a10` — D2 adds no migration). Commit `docs(arv2 d2): README, spec notes, memory — the display module close-out`.

---

## Self-review

- **Spec coverage.** §7 page grammar → T1 recipes (17 sections, restricted three, bare h1). Recipes as config rows → T1 `load_display_recipes`/`read_recipes` with workspace override. Output shape (intro/items/segments/sendLine/fitDisposition/contactRefs/priority) → T4 materialise + T5 compose. One call per section, parallel, default effort, stable prefix, three lines, no URL → T2 prompts + T4 runner + T6 semaphore/to_thread. Annotations (verbatim/numbers/ids valid/on-recipe/send lines) → T4 checks + `verbatim_annotations` behind the flag. The floor (regenerate once, then drop) → T4 floor + T6 loop. Generate once / recipe-scoped invalidation → T5 `stale_sections` + T6 `regenerate_stale`. Empty state → T5 compose (`empty`, no message). Evidence (§3.9/§6 shared) → T5 evidence. Activity `summary` → T6. A4 exit gate → T7. S4 exit gate (registered keys; prompts contain the three lines; dry run 0 unsafe) → T1/T2 tests + T7. Data-source-map §4 step 3's `current_values` wording is superseded by decision 1 and corrected in T7.
- **Placeholders.** None: every step names the code, the SQL rule, or the exact test assertion. The section instructions are specified by required content per section (they are prose content, written in T2).
- **Type consistency.** `SectionRecipe.narrative` (T1) is read by `build_messages` (T2) and `materialise` (T4). `DisplayClaim.claim_id: str` everywhere; `cited_claim_ids` are uuid strings cast to `uuid[]` at insert. `SectionInput` (T3) is consumed by T4/T5/T6 with the same fields. `PageResult.display_block` is the T5 `compose_display_block` output.
