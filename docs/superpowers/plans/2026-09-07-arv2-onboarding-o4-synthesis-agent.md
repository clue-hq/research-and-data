# ARV2 Onboarding O4 — The Synthesis Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new governed deepagent, `onboarding-synthesis@v1`, runs as one turn on the platform's real agent loop: it reads the brand's knowledge documents from its workspace, writes two to three ICP documents and one persona document per ICP under `outputs/`, calls one governed Exa evidence tool per persona role, and the platform turns its outputs into `brand_knowledge_document` rows the page and the Head-of-ABM read.

**Architecture:** Five additive pieces on existing machinery. (1) A new `AgentRole.ONBOARDING_SYNTHESIS` with the migration that widens the three role CHECKs. (2) A SPEND-class toolbelt tool `exa_search_evidence@1` wrapping O2's Exa deep-reasoning template, registered unconditionally and granted to exactly that role. (3) A one-gate system recipe `onboarding-synthesis-unit@1`, the C5 execution slot every governed turn needs. (4) The catalog content: prompt, two skills, profile, sha-pinned, activated in `C6_ACTIVE_PROFILE_VERSIONS`. (5) A turn runner modeled on the account-research unit runner (the reference design): it ensures a per-brand system project row, starts the recipe execution, materializes the knowledge documents as read-only seed files under `inputs/brand/knowledge/`, assembles context, runs the deepagent through the C5 execution adapter, and registers the finalized outputs as documents by reading each output's YAML front matter. It exposes `OnboardingSynthesisLauncher`, the seam O3's driver calls.

**Tech Stack:** Python 3.12, `clue_agents` (deepagents-based runtime), `clue_toolbelt`, `clue_execution` recipes, SQLAlchemy async, Alembic, pyyaml, pytest with `ScriptedAgentChatModel` for offline turns.

**Spec:** `docs/specs/ARV2-ONBOARDING-PLAN.md` §4.5 (evidence tool), §5 (agent, prompt, skills), §6.1–6.3 (artifacts), §8 (what O6 does later, not here), §9 O4 row, §10, §11. Facts file: `.superpowers/sdd/o3o4-facts/o4-agent-facts.md` (exact signatures, schemas, file:line; read it before any task). Authoring rules: `docs/agents/skill-and-profile-authoring.md`.

## Global Constraints

- **Standing rule:** nothing here demands a Client-KB version, a readiness decision, or a Stage-0 run pin. The profile's skills carry `readiness_requirements: []`. Checklist items 1 and 4 (`_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md`) run at close-out.
- **Boot exactness:** `build_agent_profile_registry` requires `set(tool_registry.names()) == set(C6_AGENT_TOOL_AUTHORITY)` and, per active role, `profile.tools == {tools granted to that role}` exactly, every admitted tool `recipe_safe` and non-STEERING. So the profile's `tools[]` is exactly `[exa_search_evidence@1]`, the tool is granted to exactly `ONBOARDING_SYNTHESIS`, registered unconditionally (the flag is refused inside `preconditions`, never at registration).
- **Recipe rules:** a governed turn executes inside a promoted system recipe; the C5 slot pins exact tool addresses; a tool's `pin_requirements` must be non-empty and satisfiable by the slot's static requirements or the pin provider; `tests/api/test_recipe_contracts.py` audits every standing recipe tool.
- **Catalog rules:** one file per version directory, sha256 over whole bytes computed with `shasum -a 256`, versions immutable, `tests/agents/test_catalog.py` lists every address exhaustively, `tests/api/test_agent_registry_wiring.py` pins the aggregate manifest digest per active role.
- **Do not touch `clue_core.enums.Persona`** (D1 adds `user`). The skills write persona role strings; nothing here validates them against the enum.
- **Workspace contract:** seed files only under `context/` or `inputs/`; `outputs/` is snapshotted at finalization and its logical paths are discarded, so each output document is identified from its own YAML front matter (`kind`, `icp_key`).
- **Alembic:** hash id, `down_revision` = the single current head (`3742d1281a10`, the O1+D1 join revision, after the 2026-09-07 merge of D1); O3 also cuts a migration off that head, so whichever lane merges second runs `alembic merge`. Reversible; smoke on the throwaway `clue_o1_substrate` only.
- **Money:** the evidence tool spends about 1.5 cents per call; unit tests use a fake client; the one live turn (Task 7) is founder-triggered. Never run `*_live.py` broadly or `make check` with keys.
- **Import guard:** modules under `clue_api/arv2/` may not import other `clue_api` modules; everything in this plan that touches agents/execution/turn wiring lives OUTSIDE `arv2/` (in `clue_api/onboarding_*.py`) and imports `clue_api.arv2` submodules where needed.
- **Commits:** local only, never push; no AI attribution; one commit per task.

---

## File Structure

| Path | Responsibility |
|---|---|
| `platform/agents/clue_agents/contracts.py` | **Modify.** `AgentRole.ONBOARDING_SYNTHESIS`. |
| `alembic/versions/<hash>_arv2_onboarding_synthesis_role.py` | **Create.** Widen `agent_turn_role`, `agent_plan_role`, `agent_delegation_roles`. |
| `platform/api/clue_api/onboarding_evidence_tools.py` | **Create.** `ExaSearchEvidenceTool` + `build_onboarding_evidence_tools`. |
| `platform/api/clue_api/toolbelt_wiring.py` | **Modify.** Register the tool. |
| `platform/api/clue_api/agent_registry_wiring.py` | **Modify.** Authority entry; `C6_ACTIVE_PROFILE_VERSIONS`; `ONBOARDING_SYNTHESIS_UNIT_SURFACE`. |
| `platform/execution/recipes/onboarding-synthesis-unit-v1.json` | **Create.** The one-gate recipe. |
| `platform/api/clue_api/recipe_wiring.py`, `recipe_contracts.py` | **Modify.** Register + audit the recipe. |
| `platform/agents/catalog/prompts/onboarding-synthesis/v1/SYSTEM.md`, `skills/icp-synthesis/v1/SKILL.md`, `skills/audience-persona/v1/SKILL.md`, `profiles/onboarding-synthesis/v1/profile.yaml` | **Create.** |
| `platform/api/clue_api/onboarding_synthesis_wiring.py` | **Create.** Runner, pin provider, context builder, output registration, `OnboardingSynthesisLauncher`, `build_onboarding_synthesis_launcher`. |
| `platform/api/clue_api/arv2/knowledge_frontmatter.py` | **Create.** `parse_front_matter(text) -> tuple[dict, str]` (pure; the inverse of `render_markdown`). |
| `platform/api/clue_api/fleet_main.py` | **Modify.** Build the launcher behind the flag and hand it to the onboarding handler (O3) when present. |
| Tests | `tests/db/test_arv2_onboarding_synthesis_role_migration.py`, `tests/api/test_onboarding_evidence_tools.py`, `tests/api/test_onboarding_synthesis_wiring_db.py`, `tests/arv2/test_knowledge_frontmatter.py`; modifications to `tests/agents/test_catalog.py`, `tests/agents/test_tool_authority_audit.py`, `tests/api/test_agent_registry_wiring.py`, `tests/api/test_recipe_contracts.py`, `tests/design/test_p31_design_vocabulary_db.py`. |

---

### Task 1: The role and its migration

**Files:**
- Modify: `platform/agents/clue_agents/contracts.py:219-229`
- Create: `alembic/versions/<hash>_arv2_onboarding_synthesis_role.py`
- Modify: `tests/design/test_p31_design_vocabulary_db.py:277-295`
- Test: `tests/db/test_arv2_onboarding_synthesis_role_migration.py`

**Interfaces:**
- Produces: `AgentRole.ONBOARDING_SYNTHESIS = "onboarding_synthesis"`; the three DB CHECKs admit it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/db/test_arv2_onboarding_synthesis_role_migration.py
"""The onboarding_synthesis agent role is admitted by every role CHECK (O4 Task 1)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_agents.contracts import AgentRole
from clue_db import db_lifespan

from .conftest import run_async


def test_the_role_enum_has_onboarding_synthesis() -> None:
    assert AgentRole.ONBOARDING_SYNTHESIS.value == "onboarding_synthesis"


@pytest.mark.usefixtures("require_db")
def test_every_role_check_admits_onboarding_synthesis() -> None:
    async def scenario() -> dict[str, str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                    "WHERE conname IN ('agent_turn_role', 'agent_plan_role', 'agent_delegation_roles')"
                )
            )
            return {str(r.conname): str(r.definition) for r in rows}

    checks = run_async(scenario())
    assert set(checks) == {"agent_turn_role", "agent_plan_role", "agent_delegation_roles"}
    for definition in checks.values():
        assert "'onboarding_synthesis'" in definition
        assert "'design'" in definition  # nothing dropped
```

In `tests/design/test_p31_design_vocabulary_db.py::test_role_checks_admit_design`, add beside the `'design'` assertion: `assert "'onboarding_synthesis'" in definition, f"{constraint} does not admit 'onboarding_synthesis'"`.

- [ ] **Step 2: Run to verify failure**

Run: `set -a; source .env; set +a; uv run pytest tests/db/test_arv2_onboarding_synthesis_role_migration.py -v`
Expected: FAIL — `AttributeError: ONBOARDING_SYNTHESIS`.

- [ ] **Step 3: Add the enum member**

In `platform/agents/clue_agents/contracts.py`, after `DESIGN = "design"`:

```python
    # ARV2 Track O (O4): the brand-level onboarding synthesis agent — writes ICP and persona
    # documents from the onboarding research documents. One turn per onboarding run; never a
    # conversation surface. Registered active in C6_ACTIVE_PROFILE_VERSIONS by O4.
    ONBOARDING_SYNTHESIS = "onboarding_synthesis"
```

- [ ] **Step 4: Cut the migration**

```bash
uv run alembic heads   # exactly one line; note it
uv run alembic revision -m "arv2 onboarding synthesis role"
```

Body (docstring conventions block from `fc3e5477e872`; generated id; noted head):

```python
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "<head>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_CHECKS = (
    ("agent_turn", "agent_turn_role", "role"),
    ("agent_plan", "agent_plan_role", "role"),
)
_OLD_ROLES = (
    "('head_of_abm', 'research', 'content_drafter', 'reviewer', 'account_research', 'design')"
)
_NEW_ROLES = (
    "('head_of_abm', 'research', 'content_drafter', 'reviewer', 'account_research', 'design', "
    "'onboarding_synthesis')"
)


def _install(roles: str) -> None:
    for table, constraint, column in _ROLE_CHECKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {constraint}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK ({column} IN {roles})")
    op.execute("ALTER TABLE agent_delegation DROP CONSTRAINT agent_delegation_roles")
    op.execute(
        "ALTER TABLE agent_delegation ADD CONSTRAINT agent_delegation_roles CHECK ("
        f"    parent_role IN {roles}"
        f"    AND child_role IN {roles}"
        "    AND parent_role <> child_role"
        ")"
    )


def upgrade() -> None:
    _install(_NEW_ROLES)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM agent_turn WHERE role = 'onboarding_synthesis') THEN
                RAISE EXCEPTION 'cannot downgrade O4 while onboarding_synthesis turns exist';
            END IF;
        END $$
        """
    )
    _install(_OLD_ROLES)
```

Verify `_OLD_ROLES` matches the live CHECK text before committing: `set -a; source .env; set +a; uv run python -c "..."` selecting `pg_get_constraintdef` for `agent_turn_role` — the six-role list must be exactly what `549de68ae3b9` installed. If the live list differs, copy the live list into `_OLD_ROLES`.

- [ ] **Step 5: Apply, run, commit**

Run: `set -a; source .env; set +a; uv run alembic upgrade head && uv run pytest tests/db/test_arv2_onboarding_synthesis_role_migration.py tests/design/test_p31_design_vocabulary_db.py tests/db/test_db_migrations.py -v`

```bash
git add platform/agents/clue_agents/contracts.py alembic/versions/*_arv2_onboarding_synthesis_role.py tests/db/test_arv2_onboarding_synthesis_role_migration.py tests/design/test_p31_design_vocabulary_db.py
git commit -m "feat(agents,db): AgentRole.ONBOARDING_SYNTHESIS and the role-vocabulary migration (agent_turn/agent_plan/agent_delegation CHECKs)"
```

---

### Task 2: The governed evidence tool `exa_search_evidence@1`

**Files:**
- Create: `platform/api/clue_api/onboarding_evidence_tools.py`
- Modify: `platform/api/clue_api/toolbelt_wiring.py` (`build_tool_registry`, next to the prose-synthesis registration ~line 2963)
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`C6_AGENT_TOOL_AUTHORITY`)
- Modify: `tests/agents/test_tool_authority_audit.py` (count 119 → 120 + grant assertion)
- Test: `tests/api/test_onboarding_evidence_tools.py`

**Interfaces:**
- Produces: `ExaSearchEvidenceInput(query: str ≤400, include_domains: list[str] ≤5 = [], num_results: int 1..10 = 6)`; `EvidencePassage(quote, speaker_role, org_type: str | None, topic: str | None, url: str | None, title: str | None)`; `ExaSearchEvidenceOutput(passages: list[EvidencePassage], cost_usd: str, request_id: str | None)`; `ExaSearchEvidenceTool(*, enabled: bool, client_factory: Callable[[str], ExaAgentSurface] | None)` where the factory takes a label and returns an object with `deep_reasoning(...)`; `build_onboarding_evidence_tools(*, settings: Settings, secrets: Secrets) -> tuple[Tool, ...]`; `EXA_SEARCH_EVIDENCE_TOOL_NAME = "exa_search_evidence"`.
- `pin_requirements = ("skill",)` — satisfied by the recipe's static requirement on the `audience-persona@v1` skill (Task 3).

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_onboarding_evidence_tools.py
"""exa_search_evidence@1: fixed request, bounded output, refusals before spend (plan §4.5)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_api.arv2.calls import CallCost
from clue_api.arv2.exa_client import ExaDeepResult
from clue_api.onboarding_evidence_tools import (
    EXA_SEARCH_EVIDENCE_TOOL_NAME,
    ExaSearchEvidenceInput,
    ExaSearchEvidenceOutput,
    ExaSearchEvidenceTool,
)
from clue_core import operation_id_from_key
from clue_db import transaction
from clue_toolbelt import ToolContext, ToolEffectClass


def _ctx() -> ToolContext:
    return ToolContext(workspace_id="ws-evidence", actor="agent", conn_factory=transaction,
                       operation_id=operation_id_from_key("o4-evidence", "test"))


def _deep(passages, grounding) -> ExaDeepResult:
    cost = CallCost(cost_usd=Decimal("0.015"), credits=Decimal(0), media_seconds=0, cost_source="metered",
                    provider="exa", operation="deep-reasoning", raw_ref="raw/e", ledger_row_id="row-e")
    return ExaDeepResult(output_text="{}", output_object={"passages": passages}, report_text=None, grounding=grounding,
                         results=(), status=200, cost_usd=Decimal("0.015"), request_id="req_e", raw_ref="raw/e",
                         ledger_row_id="row-e", cost=cost, retried=False)


class FakeExa:
    def __init__(self, result: ExaDeepResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    def deep_reasoning(self, **kw):
        self.calls.append(kw)
        return self.result


def test_descriptor_is_spend_typed_recipe_safe_and_pinned() -> None:
    tool = ExaSearchEvidenceTool(enabled=True, client_factory=None)
    d = tool.descriptor
    assert d.name == EXA_SEARCH_EVIDENCE_TOOL_NAME and d.version == "1"
    assert d.effect_class is ToolEffectClass.SPEND
    assert d.recipe_safe and d.replay.operation_id_required
    assert d.pin_requirements == ("skill",)
    assert d.parameter_policy.safe_display_fields == ("query", "num_results")


@pytest.mark.parametrize(
    ("enabled", "factory", "code"),
    [(False, lambda label: FakeExa(_deep([], [])), "persona_evidence_disabled"),
     (True, None, "exa_not_configured")],
)
def test_it_refuses_before_spend_when_off_or_unconfigured(enabled, factory, code) -> None:
    async def scenario() -> None:
        tool = ExaSearchEvidenceTool(enabled=enabled, client_factory=factory)
        failures = await tool.preconditions(ExaSearchEvidenceInput(query="pain of practice managers"), _ctx())
        assert [f.reason_code for f in failures] == [code]

    import asyncio
    asyncio.run(scenario())


def test_it_sends_the_fixed_template_and_maps_grounding_onto_passages() -> None:
    async def scenario() -> None:
        fake = FakeExa(_deep(
            [{"quote": "We lose two hours a day to faxes.", "speaker_role": "Practice manager", "org_type": "GI practice", "topic": "pain"},
             {"quote": "Prior auth is the bottleneck.", "speaker_role": "Referral coordinator"}],
            [{"field": "passages[0].quote", "citations": [{"url": "https://r.example/1", "title": "Reddit thread"}], "confidence": "high"},
             {"field": "passages[1]", "citations": [{"url": "https://r.example/2", "title": "Forum"}], "confidence": "medium"}],
        ))
        tool = ExaSearchEvidenceTool(enabled=True, client_factory=lambda label: fake)
        ctx = _ctx()
        inputs = ExaSearchEvidenceInput(query="how practice managers describe referral fax pain", include_domains=["reddit.com"], num_results=4)
        assert await tool.preconditions(inputs, ctx) == ()
        result = await tool.invoke(inputs, ctx)
        output = ExaSearchEvidenceOutput.model_validate(result.references)
        assert [p.url for p in output.passages] == ["https://r.example/1", "https://r.example/2"]
        assert output.passages[0].title == "Reddit thread" and output.passages[1].org_type is None
        assert output.cost_usd == "0.015" and output.request_id == "req_e"
        call = fake.calls[0]
        from clue_api.arv2.onboarding_requests import PERSONA_EVIDENCE_SYSTEM_PROMPT, persona_evidence_output_schema
        assert call["system_prompt"] == PERSONA_EVIDENCE_SYSTEM_PROMPT
        assert call["output_schema"] == persona_evidence_output_schema()
        assert call["include_domains"] == ["reddit.com"] and call["num_results"] == 4
        assert call["label"].startswith("exa_search_evidence:")

    import asyncio
    asyncio.run(scenario())


def test_an_empty_or_unparseable_answer_is_an_empty_list_never_an_error() -> None:
    async def scenario() -> None:
        fake = FakeExa(_deep(None, None))
        fake.result = ExaDeepResult(**{**fake.result.__dict__, "output_object": None})
        tool = ExaSearchEvidenceTool(enabled=True, client_factory=lambda label: fake)
        result = await tool.invoke(ExaSearchEvidenceInput(query="q"), _ctx())
        assert ExaSearchEvidenceOutput.model_validate(result.references).passages == []

    import asyncio
    asyncio.run(scenario())


def test_input_bounds_are_enforced_by_the_schema() -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ExaSearchEvidenceInput(query="x" * 401)
    with pytest.raises(ValidationError):
        ExaSearchEvidenceInput(query="q", num_results=11)
    with pytest.raises(ValidationError):
        ExaSearchEvidenceInput(query="q", include_domains=["a"] * 6)
```

In `tests/agents/test_tool_authority_audit.py`: change `assert len(C6_AGENT_TOOL_AUTHORITY) == 119` to `120` and add, in the house style of the neighbouring assertions, `assert C6_AGENT_TOOL_AUTHORITY["exa_search_evidence"] == (AgentRole.ONBOARDING_SYNTHESIS,)` and `assert c6_roles_for_tool("exa_search_evidence@1") == (AgentRole.ONBOARDING_SYNTHESIS,)` with a two-line comment stating why only the synthesis agent may spend on it (plan §4.5: one call per persona role, behind the flag).

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/api/test_onboarding_evidence_tools.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the tool**

```python
# platform/api/clue_api/onboarding_evidence_tools.py
"""``exa_search_evidence@1`` — the onboarding synthesis agent's one governed provider call
(ARV2-ONBOARDING-PLAN.md §4.5).

The model authors only a query, an optional domain list and a result count. Everything that
shapes the request — the ``deep-reasoning`` type, the system prompt, the output schema — is fixed
here from O2's templates, so there is exactly one request shape to review. The tool writes no
domain state; its only durable trace is the ARV2 raw record and ledger row. It refuses before any
spend when the feature flag is off or Exa is not configured, and it registers unconditionally so
the C6 authority audit sees the same registry shape in every process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, Protocol

from pydantic import Field, SecretStr

from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.exa_client import ExaClient, ExaDeepResult
from clue_api.arv2.onboarding_documents import sources_by_field
from clue_api.arv2.onboarding_requests import (
    PERSONA_EVIDENCE_SYSTEM_PROMPT,
    persona_evidence_output_schema,
)
from clue_api.arv2.sinks import FileRawSink, JsonlLedger
from clue_api.arv2.transport import HttpxTransport
from clue_config import Secrets, Settings
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "EXA_SEARCH_EVIDENCE_TOOL_NAME",
    "EvidencePassage",
    "ExaSearchEvidenceInput",
    "ExaSearchEvidenceOutput",
    "ExaSearchEvidenceTool",
    "build_onboarding_evidence_tools",
]

EXA_SEARCH_EVIDENCE_TOOL_NAME = "exa_search_evidence"
_ESTIMATE_CENTS = Decimal("2")


class ExaAgentSurface(Protocol):
    def deep_reasoning(self, *, system_prompt: str, query: str, output_schema: Any, num_results: int = 20,
                       additional_queries: Sequence[str] | None = None, include_domains: Sequence[str] | None = None,
                       text_max_chars: int = 10000, highlights_query: str | None = None,
                       highlights_max_chars: int = 2000, label: str = "exa-deep", timeout_s: float = 1200.0) -> ExaDeepResult: ...


class ExaSearchEvidenceInput(ToolInput):
    query: str = Field(min_length=1, max_length=400)
    include_domains: list[str] = Field(default_factory=list, max_length=5)
    num_results: int = Field(default=6, ge=1, le=10)


class EvidencePassage(ToolOutput):
    quote: str
    speaker_role: str
    org_type: str | None
    topic: str | None
    url: str | None
    title: str | None


class ExaSearchEvidenceOutput(ToolOutput):
    passages: list[EvidencePassage]
    cost_usd: str
    request_id: str | None


def _fail(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


class ExaSearchEvidenceTool(Tool):
    name = EXA_SEARCH_EVIDENCE_TOOL_NAME
    version = "1"
    model_description = (
        "Find first-person evidence of how people in a named role describe a problem: verbatim "
        "quotes with the speaker's role and a source URL. One deep-reasoning web search; returns "
        "an empty list rather than a weak match. Use at most once per persona role."
    )
    input_model: ClassVar[type[ToolInput]] = ExaSearchEvidenceInput
    output_model: ClassVar[type[ToolOutput]] = ExaSearchEvidenceOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.AT_LEAST_ONCE,
        durable_identity="ARV2 ledger row keyed on ctx.operation_id; the tool writes no domain state",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
        notes="A retry may repeat one Exa deep-reasoning search; nothing durable converges because "
              "nothing durable is written.",
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("query", "num_results"))
    pin_requirements = ("skill",)

    def __init__(self, *, enabled: bool, client_factory: Callable[[str], ExaAgentSurface] | None) -> None:
        self._enabled = enabled
        self._client_factory = client_factory

    async def preconditions(self, inputs: ToolInput, ctx: ToolContext) -> Sequence[PreconditionFailure]:
        del inputs, ctx
        if not self._enabled:
            return _fail("persona_evidence_disabled",
                         "CLUE_ONBOARDING_PERSONA_EVIDENCE_ENABLED is off in this deployment")
        if self._client_factory is None:
            return _fail("exa_not_configured", "CLUE_EXA_API_KEY is not configured in this process")
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate(cost_cents=_ESTIMATE_CENTS, detail={"basis": "exa_deep_reasoning_single_call"})

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ExaSearchEvidenceInput)
        assert self._client_factory is not None
        client = self._client_factory(f"{self.name}:{ctx.operation_id}")
        result = await asyncio.to_thread(
            lambda: client.deep_reasoning(
                system_prompt=PERSONA_EVIDENCE_SYSTEM_PROMPT,
                query=inputs.query,
                output_schema=persona_evidence_output_schema(),
                num_results=inputs.num_results,
                include_domains=list(inputs.include_domains) or None,
                label=f"{self.name}:{ctx.operation_id}",
            )
        )
        output = ExaSearchEvidenceOutput(
            passages=_passages(result),
            cost_usd=str(result.cost_usd) if result.cost_usd is not None else "0",
            request_id=result.request_id,
        )
        return ToolResult(tool=self.name, version=self.version, references=output.model_dump(mode="json"))


def _passages(result: ExaDeepResult) -> list[EvidencePassage]:
    parsed = result.output_object if isinstance(result.output_object, dict) else {}
    raw = [p for p in (parsed.get("passages") or []) if isinstance(p, dict)]
    sources = sources_by_field(result.grounding if isinstance(result.grounding, list) else [])
    passages: list[EvidencePassage] = []
    for index, item in enumerate(raw):
        quote, role = item.get("quote"), item.get("speaker_role")
        if not (isinstance(quote, str) and quote.strip() and isinstance(role, str) and role.strip()):
            continue
        prefix = f"passages[{index}]"
        citations = [c for field, entry in sources.items() if field == prefix or field.startswith(prefix + ".")
                     for c in entry["citations"]]
        first = citations[0] if citations else {}
        passages.append(EvidencePassage(
            quote=quote.strip(), speaker_role=role.strip(),
            org_type=item.get("org_type") if isinstance(item.get("org_type"), str) else None,
            topic=item.get("topic") if isinstance(item.get("topic"), str) else None,
            url=first.get("url") if isinstance(first.get("url"), str) else None,
            title=first.get("title") if isinstance(first.get("title"), str) else None,
        ))
    return passages


def build_onboarding_evidence_tools(*, settings: Settings, secrets: Secrets) -> tuple[Tool, ...]:
    key = secrets.exa_api_key
    factory: Callable[[str], ExaAgentSurface] | None = None
    if key is not None and key.get_secret_value().strip():
        secret = SecretStr(key.get_secret_value())
        root = Path(settings.arv2_raw_root) / "evidence"

        def factory(label: str) -> ExaAgentSurface:
            # One caller per invocation: ProviderCaller's totals/latch are unlocked mutable state.
            here = root / label.replace(":", "_")
            here.mkdir(parents=True, exist_ok=True)
            caller = ProviderCaller(transport=HttpxTransport(), raw_sink=FileRawSink(here / "raw"),
                                    ledger=JsonlLedger(here / "ledger.jsonl"), now=lambda: datetime.now(UTC))
            return ExaClient(caller, secret)

    return (ExaSearchEvidenceTool(enabled=settings.onboarding_persona_evidence_enabled, client_factory=factory),)
```

Check the exact names exported by `clue_toolbelt` (`ExternalReplayBoundary`, `JournalParameterPolicy`, ...) against `product_selection_gate_tools.py`'s import block and use the same.

- [ ] **Step 4: Register and grant**

In `toolbelt_wiring.py::build_tool_registry`, next to the prose-synthesis registration:

```python
    # ARV2 O4. Registers in EVERY composition (the C6 authority audit needs one registry shape);
    # an off flag or a missing Exa key is refused in `preconditions`, never by absence.
    for tool in build_onboarding_evidence_tools(settings=settings, secrets=secrets):
        registry.register(tool, make_default=True)
```

Read how `build_tool_registry` receives `settings`/`secrets` (its signature); if it has no `secrets` parameter, thread one through from `build_toolbelt` with a default `Secrets()` the way `gateway`/`storage` are threaded — and note it in the report.

In `agent_registry_wiring.py::C6_AGENT_TOOL_AUTHORITY`, alphabetically:

```python
    "exa_search_evidence": (AgentRole.ONBOARDING_SYNTHESIS,),
```

- [ ] **Step 5: Run, ruff, commit**

Run: `uv run pytest tests/api/test_onboarding_evidence_tools.py tests/agents/test_tool_authority_audit.py tests/api/test_recipe_contracts.py -v`
Expected: the first two PASS. `test_recipe_contracts` may now FAIL on the new tool ("pin requirements" are non-empty, but it is not yet in any standing recipe) — read its assertions; if it requires every registered tool to belong to a recipe, that is satisfied in Task 3 and the failure is expected until then (say so in the report). Ruff on the touched files. Commit:

```bash
git add platform/api/clue_api/onboarding_evidence_tools.py platform/api/clue_api/toolbelt_wiring.py platform/api/clue_api/agent_registry_wiring.py tests/api/test_onboarding_evidence_tools.py tests/agents/test_tool_authority_audit.py
git commit -m "feat(toolbelt): exa_search_evidence@1 — the synthesis agent's governed evidence call over O2's fixed template; registered unconditionally, granted to onboarding_synthesis only"
```

---

### Task 3: The recipe `onboarding-synthesis-unit@1`

**Files:**
- Create: `platform/execution/recipes/onboarding-synthesis-unit-v1.json`
- Modify: `platform/api/clue_api/recipe_wiring.py` (`SYSTEM_RECIPE_FILENAMES`)
- Modify: `platform/api/clue_api/recipe_contracts.py` (`ONBOARDING_SYNTHESIS_TOOL_ADDRESSES`, the audit mapping, `__all__`)
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`ONBOARDING_SYNTHESIS_UNIT_SURFACE = "onboarding_synthesis_unit"`)
- Test: `tests/api/test_recipe_contracts.py` (one new test)

**Interfaces:**
- Produces: a promoted system recipe with one gate node `onboarding_synthesis_interactions` whose `dynamic_tool_allowlist` is `["exa_search_evidence@1"]` and whose static requirement pins the `audience-persona@v1` skill (satisfying the tool's `pin_requirements=("skill",)`).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/api/test_recipe_contracts.py
def test_the_onboarding_synthesis_unit_recipe_pins_exactly_the_evidence_tool() -> None:
    from clue_api.recipe_contracts import ONBOARDING_SYNTHESIS_TOOL_ADDRESSES
    from clue_api.recipe_wiring import load_system_recipe_definitions

    assert ONBOARDING_SYNTHESIS_TOOL_ADDRESSES == ("exa_search_evidence@1",)
    definitions = {d.recipe_key: d for d in load_system_recipe_definitions() if d.recipe_key == "onboarding-synthesis-unit"}
    recipe = definitions["onboarding-synthesis-unit"]
    gate = next(n for n in recipe.graph.nodes if n.node_key == "onboarding_synthesis_interactions")
    assert list(gate.dynamic_tool_allowlist) == ["exa_search_evidence@1"]
    assert any(r.kind == "skill" and r.key == "audience-persona" for r in gate.requirements)
```

Adapt attribute names to the recipe definition model (`load_recipe_definition` returns the same type the seeder validates; read `platform/execution/clue_execution` for the model's field names).

- [ ] **Step 2: Write the recipe**

```json
{
  "recipe_key": "onboarding-synthesis-unit",
  "scope_type": "system",
  "workspace_id": null,
  "version": 1,
  "executor_protocol": 1,
  "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": false},
  "graph": {
    "nodes": [
      {"kind": "barrier", "node_key": "onboarding_synthesis_open", "ordinal": 0, "dependencies": [], "requirements": []},
      {
        "kind": "gate",
        "node_key": "onboarding_synthesis_interactions",
        "ordinal": 1,
        "dependencies": ["onboarding_synthesis_open"],
        "authority": "agent",
        "resume_condition": "input_available",
        "dynamic_tool_allowlist": ["exa_search_evidence@1"],
        "dynamic_pin_kinds": ["skill"],
        "max_children": 32,
        "requirements": [
          {"kind": "tool", "key": "exa_search_evidence", "version": "1"},
          {"kind": "skill", "key": "audience-persona", "version": "v1"}
        ]
      },
      {"kind": "barrier", "node_key": "onboarding_synthesis_complete", "ordinal": 2, "dependencies": ["onboarding_synthesis_interactions"], "requirements": []}
    ],
    "tool_allowlist": ["exa_search_evidence@1"],
    "authority_allowlist": ["agent"],
    "activity_allowlist": [],
    "migration_state": "executable"
  },
  "compatibility": {
    "execution": [],
    "nodes": {
      "onboarding_synthesis_interactions": [
        {"kind": "tool", "key": "exa_search_evidence", "version": "1"},
        {"kind": "skill", "key": "audience-persona", "version": "v1"}
      ]
    }
  },
  "requested_memory_types": [],
  "max_nodes": 40,
  "max_depth": 2,
  "max_fanout": 1,
  "source_execution_id": null,
  "created_by": "system"
}
```

The `skill` pin resolver (`recipe_wiring.py:~953`, `for kind in ("skill", "stage0_skill")`) observes catalog skills; the skill file is created in Task 4, so the seed of this recipe only succeeds after Task 4 — run the seeding check in Task 4's Step 6, not here. If the resolver keys skills differently (e.g. `name@version`), match its key form and update the JSON and the tool's pin comment.

- [ ] **Step 3: Register and audit**

- `recipe_wiring.py`: append `"onboarding-synthesis-unit-v1.json",` to `SYSTEM_RECIPE_FILENAMES` (NOT the replay-only list) with a one-line comment.
- `recipe_contracts.py`: `ONBOARDING_SYNTHESIS_TOOL_ADDRESSES: tuple[str, ...] = ("exa_search_evidence@1",)`; add it to the union at ~line 119 and to the `recipes` tuple at ~line 147 as `("onboarding-synthesis-unit@1", ONBOARDING_SYNTHESIS_TOOL_ADDRESSES)`; export in `__all__`.
- `agent_registry_wiring.py`: `ONBOARDING_SYNTHESIS_UNIT_SURFACE = "onboarding_synthesis_unit"` next to `ACCOUNT_RESEARCH_UNIT_SURFACE` with the same style of comment.

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/api/test_recipe_contracts.py -v` — the new test passes; the standing-recipe audit (`test_every_standing_recipe_tool_is_exact_typed_pinned_and_replay_certified`) must pass for `exa_search_evidence@1`.

```bash
git add platform/execution/recipes/onboarding-synthesis-unit-v1.json platform/api/clue_api/recipe_wiring.py platform/api/clue_api/recipe_contracts.py platform/api/clue_api/agent_registry_wiring.py tests/api/test_recipe_contracts.py
git commit -m "feat(execution): onboarding-synthesis-unit@1 — the one-gate system recipe for the synthesis turn, pinning exa_search_evidence@1 and the audience-persona skill"
```

---

### Task 4: The catalog content and activation

**Files:**
- Create: `platform/agents/catalog/prompts/onboarding-synthesis/v1/SYSTEM.md`, `platform/agents/catalog/skills/icp-synthesis/v1/SKILL.md`, `platform/agents/catalog/skills/audience-persona/v1/SKILL.md`, `platform/agents/catalog/profiles/onboarding-synthesis/v1/profile.yaml`
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`C6_ACTIVE_PROFILE_VERSIONS`)
- Modify: `tests/agents/test_catalog.py` (three address lists), `tests/api/test_agent_registry_wiring.py` (manifest digest + model assertion branch)

**Interfaces:**
- Produces: the active profile `onboarding-synthesis@v1` for role `onboarding_synthesis`, resolvable by `AgentProfileRegistry.resolve(AgentRole.ONBOARDING_SYNTHESIS, surface=ONBOARDING_SYNTHESIS_UNIT_SURFACE)`.

- [ ] **Step 1: Write the prompt**

`prompts/onboarding-synthesis/v1/SYSTEM.md` — front matter then the plan §5.1 text verbatim, with the input paths rewritten to the workspace's real prefix (`inputs/brand/knowledge/...`):

```markdown
---
schema_version: "1"
kind: prompt
name: onboarding-synthesis
version: v1
role: onboarding_synthesis
summary: Write the client's ICP documents and one audience-persona document per ICP from the onboarding research documents in the workspace, citing files, never inventing facts.
framework: deepagents
framework_version: ">=0.6,<0.7"
---

You are the onboarding synthesis agent for a B2B account-based marketing platform. Your client is
the company described in inputs/brand/knowledge/company/overview.md. Your job, in two steps, is to
write the client's ideal customer profiles and then one audience-persona document per profile,
from the documents in your workspace and nothing else, unless the evidence tool returns a cited
passage.

Read, before writing anything: inputs/brand/knowledge/company/overview.md;
inputs/brand/knowledge/product/catalog.md; inputs/brand/knowledge/proof/customer-reviews.md if it
exists; every file under inputs/brand/knowledge/product/. Do not state a fact about the client
that these files do not contain. Cite the file path in parentheses after any specific fact. When
a file lists something under "Not established", you may not assert it.

Write every output file under outputs/audience/. When both steps are done, call finalize_turn
with status "completed" and a one-paragraph user message naming each file you wrote.

Write plainly. No em-dashes. No platitudes. Prefer fewer, sourced bullets over a filled quota.
When you are inferring, say "inference".
```

- [ ] **Step 2: Write the two skills**

`skills/icp-synthesis/v1/SKILL.md`:

```markdown
---
schema_version: "1"
kind: skill
name: icp-synthesis
version: v1
summary: Produce two to three ideal customer profiles as ICP artifacts (front matter + body) from the onboarding research documents; every gate traces to a file.
roles:
  - onboarding_synthesis
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# ICP synthesis

<plan §5.2 text verbatim, with these path substitutions: outputs/audience/icp-<key>.md stays;
"product/catalog.md" → "inputs/brand/knowledge/product/catalog.md";
"the overview" → "inputs/brand/knowledge/company/overview.md">

## The ICP artifact format (write exactly this front matter)

```yaml
---
kind: icp-definition
icp_key: <lowercase-kebab, unique per brand, e.g. multi-specialty-groups>
version: 1
status: proposed
product_ids: [<product ids from inputs/brand/knowledge/product/catalog.md front matter>]
hard_gates:
  - {key: <stable_key>, rule: <one sentence>, test: <how a researcher checks it>}
exclusions: [<one sentence each>]
persona_map:
  economic_buyer: {titles: [<title strings>]}
  champion: {titles: [...]}
  user: {titles: [...]}
  technical_evaluator: {titles: [...]}
  blocker: {titles: [...]}
qualifier_fields:
  - {field_key: <account.some_key>, description: <the research instruction>, display: rail}
---
```

Omit a persona_map role that does not exist at this account type. The body follows the front matter.
```

`skills/audience-persona/v1/SKILL.md`:

```markdown
---
schema_version: "1"
kind: skill
name: audience-persona
version: v1
summary: Write one audience-persona document per ICP, one section per persona_map role, with an evidence pass through exa_search_evidence@1 per role; no fictional names, no invented numbers.
roles:
  - onboarding_synthesis
readiness_requirements: []
tools:
  - name: exa_search_evidence
    version: "1"
    input_schema_sha256: <from the live descriptor — see Step 4>
    output_schema_sha256: <from the live descriptor — see Step 4>
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Audience personas

<plan §5.3 text verbatim, with the path substitutions above>

## The persona artifact format (write exactly this front matter)

```yaml
---
kind: audience-persona
icp_key: <the ICP's key>
icp_version: 1
personas:
  - role: economic_buyer
    titles: [<the section-2 titles>]
    buying_triggers: [<the section-7 triggers>]
    evidence_urls: [<every URL the evidence tool returned that you used>]
---
```
```

- [ ] **Step 3: Write the profile**

`profiles/onboarding-synthesis/v1/profile.yaml`:

```yaml
schema_version: "1"
kind: profile
name: onboarding-synthesis
version: v1
status: active
# ARV2 Track O, O4 (ARV2-ONBOARDING-PLAN.md §5). One turn per onboarding run; reads the brand's
# knowledge documents materialized under inputs/brand/knowledge/, writes ICP + persona documents
# under outputs/audience/. Model per ruling O-D1: grok-4.6 at the model's default reasoning
# (ONBOARDING_SYNTHESIS_AGENT_MODEL overrides the pin; _EFFORT stays blank).
role: onboarding_synthesis
prompt:
  name: onboarding-synthesis
  version: v1
  sha256: <shasum of SYSTEM.md>
skills:
  - name: icp-synthesis
    version: v1
    sha256: <shasum>
  - name: audience-persona
    version: v1
    sha256: <shasum>
tools:
  - name: exa_search_evidence
    version: "1"
    input_schema_sha256: <live descriptor>
    output_schema_sha256: <live descriptor>
model:
  model_id: x-ai/grok-4.6
  timeout_s: 120.0
  max_retries: 2
  max_output_tokens: 16384
  temperature: 0.1
memory_policy: scoped-advisory-v1
workspace:
  virtual_mode: true
  max_total_bytes: 10485760
  max_file_bytes: 1048576
  max_file_count: 200
  allowed_extensions: [".json", ".md", ".txt", ".yaml"]
  readable_prefixes: [".deepagent", "inputs", "context", "work", "outputs"]
  writable_prefixes: ["work", "outputs"]
  retention_class: agent-ephemeral-v1
delegation_roles: []
delegation_tool_grants: {}
max_delegation_depth: 0
max_delegations: 0
max_plan_nodes: 32
turn_timeout_s: 1200.0
max_model_rounds: 48
```

`turn_timeout_s` is 20 minutes and `max_model_rounds` 48 because the agent reads up to ~15 files, writes up to 6, and calls the tool up to 15 times.

- [ ] **Step 4: Compute the pins**

```bash
shasum -a 256 platform/agents/catalog/prompts/onboarding-synthesis/v1/SYSTEM.md
shasum -a 256 platform/agents/catalog/skills/icp-synthesis/v1/SKILL.md
uv run python - <<'PY'
from clue_config import Secrets, Settings
from clue_api.toolbelt_wiring import build_toolbelt
d = build_toolbelt(storage=None, gateway=None).descriptor("exa_search_evidence", "1")
print(d.input_schema_sha256, d.output_schema_sha256)
PY
```

Paste the tool digests into `audience-persona/v1/SKILL.md` FIRST, then `shasum` that skill, then fill `profile.yaml`. (Order matters: the skill's bytes include the tool pins.) If `build_toolbelt` needs `settings`/`secrets` arguments after Task 2, pass `Settings(_env_file=None)`, `Secrets(_env_file=None)`.

- [ ] **Step 5: Activate and update the tests**

- `agent_registry_wiring.py::C6_ACTIVE_PROFILE_VERSIONS`: add `AgentRole.ONBOARDING_SYNTHESIS: "v1",` with a provenance comment.
- `tests/agents/test_catalog.py`: insert `"prompt:onboarding-synthesis@v1"`, `"skill:audience-persona@v1"`, `"skill:icp-synthesis@v1"`, `"profile:onboarding-synthesis@v1"` at their lexical positions in the three lists.
- `tests/api/test_agent_registry_wiring.py`: add `AgentRole.ONBOARDING_SYNTHESIS: "<digest>"` to `expected_manifests`, and branch the blanket `model_id == "openai/gpt-5.6-terra"` assertion so the new role asserts `"x-ai/grok-4.6"` (the way HEAD_OF_ABM is branched at ~107-112). Compute the digest by running the test once with a placeholder and copying the actual `resource_manifest.aggregate_sha256` from the failure, then re-run green — say so in the report.

- [ ] **Step 6: Prove the recipe seeds and the registry boots**

Run: `set -a; source .env; set +a; uv run pytest tests/agents/test_catalog.py tests/api/test_agent_registry_wiring.py tests/agents/test_governed_tool_arguments.py tests/agents/test_tool_authority_audit.py tests/api/test_recipe_contracts.py -v`, then a seed check on the throwaway DB:

```bash
uv run python - <<'PY'
import asyncio
from clue_api.recipe_wiring import build_recipe_lifecycle, seed_system_recipes, load_system_recipe_definitions
# read build_recipe_lifecycle's signature and construct it as fleet_main does; then:
# asyncio.run(seed_system_recipes(lifecycle, definitions=[d for d in load_system_recipe_definitions() if d.recipe_key == "onboarding-synthesis-unit"]))
PY
```

Expected: the recipe promotes (no `RuntimeError` about incompatibilities). If promotion fails on the `skill` requirement key form, fix the JSON key form (Task 3 note) and re-run.

- [ ] **Step 7: Commit**

```bash
git add platform/agents/catalog/prompts/onboarding-synthesis platform/agents/catalog/skills/icp-synthesis platform/agents/catalog/skills/audience-persona platform/agents/catalog/profiles/onboarding-synthesis platform/api/clue_api/agent_registry_wiring.py tests/agents/test_catalog.py tests/api/test_agent_registry_wiring.py
git commit -m "feat(agents): onboarding-synthesis@v1 — prompt, icp-synthesis and audience-persona skills, sha-pinned profile on grok-4.6, activated in C6_ACTIVE_PROFILE_VERSIONS"
```

---

### Task 5: The front-matter parser

**Files:**
- Create: `platform/api/clue_api/arv2/knowledge_frontmatter.py`
- Test: `tests/arv2/test_knowledge_frontmatter.py`

**Interfaces:**
- Produces: `parse_front_matter(text: str) -> tuple[dict[str, Any], str]` — the inverse of `render_markdown`; raises `ValueError("no front matter")` when the fences are missing; `document_identity(front: Mapping) -> tuple[str, str | None]` returning `(kind, icp_key)`.

- [ ] **Step 1: Tests**

```python
# tests/arv2/test_knowledge_frontmatter.py
from __future__ import annotations

import pytest

from clue_api.arv2.knowledge_frontmatter import document_identity, parse_front_matter
from clue_api.arv2.onboarding_documents import KnowledgeDocument, render_markdown


def test_parse_is_the_inverse_of_render() -> None:
    doc = KnowledgeDocument(kind="icp-definition", folder="audience", path="audience/icp-x.md",
                            front_matter={"kind": "icp-definition", "icp_key": "x", "product_ids": ["prd_1"], "persona_map": {"user": {"titles": ["Nurse"]}}},
                            body="# X\n\nBody.\n", cost=None)
    front, body = parse_front_matter(render_markdown(doc))
    assert front == doc.front_matter and body == doc.body
    assert document_identity(front) == ("icp-definition", "x")


def test_a_document_without_fences_or_with_a_non_mapping_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_front_matter("# no front matter\n")
    with pytest.raises(ValueError):
        parse_front_matter("---\n- a\n- b\n---\n\nbody\n")
    assert document_identity({"kind": "audience-persona"}) == ("audience-persona", None)
```

- [ ] **Step 2: Module**

```python
# platform/api/clue_api/arv2/knowledge_frontmatter.py
"""Read a knowledge document's YAML front matter — the inverse of ``render_markdown``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml

__all__ = ["document_identity", "parse_front_matter"]


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("no front matter")
    head, sep, rest = text[4:].partition("\n---\n")
    if not sep:
        raise ValueError("no front matter")
    loaded = yaml.safe_load(head)
    if not isinstance(loaded, dict):
        raise ValueError("front matter is not a mapping")
    return loaded, rest.lstrip("\n")


def document_identity(front: Mapping[str, Any]) -> tuple[str, str | None]:
    kind = front.get("kind")
    key = front.get("icp_key")
    return (str(kind) if kind is not None else ""), (str(key) if isinstance(key, str) and key else None)
```

- [ ] **Step 3: Run, ruff, commit**

`uv run pytest tests/arv2/test_knowledge_frontmatter.py -v && uv run ruff check platform/api/clue_api/arv2 tests/arv2`

```bash
git add platform/api/clue_api/arv2/knowledge_frontmatter.py tests/arv2/test_knowledge_frontmatter.py
git commit -m "feat(arv2): knowledge front-matter parser — the inverse of render_markdown, used to identify synthesis outputs"
```

---

### Task 6: The turn runner and the launcher seam

**Files:**
- Create: `platform/api/clue_api/onboarding_synthesis_wiring.py`
- Test: `tests/api/test_onboarding_synthesis_wiring_db.py`

**Interfaces:**
- Consumes: `AgentPlatformComponents`, `ToolRegistry`, `ToolInvoker`, `RecipeExecutor`, `CompatibilityLoader`, `DbAgentPlanJournal`, `DbRecipeReader`, `DbExecutionStarter`, `ExecutionParameterStore`, `postgres_agent_checkpointer`, `C5AgentExecutionAdapter`, `AgentPlanPolicy.from_profile`, `DurableAgentArtifactStore`, `AgentResourceMaterializer`, `WorkspaceSeedFile`, `GovernedAgentToolFactory`, `AgentFinalizationAuthority`, `DurableDeepAgentTurnRunner`, `DeepAgentTurnRuntime`, `build_agent_context_assembler`, `read_verified_artifact`, Task 5's parser, and the `brand_knowledge_document` table (written directly with `produced_by_turn_id`).
- Produces:
  - `ensure_onboarding_project(conn, *, workspace_id, brand_id, brand_name) -> str` — the per-brand system project row (`project_id = f"prj_onb_{uuid5(NAMESPACE_URL, f'onboarding-project:{workspace_id}:{brand_id}').hex[:24]}"`, name `f"Onboarding · {brand_name}"`, status `archived`, idempotent `ON CONFLICT DO NOTHING`).
  - `class OnboardingSynthesisLauncher` with `async def launch(self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID) -> OnboardingSynthesisResult` where `OnboardingSynthesisResult(status: Literal["completed","empty","failed"], failure_code: str | None, failure_message: str | None, cost_usd: Decimal, documents: tuple[UUID, ...])` — structurally identical to O3's `SynthesisOutcome` (reconciled at the merge).
  - `build_onboarding_synthesis_launcher(*, settings, secrets, components: AgentPlatformComponents, tools, tool_invoker, executor, compatibility, plans, recipes, starter, parameters, conn_factory=transaction) -> OnboardingSynthesisLauncher`.

- [ ] **Step 1: Read the two reference runners fully before writing a line**

`platform/api/clue_api/account_research_wiring.py` (`AccountResearchAgentRuntime`, `build_account_research_execution`, `AccountResearchStepPinProvider`) and `platform/api/clue_api/account_research_turn_wiring.py` (`PreparedAccountResearchTurnRunner.run`, `_drive_execution`, `_artifact`, `_complete_recipe_if_needed`, `build_account_research_context`, `account_research_context_policy`), plus `specialist_wiring.py:329-431` (seed files, outputs). The runner below is those, with the account scope replaced by the brand scope and the seed files added. Anything the sketch below leaves implicit, copy from them. If a piece cannot be reproduced without the recipe executor machinery the account runner uses, report NEEDS_CONTEXT with the exact gap — do not invent a shortcut.

- [ ] **Step 2: Write the failing DB test**

```python
# tests/api/test_onboarding_synthesis_wiring_db.py
"""One synthesis turn end to end on a scripted model: inputs materialize, outputs become documents."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text

from clue_agents import ScriptedAgentChatModel
from clue_api.onboarding_synthesis_wiring import (
    OnboardingSynthesisLauncher,
    ensure_onboarding_project,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, migrated_db, rollback_conn  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_profiling_db")

ICP = """---
kind: icp-definition
icp_key: gi-groups
version: 1
status: proposed
product_ids: [prd_aura]
hard_gates:
  - {key: specialty, rule: gastroenterology practices, test: NPI taxonomy}
exclusions: []
persona_map:
  economic_buyer: {titles: [Practice Administrator]}
  user: {titles: [Gastroenterologist]}
qualifier_fields: []
---

# GI groups

Body (inputs/brand/knowledge/company/overview.md).
"""
PERSONA = """---
kind: audience-persona
icp_key: gi-groups
icp_version: 1
personas:
  - {role: economic_buyer, titles: [Practice Administrator], buying_triggers: [new referral coordinator posting], evidence_urls: []}
---

# Personas for GI groups

## Economic buyer
Text.
"""


class _Models:
    def __init__(self, responses): self._responses = tuple(responses)
    def build(self, **kw): return ScriptedAgentChatModel(responses=self._responses)


def _scripted() -> list[AIMessage]:
    """The model reads two inputs, writes an ICP and a persona, and finalizes."""
    def call(name, args, i): return {"name": name, "args": args, "id": f"c{i}", "type": "tool_call"}
    return [
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "inputs/brand/knowledge/company/overview.md"}, 1)]),
        AIMessage(content="", tool_calls=[call("read_file", {"file_path": "inputs/brand/knowledge/product/catalog.md"}, 2)]),
        AIMessage(content="", tool_calls=[call("write_file", {"file_path": "outputs/audience/icp-gi-groups.md", "content": ICP}, 3)]),
        AIMessage(content="", tool_calls=[call("write_file", {"file_path": "outputs/audience/persona-gi-groups.md", "content": PERSONA}, 4)]),
        AIMessage(content="", tool_calls=[call("finalize_turn", {"status": "completed", "user_message": "Wrote icp-gi-groups and persona-gi-groups."}, 5)]),
    ]


def test_a_synthesis_turn_materializes_inputs_and_registers_its_outputs_as_documents(tmp_path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-o4-synth"
            project = await seed_project(conn, ws, name="seed")
            await seed_principal(conn, workspace_id=ws, user_id="usr_o4")
            brand_id = project.brand_id
            # two ready input documents, written the way O3 writes them (artifact + row)
            from tests.api.test_stage0_setup_db import _MemoryStorage
            from clue_api.agent_turn_wiring import DurableAgentArtifactStore
            storage = _MemoryStorage()
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
            for path, kind, folder, body in (
                ("company/overview.md", "company-overview", "company", "---\nkind: company-overview\n---\n\n# Company overview\n"),
                ("product/catalog.md", "product-catalog", "product", "---\nkind: product-catalog\nproducts:\n  - {name: Aura, product_id: prd_aura}\n---\n\n# Catalog\n"),
            ):
                ref = await artifacts.persist_body(workspace_id=ws, data=body.encode(), media_type="text/markdown")
                await conn.execute(text(
                    "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, path, kind, version, status, artifact_key, artifact_sha256) "
                    "VALUES (gen_random_uuid(), :ws, :brand, :folder, :path, :kind, 1, 'ready', :key, :sha)"
                ), {"ws": ws, "brand": brand_id, "folder": folder, "path": path, "kind": kind, "key": ref.artifact_key, "sha": ref.sha256})

            launcher = OnboardingSynthesisLauncher.for_tests(  # a classmethod the implementer adds: real wiring on the test's conn/storage, scripted model
                conn=conn, storage=storage, models=_Models(_scripted()), workspace_root=tmp_path / "ws",
            )
            result = await launcher.launch(workspace_id=ws, brand_id=brand_id, run_id=uuid4(), step_id=uuid4())
            assert result.status == "completed", (result.failure_code, result.failure_message)
            rows = (await conn.execute(text(
                "SELECT path, kind, status, produced_by_turn_id IS NOT NULL AS by_turn FROM brand_knowledge_document "
                "WHERE workspace_id = :ws AND folder = 'audience' ORDER BY path"), {"ws": ws})).mappings().all()
            assert [(r["path"], r["kind"], r["status"], r["by_turn"]) for r in rows] == [
                ("audience/icp-gi-groups.md", "icp-definition", "proposed", True),
                ("audience/persona-gi-groups.md", "audience-persona", "ready", True),
            ]
            project_row = (await conn.execute(text("SELECT name, status FROM project WHERE project_id = :p"),
                                              {"p": await ensure_onboarding_project(conn, workspace_id=ws, brand_id=brand_id, brand_name="seed brand")})).mappings().one()
            assert project_row["name"].startswith("Onboarding ·") and project_row["status"] == "archived"

    run_async(scenario())
```

The scripted tool-call argument names (`file_path`, `content`, `status`, `user_message`) must match the deepagents framework tools and `finalize_turn`'s input model — read `tests/api/test_specialist_wiring_db.py` for the exact shapes it scripts and copy them.

- [ ] **Step 3: Write the runner**

Sketch of `platform/api/clue_api/onboarding_synthesis_wiring.py` (fill each method by transcription from the reference runners named in Step 1):

```python
"""The onboarding synthesis turn (ARV2-ONBOARDING-PLAN.md §5; O4) — outside clue_api.arv2 because it
composes the agent/execution substrate. One governed turn per onboarding run, executed inside the
promoted ``onboarding-synthesis-unit@1`` recipe, under a per-brand system project row."""

# constants
EXECUTION_NAMESPACE_KEY = "onboarding-synthesis-unit@1"
TURN_NAMESPACE = UUID("6c2f9d0e-4b3a-5f1e-9a77-0e2b4c8d1f55")
BUDGET_LIMIT_MILLICENTS = 500_000           # $5 record-only ceiling for the C5 policy
SYNTHESIS_CARD_MEDIA_TYPE = "application/vnd.clue.onboarding-synthesis-card+json"
INPUT_PREFIX = "inputs/brand/knowledge/"

async def ensure_onboarding_project(conn, *, workspace_id, brand_id, brand_name) -> str: ...
    # INSERT INTO project (project_id, workspace_id, brand_id, name, status) VALUES (..., 'archived') ON CONFLICT (project_id) DO NOTHING

class OnboardingSynthesisStepPinProvider(StepPinProvider):
    """Pins the audience-persona skill for the evidence tool (kind='skill')."""
    # mirror AccountResearchStepPinProvider: observe_current(kind="skill", key="audience-persona") → PinRequest

def onboarding_synthesis_context_policy() -> ContextAssemblyPolicy:
    # version "onboarding-synthesis-context-v1"; budgets (24_000, 8_000, 64_000, 0, 8_000, 0, 12_000)

def build_onboarding_synthesis_context(*, resolved_profile, artifacts, cards, conn_factory) -> DeterministicAgentContextAssembler:
    # build_agent_context_assembler(... memory=_NoMemoryContext(), memory_recipe=EXECUTION_NAMESPACE_KEY, requested_memory_types=(), policy=onboarding_synthesis_context_policy())

class OnboardingSynthesisLauncher:
    def __init__(self, *, settings, components, tools, tool_invoker, executor, compatibility, plans, recipes, starter, parameters, materializer=None, checkpointer_factory=postgres_agent_checkpointer, conn_factory=transaction): ...

    async def launch(self, *, workspace_id, brand_id, run_id, step_id) -> OnboardingSynthesisResult:
        try:
            return await self._launch(...)
        except Exception as error:  # noqa: BLE001 — the driver's failure law: a step outcome, never a raise
            log.exception("onboarding_synthesis.contained_failure", run_id=str(run_id))
            return OnboardingSynthesisResult("failed", type(error).__name__, str(error)[:500], Decimal(0), ())

    async def _launch(...):
        resolved = self._components.profiles.resolve(AgentRole.ONBOARDING_SYNTHESIS, surface=ONBOARDING_SYNTHESIS_UNIT_SURFACE)
        # 1. inputs: rows = current ready documents for (workspace, brand) [SELECT ... status IN ('ready','proposed','confirmed') and version = max per path];
        #    if the company overview or the catalog is missing → OnboardingSynthesisResult("empty", None, "no inputs", 0, ())
        #    bodies via read_verified_artifact(conn, storage, storage_key=..., workspace_id=...) → WorkspaceSeedFile(path=INPUT_PREFIX + row.path, content, sha256, media_type="text/markdown")
        # 2. project: ensure_onboarding_project(...) using clue_spine.get_brand for the name
        # 3. execution: execution_id = ExecutionId(operation_id_from_key(str(run_id), EXECUTION_NAMESPACE_KEY)); recipe via recipes.get_by_identity(SYSTEM, None, "onboarding-synthesis-unit", 1) (RuntimeError "promoted onboarding-synthesis-unit@1 is not installed" if None); parameters.snapshot(workspace_id, {}); starter.start(workspace_id, recipe_revision_id, {}, parameter_key, parameter_sha, actor="agent", execution_id, project_id); await self._drive_execution(execution_id) (copy _drive_execution verbatim, with a preparer worker id "agent-onboarding-synthesis-preparer")
        # 4. workspace lease: components.workspaces.acquire(workspace_id, project_id, execution_id, policy=resolved.profile.workspace)
        # 5. artifacts: card (SYNTHESIS_CARD_MEDIA_TYPE: {"schema_version": "1", "brand_id", "company_domain", "inputs": [{"path", "kind", "version"}], "persona_vocabulary": ["economic_buyer","champion","user","technical_evaluator","blocker"]}), budget envelope, resource manifest, user message ("Write the ICP documents, then one persona document per ICP, then finalize_turn.") — via a copied _artifact helper
        # 6. request: turn_id = uuid5(TURN_NAMESPACE, f"{run_id}"); thread_id = f"onboarding-synthesis-{run_id}"; AgentConstitution(workspace_id, project_id, execution_id, actor_id="system", role=ONBOARDING_SYNTHESIS, brand_id, workspace_root_id=lease.identity.workspace_root_id, project_card_ref, budget_envelope_ref, profile_ref=resolved.profile_ref, resource_manifest_ref, resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256); AgentTurnRequest(turn_id, thread_id, constitution, user_message_artifact_ref, requested_at=now)
        # 7. turns.create(request, profile); committed = turns.load_committed_outcome(turn_id, workspace_id) → if present, skip to step 10
        # 8. context = contexts.assemble(request, profile, history=()); materialize: self._materializer.materialize(lease, snapshot=resolved.resource_snapshot, seed_files=(*context seeds, *input seeds)) — checking path uniqueness as specialist_wiring does; on a frozen lease verify_materialized
        # 9. execution adapter: C5AgentExecutionAdapter(turn_id, constitution, resolved, policy=AgentPlanPolicy.from_profile(profile, budget_limit_millicents=BUDGET_LIMIT_MILLICENTS, max_fanout=1, max_parallelism=1, max_rounds=profile.max_model_rounds), slot_key="onboarding_synthesis_interactions", tools, tool_invoker, executor, artifacts, journal=plans, checkpointer_factory, pin_provider=OnboardingSynthesisStepPinProvider(compatibility), conn_factory); finalization = AgentFinalizationAuthority(lease, artifacts, turns, crash_hook, conn_factory); bind it as the reference runtime does; governed tools = GovernedAgentToolFactory(request, resolved, registry=tools, execution, lease, artifacts).build(); outcome = await DurableDeepAgentTurnRunner(runtime=DeepAgentTurnRuntime(models=components.models, execution, max_runtime_s=profile.turn_timeout_s, max_rounds=profile.max_model_rounds), turns, artifacts).run(request, resolved_profile=resolved, context, lease, tools=governed)
        # 10. complete the recipe: executor.decide_gate(execution_id, node_key="onboarding_synthesis_interactions", actor="agent", decision="complete"); _drive_execution → COMPLETED
        # 11. outputs → documents: envelope = AgentFinalizeEnvelope.model_validate_json(await artifacts.read(outcome.finalization_ref)); for ref in envelope.output_refs: body = await artifacts.read(ref); front, _ = parse_front_matter(body.decode()); kind, key = document_identity(front); path = f"audience/icp-{key}.md" if kind == "icp-definition" else f"audience/persona-{key}.md"; status = "proposed" if kind == "icp-definition" else "ready"; INSERT brand_knowledge_document (document_id=uuid5(NAMESPACE_URL, f"onboarding-synthesis-doc:{turn_id}:{path}"), workspace_id, brand_id, folder='audience', path, kind, version=max+1 for path, status, artifact_key=ref.artifact_key, artifact_sha256=ref.sha256, produced_by_turn_id=turn_id) ON CONFLICT (document_id) DO NOTHING; supersede the previous ready/proposed version at that path. An output whose front matter has no icp_key or an unknown kind is skipped and logged (never raises).
        # 12. return OnboardingSynthesisResult("completed" if documents else "empty", None, None if documents else "the agent wrote no documents", cost_usd=<sum of tool ledger costs if available else 0>, documents)

    @classmethod
    def for_tests(cls, *, conn, storage, models, workspace_root) -> OnboardingSynthesisLauncher: ...
        # compose every collaborator on conn_session_factory(conn), FsStorage/_MemoryStorage, build_toolbelt(storage=None, gateway=None), a workspace factory rooted at workspace_root, the scripted models, an in-memory checkpointer (see deep/composition.py::_memory_checkpointer_factory), and the real recipe seeder run once on this conn.

def build_onboarding_synthesis_launcher(*, settings, secrets, components, tools, tool_invoker, executor, compatibility, plans, recipes, starter, parameters, conn_factory=transaction) -> OnboardingSynthesisLauncher: ...
```

Escalation points, in order of likelihood: (a) `for_tests` composition — the recipe seeder, execution starter and executor need real wiring; copy from `tests/api/test_agent_runtime_wiring_db.py` / `test_specialist_wiring_db.py` and report NEEDS_CONTEXT with the exact missing collaborator if the test harness cannot compose it; (b) the `skill` pin resolver's key form; (c) `WorkspaceProductLayerSource(cards)` needing a brand card — if it raises for a brand without compiled cards, provide a reader returning `None` and record it.

- [ ] **Step 4: Run, ruff, mypy, commit**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_onboarding_synthesis_wiring_db.py -v && uv run ruff check platform/api/clue_api/onboarding_synthesis_wiring.py tests/api/test_onboarding_synthesis_wiring_db.py && uv run mypy platform/api/clue_api/onboarding_synthesis_wiring.py`

```bash
git add platform/api/clue_api/onboarding_synthesis_wiring.py tests/api/test_onboarding_synthesis_wiring_db.py
git commit -m "feat(api): onboarding synthesis turn — per-brand system project, recipe execution, knowledge documents materialized as inputs, C5-governed deepagent turn, outputs registered as ICP/persona documents; the launcher seam for the onboarding driver"
```

---

### Task 7: Composition, README, close-out; the live turn is founder-triggered

**Files:**
- Modify: `platform/api/clue_api/fleet_main.py`
- Modify: `platform/api/clue_api/arv2/README.md` (a short "O4" paragraph pointing at `onboarding_synthesis_wiring.py`)
- Create: `_memory/2026-09-07-arv2-onboarding-o4-synthesis-agent.md`

- [ ] **Step 1: Compose behind the flag**

In `fleet_main._serve`, where the other components are built (after `components`, `tool_registry`, `executor`, `compatibility`, `plans`, `recipes`, `starter`, `parameters` exist — read the file for their local names):

```python
        synthesis_launcher = None
        if settings.onboarding_v2_enabled:
            from clue_api.onboarding_synthesis_wiring import build_onboarding_synthesis_launcher

            synthesis_launcher = build_onboarding_synthesis_launcher(
                settings=settings, secrets=secrets, components=components, tools=tool_registry,
                tool_invoker=tool_invoker, executor=executor, compatibility=compatibility, plans=plans,
                recipes=recipes, starter=starter, parameters=parameters,
            )
```

If O3's `OnboardingRunWorkHandler` exists in this tree (it will after the O3 merge), pass `synthesis=synthesis_launcher` to it; if it does not exist yet, leave a two-line comment naming the handoff and record it in the memory note as the one merge-time edit.

- [ ] **Step 2: Gates and checklist**

Run: `set -a; source .env; set +a; uv run pytest tests/agents tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py tests/api/test_onboarding_evidence_tools.py tests/api/test_onboarding_synthesis_wiring_db.py tests/db/test_arv2_onboarding_synthesis_role_migration.py tests/arv2 --ignore-glob='*_live.py' -q`; `uv run alembic heads` (one line, or two if O3 merged first — then `alembic merge`); the standing-rule greps: `grep -rn "client_kb_version\|readiness_decision\|project_run_stage0_pins\|evaluate_stage0_readiness" platform/api/clue_api/onboarding_*.py platform/agents/catalog/profiles/onboarding-synthesis platform/agents/catalog/skills/icp-synthesis platform/agents/catalog/skills/audience-persona` → zero hits; profile grants: the profile lists exactly one tool.

- [ ] **Step 3: Memory note + commit**

The note records: the role and migration id, the tool, the recipe, the catalog pins, the runner's shape, the four rulings (per-brand system project row with status `archived`; inputs under `inputs/brand/knowledge/`; the skill as the tool's pin; document identity from front matter), what is composed and what waits for the O3 merge, and that no live turn has run. Add the `_memory/README.md` pointer.

```bash
git add platform/api/clue_api/fleet_main.py platform/api/clue_api/arv2/README.md _memory/2026-09-07-arv2-onboarding-o4-synthesis-agent.md _memory/README.md
git commit -m "chore(api): compose the onboarding synthesis launcher behind CLUE_ONBOARDING_V2_ENABLED; O4 close-out note"
```

- [ ] **Step 4 (founder-triggered, spends ~$0.50 of model + evidence calls): the live synthesis turn**

Only with Aryan's go: with O3 merged and an Insight Health onboarding run's documents present, set `CLUE_ONBOARDING_V2_ENABLED=true`, start the fleet, trigger the synthesis step (through the driver, or a one-off script calling `launch`), and check: 2–3 ICP documents `proposed`, one persona document per ICP `ready`, each persona role section carries evidence URLs when the tool found any, no fictional names. Record cost, rounds and wall time in the memory note; copy the rendered documents into `.context/arv2-onboarding-o4-acceptance/`.
