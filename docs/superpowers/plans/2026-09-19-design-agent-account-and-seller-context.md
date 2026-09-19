# Design Agent Account and Seller Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The design deepagent can read the target account's research through the platform's governed reads whenever it wants, and finds the seller's brand knowledge (company, products, ICP, personas) as files in its session workspace; the brief stays the primary channel and nothing is forced.

**Architecture:** One injected capability, `DesignPlatformReads`, composed at the platform's composition root exactly like the scoped-preference resolver: closures that run on the platform loop (through `asyncio.run_coroutine_threadsafe` with a bounded wait) and are called from the design worker thread. Three closures invoke the governed tools `read_project_accounts@1`, `read_account_research@2` (the paged contract; `@1` is granted to nobody), `read_claims@1` through the worker's shared `ToolInvoker` (the finisher precedent), so every call is journaled and priced like Head-of-ABM's; a fourth reads the opening turn's pinned brand-knowledge documents (`get_knowledge_pin` by the leg's `opened_by_turn_id`, `read_pinned_documents`) plus the project's confirmed product set. The design runtime wraps the three reads as LangChain tools on the solo and trio graphs and writes the seller documents into `workspace/seller/` once per session, stamped by the pin's digest. The three reads are granted to the design role through a new immutable profile version `design@v2`. No bundle change, no envelope change, no migration, no env key.

**Tech Stack:** Python 3.12, `clue_toolbelt` (`ToolInvoker`, `ToolContext`, `operation_id_from_key`), `clue_api.brand_knowledge_context`, `clue_spine.current_project_product_set`, LangChain `@tool`, deepagents 0.6.12, pytest.

**Spec:** `docs/superpowers/specs/2026-09-19-design-agent-account-and-seller-context-design.md` (§3.3's card compilers are superseded by this plan: on this stack the seller's knowledge is the ARV2 brand-knowledge documents, not the old lane's Client-KB cards — ruling "ARV2 schema is the only truth", 2026-09-09).

## Global Constraints

- The brief is untouched. `open_design_leg` gains no field; `DesignTurnEnvelope` gains no field; the bundle body gains no field.
- Scope is the project through the turn's identity, never a tag or an account-id list.
- The design runtime never reads the platform database and imports nothing from `clue_api`, `clue_research`, `clue_spine`: every platform fact reaches it through the injected object, by value.
- Contact-level personal claims reach the agent only through `read_claims@1` under its existing use-class gate; never written to any file.
- The capability exists only on LEG turns (the envelope carries a `leg` block) — the design API's own routes, the CLI and fixtures compose nothing and are byte-identical.
- A catalog version is immutable: the design profile goes to `v2`; `v1` is not edited.
- Skill text (Task 5) is founder-reviewed; land it, then present it in the closing report verbatim.
- No new env key; `.env.example` parity unaffected. No migration.
- DB suites only on the lane DB with `--ignore-glob='*_live.py' -p no:cacheprovider`, `.env` sourced; suites that enqueue design work run with the stack DOWN. Never `make check` or broad pytest with real keys.
- No Claude/AI attribution in commits. Never push.

---

## File map

| File | Responsibility after this plan |
|---|---|
| `platform/agents/catalog/profiles/design/v2/profile.yaml` (create) | design@v1 + three read pins |
| `platform/api/clue_api/agent_registry_wiring.py` | DESIGN in the three reads' authority; active design version v2 |
| `platform/api/clue_api/design_loop_bridge.py` (create) | the platform-loop waiter extracted from `design_memory_runtime` |
| `platform/api/clue_api/design_memory_runtime.py` | uses the shared bridge |
| `platform/api/clue_api/design_platform_reads.py` (create) | `DesignPlatformReads`, `SellerKnowledge`, `build_design_platform_reads_factory` |
| `platform/api/clue_api/design_fleet.py`, `fleet_main.py` | compose and inject the factory |
| `subsystems/clue-design/apps/api/lumen_api/fleet_handler.py` | `DesignTurnHost.platform_reads_factory`, handler kwarg |
| `subsystems/clue-design/apps/api/lumen_api/main.py` | executors resolve `platform_reads` for leg turns; runtime entry points take `platform_reads=` |
| `subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py` | `AgentRuntimeConfig.platform_reads` |
| `.../lumen_agent/platform_reads.py` (create) | the three LangChain tools + `write_seller_knowledge` |
| `.../lumen_agent/workspace.py` | scaffold writes `seller/` |
| `.../lumen_agent/fs_backend.py` | `seller/` read-only under the run root |
| `.../lumen_agent/harness.py`, `harness_web.py`, `prompts.py` | tools on the graphs; gather step names `seller/index.md` |
| `.../knowledge_docs/views/scene/skills/{account-adaptation,scene-brief-copy,tools}/SKILL.md` | the guidance |

---

### Task 1: Grant the three reads to the design role through `design@v2`

**Files:**
- Create: `platform/agents/catalog/profiles/design/v2/profile.yaml`
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (`C6_AGENT_TOOL_AUTHORITY` entries at ~:226-235; `C6_ACTIVE_PROFILE_VERSIONS[AgentRole.DESIGN]` at ~:186)
- Test: `tests/api/test_agent_registry_wiring.py::test_design_profile_resolves_with_the_full_granted_write_surface` (~:902), `tests/agents/test_catalog.py` (whatever pins the profile version set)

**Interfaces:**
- Produces: `registry.resolve(AgentRole.DESIGN)` → profile `v2` with 53 pins: the 49 `design_*`, `finish_design_leg@1`, `read_project_accounts@1`, `read_account_research@1`, `read_claims@1`.

- [ ] **Step 1: Update the pinning test first (red)**

In `test_design_profile_resolves_with_the_full_granted_write_surface`:

```python
    resolved = registry.resolve(AgentRole.DESIGN)
    assert resolved.profile.version == "v2"
    assert len(resolved.profile.tools) == 53
    assert sum(1 for pin in resolved.profile.tools if pin.name.startswith("design_")) == 49
    assert any(pin.address == "finish_design_leg@1" for pin in resolved.profile.tools)
    # 2026-09-19: the design agent reads the target account the way head-of-abm does.
    for address in ("read_project_accounts@1", "read_account_research@1", "read_claims@1"):
        assert any(pin.address == address for pin in resolved.profile.tools), address
```

Add a docstring sentence: "2026-09-19 adds three pins: the account reads, granted so a 1:1 creative can open the account's research itself."

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/api/test_agent_registry_wiring.py -k design_profile -q -p no:cacheprovider`
Expected: FAIL (`version == "v1"`, 50 pins).

- [ ] **Step 3: Mint `design/v2/profile.yaml`**

Copy `profiles/design/v1/profile.yaml` to `profiles/design/v2/profile.yaml`; set `version: v2`; append to the `tools:` list, in the same `- name:` / `version: "1"` form the file uses:

```yaml
  # 2026-09-19 — the account reads (granted to design so a 1:1 creative can open the target
  # account's research itself; same contracts, receipts and journal as head-of-abm's).
  - name: read_project_accounts
    version: "1"
  - name: read_account_research
    version: "1"
  - name: read_claims
    version: "1"
```

Keep every other line identical to v1 (skills, model policy, delegation fields, workspace prefixes). Add the leading comment block: "v2 (2026-09-19): v1 plus the three account reads. Nothing else moves."

- [ ] **Step 4: Registry**

In `agent_registry_wiring.py`: `AgentRole.DESIGN: "v2"` in `C6_ACTIVE_PROFILE_VERSIONS`; and

```python
    "read_project_accounts": (AgentRole.HEAD_OF_ABM, AgentRole.DESIGN),
    "read_account_research": (AgentRole.HEAD_OF_ABM, AgentRole.DESIGN),
    ...
    "read_claims": (AgentRole.HEAD_OF_ABM, AgentRole.DESIGN),
```

with one comment above the block: "2026-09-19: the design role reads the target account with the same three tools (design@v2 pins them; the registry refuses a grant the profile does not pin)."

- [ ] **Step 5: Run the registry, catalog and authority suites**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_agent_registry_wiring.py tests/agents/test_catalog.py tests/api/test_c8_inspection_tools.py tests/api/test_c8_trial_surface.py -q -p no:cacheprovider`
Expected: PASS. If `test_catalog.py` pins the set of catalog versions or a digest, update that pin the way its comments describe (a new version, never an edit of v1).

- [ ] **Step 6: Commit**

```bash
git add platform/agents/catalog/profiles/design/v2 platform/api/clue_api/agent_registry_wiring.py tests/api/test_agent_registry_wiring.py tests/agents/test_catalog.py
git commit -m "feat(registry): design@v2 pins the three account reads; the design role may read the target account's research"
```

---

### Task 2: The platform-side capability: `DesignPlatformReads` and its factory

**Files:**
- Create: `platform/api/clue_api/design_loop_bridge.py`
- Modify: `platform/api/clue_api/design_memory_runtime.py` (`build_design_preference_resolver_factory` ~:176-215 uses the bridge)
- Create: `platform/api/clue_api/design_platform_reads.py`
- Test: `tests/api/test_design_platform_reads_db.py` (create), `tests/api/test_design_memory_runtime_db.py` (unchanged, must stay green)

**Interfaces:**
- Consumes: `clue_toolbelt.ToolInvoker.invoke(name, body, ToolContext)`; `clue_api.brand_knowledge_context.{get_knowledge_pin, read_pinned_documents, confirmed_icp_for_project}`; `clue_spine.current_project_product_set`; `clue_design.envelopes.DesignTurnEnvelope`.
- Produces:

```python
# design_loop_bridge.py
class PlatformLoopBridge:
    def __init__(self, *, loop: asyncio.AbstractEventLoop | None = None, timeout_s: float = 10.0, error: type[Exception] = RuntimeError) -> None: ...
    def wait(self, operation: Callable[[], Coroutine[Any, Any, _T]]) -> _T: ...   # the body of design_memory_runtime.wait, verbatim; raises `error(code)` with the same four codes

# design_platform_reads.py
@dataclass(frozen=True)
class SellerDocument:
    path: str; kind: str; version: int; status: str; body_text: str

@dataclass(frozen=True)
class SellerKnowledge:
    documents_sha256: str | None
    documents: tuple[SellerDocument, ...]
    confirmed_icp_path: str | None
    product_set: dict[str, Any] | None   # {"selection_version": int, "product_ids": [..]}

class DesignPlatformReads:
    """Sync, worker-thread-callable. Every method returns JSON-safe dicts; errors raise DesignPlatformReadError(code)."""
    def read_project_accounts(self, *, query: str | None = None, offset: int = 0, limit: int = 100) -> dict[str, Any]: ...
    def read_account_research(self, *, account_entity_id: str, section: str = "overview", field_prefix: str | None = None, offset: int = 0) -> dict[str, Any]: ...
    def read_claims(self, *, entity_id: str, field_prefix: str | None = None, tier: int | None = None, verification_status: str | None = None, since: str | None = None, offset: int = 0) -> dict[str, Any]: ...
    def seller_knowledge(self) -> SellerKnowledge: ...

class DesignPlatformReadError(RuntimeError): ...

type DesignPlatformReadsFactory = Callable[[DesignTurnEnvelope], DesignPlatformReads | None]

def build_design_platform_reads_factory(*, invoker: ToolInvoker, storage: StorageBackend, conn_factory: ConnFactory = transaction, loop: asyncio.AbstractEventLoop | None = None, timeout_s: float = 20.0) -> DesignPlatformReadsFactory: ...
```

- [ ] **Step 1: Write the failing tests**

`tests/api/test_design_platform_reads_db.py`, modeled on `tests/api/test_design_memory_runtime_db.py:81-112` (same `rollback_conn`, `migrated_db`, `registry`, `run_async`) and on `tests/api/test_brand_knowledge_context_db.py::_seed_document` (~:94) plus `load_or_create_knowledge_pin` (~:391) for the seller side. Build a real `ToolInvoker` the way `tests/api/test_p37_exit_bridge_db.py` builds its finisher's invoker (find its `build_tool_invoker(...)` call and copy it). Seed a workspace, project, brand, one account in the project (the seeding helpers in `tests/api/test_p34_design_leg_engine_db.py` and `tests/_workspace.seed_project`), three brand documents (`company/overview.md` kind `company-overview`, `product/catalog.md` kind `product-catalog`, `audience/icp-x.md` kind `icp-definition`) and a knowledge pin for a turn id `opening_turn`.

```python
def _leg_envelope(workspace_id: str, project_id: str, opening_turn: UUID, *, leg: bool = True) -> DesignTurnEnvelope:
    run_id = f"run_{uuid4().hex}"
    config: dict[str, Any] = {"request": {"prompt": "p", "scene": {}}}
    if leg:
        config["leg"] = {"leg_id": "leg-1"}
        config["delegation_bundle"] = {"brief": "b", "opened_by_turn_id": str(opening_turn)}
    return DesignTurnEnvelope(kind="agent_turn", work_id=work_id_for_run(run_id), workspace_id=workspace_id,
                              run_id=run_id, checkpoint_thread_id=run_id, document_id=None, project_id=project_id, config=config)


def test_a_non_leg_envelope_gets_no_reads(...) -> None:
    factory = build_design_platform_reads_factory(invoker=invoker, storage=storage, conn_factory=conn_factory)
    assert factory(_leg_envelope(ws, prj, opening, leg=False)) is None


def test_the_three_reads_answer_for_the_legs_project_on_the_platform_loop(...) -> None:
    reads = await asyncio.to_thread(factory, _leg_envelope(ws, prj, opening))
    accounts = await asyncio.to_thread(reads.read_project_accounts, query="premier")
    assert accounts["total"] == 1 and accounts["accounts"][0]["canonical_name"] == "Premier Gastroenterology"
    research = await asyncio.to_thread(reads.read_account_research, account_entity_id=accounts["accounts"][0]["account_entity_id"], section="overview")
    assert research["account_name"] == "Premier Gastroenterology"   # overview may be empty: overview_not_written is not a failure
    claims = await asyncio.to_thread(reads.read_claims, entity_id=accounts["accounts"][0]["account_entity_id"])
    assert "claims" in claims and "prefixes" in claims
    # Every call was journaled as a governed invocation under the design run.
    rows = await conn.execute(text("SELECT tool FROM tool_invocation WHERE workspace_id=:w ORDER BY created_at"), {"w": ws})
    assert [r.tool for r in rows] == ["read_project_accounts", "read_account_research", "read_claims"]


def test_seller_knowledge_is_the_opening_turns_pinned_set_plus_the_product_set(...) -> None:
    seller = await asyncio.to_thread(reads.seller_knowledge)
    assert seller.documents_sha256 == pin.documents_sha256
    assert {d.path for d in seller.documents} == {"company/overview.md", "product/catalog.md", "audience/icp-x.md"}
    assert seller.documents[0].body_text.startswith("#")   # front matter split off, markdown kept
    assert seller.product_set == {"selection_version": 1, "product_ids": [...]}   # from the seeded confirmed set; None when the project confirmed none


def test_a_leg_without_a_pin_gets_empty_seller_knowledge_not_an_error(...) -> None:
    seller = await asyncio.to_thread(reads_for_unpinned_turn.seller_knowledge)
    assert seller.documents == () and seller.documents_sha256 is None


def test_calling_from_the_platform_loop_is_refused(...) -> None:
    with pytest.raises(DesignPlatformReadError, match="platform_loop"):
        reads.read_project_accounts()
```

Check the real field names the read tools return (`ReadProjectAccountsOutput.accounts[*]`, `ReadAccountResearchOutput`, `ReadClaimsOutput` in `arv2/read_tools.py` ~:1340-1350, ~:1418-1430, ~:1785-1810) and the `tool_invocation` table's column names before asserting; adjust the assertions to the real names, not the other way round.

- [ ] **Step 2: Run to verify they fail**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_design_platform_reads_db.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: clue_api.design_platform_reads`.

- [ ] **Step 3: Extract the loop bridge**

`design_loop_bridge.py`:

```python
"""One rule for calling the platform from a design worker thread.

The design runtime runs its turn synchronously on a worker thread while the platform owns the
event loop and the connection pool. Anything the design side needs from the platform mid-turn
therefore runs as a coroutine ON the platform loop, with the worker thread blocked for a bounded
wait. First written for the scoped-preference resolver (design_memory_runtime); the account
reads (design_platform_reads) use the same bridge, so there is exactly one place that knows the
four ways this can go wrong.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Coroutine
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, TypeVar

_T = TypeVar("_T")


class PlatformLoopBridge:
    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        timeout_s: float = 10.0,
        error: type[Exception] = RuntimeError,
    ) -> None:
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("platform_loop_timeout_must_be_positive")
        self._loop = loop if loop is not None else asyncio.get_running_loop()
        self._timeout_s = timeout_s
        self._error = error

    def wait(self, operation: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is self._loop:
            raise self._error("platform_loop")
        if self._loop.is_closed() or not self._loop.is_running():
            raise self._error("loop_unavailable")
        pending = operation()
        try:
            future = asyncio.run_coroutine_threadsafe(pending, self._loop)
        except RuntimeError:
            pending.close()
            raise self._error("loop_unavailable") from None
        try:
            return future.result(timeout=self._timeout_s)
        except FutureTimeoutError:
            future.cancel()
            raise self._error("timeout") from None


__all__ = ["PlatformLoopBridge"]
```

In `design_memory_runtime.py`, replace the body of `wait` inside `build_design_preference_resolver_factory` with a bridge whose error codes keep their current names: construct `PlatformLoopBridge(loop=loop, timeout_s=timeout_s, error=_bridge_error)` where `_bridge_error(code)` maps `platform_loop → DesignMemoryRuntimeError("design_memory_platform_loop")`, `loop_unavailable → "design_memory_loop_unavailable"`, `timeout → "design_memory_timeout"`; keep the existing catch-all that turns any other exception into `design_memory_authorization_unavailable`. (Implement `_bridge_error` as a small `DesignMemoryRuntimeError` subclass factory or a function returning the exception instance; `PlatformLoopBridge.error` accepts any callable returning an exception.) `tests/api/test_design_memory_runtime_db.py` must stay green unchanged.

- [ ] **Step 4: Write `design_platform_reads.py`**

```python
"""What the design agent may read from the platform mid-turn (design note 2026-09-19).

Founder ruling: the brief stays the primary channel; the target account is reached by TOOLS, not
files; scope is the project, never a tag; the seller's knowledge is accessible as files. This
module is the platform half. It is composed at the composition root (``fleet_main``) with the
worker's shared ``ToolInvoker`` and storage, and handed to the design turn host — the same shape
as the scoped-preference resolver, for the same reason: the design runtime never opens the
platform database and imports none of this.

Three of the four reads are the governed tools head-of-abm uses (``read_project_accounts@1``,
``read_account_research@1``, ``read_claims@1``), invoked through the journaled invoker under the
turn's workspace, so a design turn's reads are receipts like any other. The fourth is not a tool:
it hands over the seller's brand-knowledge documents as pinned for the turn that OPENED the leg
(``get_knowledge_pin`` by the bundle's ``opened_by_turn_id``), plus the project's confirmed
product set — the same set head-of-abm's own turn seeded, at the same version.

Leg turns only: a direct editor turn has no ``leg`` block and gets ``None``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from clue_api.brand_knowledge_context import (
    confirmed_icp_for_project,
    get_knowledge_pin,
    read_pinned_documents,
)
from clue_api.design_loop_bridge import PlatformLoopBridge
from clue_core import operation_id_from_key
from clue_db import ConnFactory, transaction
from clue_design.envelopes import DesignTurnEnvelope
from clue_spine import current_project_product_set
from clue_storage import StorageBackend
from clue_toolbelt import ToolContext, ToolInvoker
from clue_obs import get_logger

log = get_logger("clue_api.design_platform_reads")


class DesignPlatformReadError(RuntimeError):
    """One code, the way the memory runtime's errors are: platform_loop / loop_unavailable /
    timeout / read_failed. Never carries tool inputs or outputs in its message."""


@dataclass(frozen=True)
class SellerDocument:
    path: str
    kind: str
    version: int
    status: str
    body_text: str


@dataclass(frozen=True)
class SellerKnowledge:
    documents_sha256: str | None
    documents: tuple[SellerDocument, ...]
    confirmed_icp_path: str | None
    product_set: dict[str, Any] | None


EMPTY_SELLER_KNOWLEDGE = SellerKnowledge(None, (), None, None)


class DesignPlatformReads:
    def __init__(
        self,
        *,
        envelope: DesignTurnEnvelope,
        invoker: ToolInvoker,
        storage: StorageBackend,
        conn_factory: ConnFactory,
        bridge: PlatformLoopBridge,
    ) -> None:
        self._envelope = envelope
        self._invoker = invoker
        self._storage = storage
        self._conn_factory = conn_factory
        self._bridge = bridge

    # --- the governed reads -------------------------------------------------------------------

    def _invoke(self, name: str, body: dict[str, Any]) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            result = await self._invoker.invoke(
                name,
                body,
                version="2" if name == "read_account_research" else None,
                context=ToolContext(
                    workspace_id=self._envelope.workspace_id,
                    actor="agent",
                    conn_factory=self._conn_factory,
                    # A read is not idempotent work: every call is its own operation, so the A9
                    # journal never replays an earlier page as the answer to a later one.
                    operation_id=operation_id_from_key(
                        f"{self._envelope.run_id}:{uuid4().hex}", "design-platform-read@1"
                    ),
                ),
            )
            return dict(result.references)

        try:
            return self._bridge.wait(call)
        except DesignPlatformReadError:
            raise
        except Exception:
            log.warning("design_platform_reads.read_failed", tool=name, exc_info=True)
            raise DesignPlatformReadError("read_failed") from None

    def read_project_accounts(self, *, query: str | None = None, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        project_id = self._envelope.project_id
        if project_id is None:
            raise DesignPlatformReadError("read_failed")
        body: dict[str, Any] = {"project_id": project_id, "offset": offset, "limit": limit}
        if query:
            body["query"] = query
        return self._invoke("read_project_accounts", body)

    def read_account_research(self, *, account_entity_id: str, section: str = "overview", field_prefix: str | None = None, offset: int = 0) -> dict[str, Any]:
        body: dict[str, Any] = {"account_entity_id": account_entity_id, "section": section, "offset": offset}
        if field_prefix:
            body["field_prefix"] = field_prefix
        return self._invoke("read_account_research", body)

    def read_claims(self, *, entity_id: str, field_prefix: str | None = None, tier: int | None = None, verification_status: str | None = None, since: str | None = None, offset: int = 0) -> dict[str, Any]:
        body: dict[str, Any] = {"entity_id": entity_id, "offset": offset}
        for key, value in (("field_prefix", field_prefix), ("tier", tier), ("verification_status", verification_status), ("since", since)):
            if value is not None:
                body[key] = value
        return self._invoke("read_claims", body)

    # --- the seller ---------------------------------------------------------------------------

    def seller_knowledge(self) -> SellerKnowledge:
        bundle = self._envelope.config.get("delegation_bundle")
        opened_by = bundle.get("opened_by_turn_id") if isinstance(bundle, dict) else None
        if not opened_by:
            return EMPTY_SELLER_KNOWLEDGE
        workspace_id = self._envelope.workspace_id
        project_id = self._envelope.project_id

        async def read() -> SellerKnowledge:
            async with self._conn_factory() as conn:
                pin = await get_knowledge_pin(conn, workspace_id=workspace_id, turn_id=UUID(str(opened_by)))
                if pin is None:
                    return EMPTY_SELLER_KNOWLEDGE
                documents = await read_pinned_documents(conn, self._storage, pin=pin)
                product_set = (
                    await current_project_product_set(conn, workspace_id=workspace_id, project_id=project_id)
                    if project_id is not None
                    else None
                )
                # The project's pinned ICP: the same resolution head-of-abm's turn makes
                # (agent_turn_fleet_wiring ~:611-640) — copy its `pinned_document_id` source.
                icp = confirmed_icp_for_project(documents, pinned_document_id=<the project's ICP pin document id, read the way the head-of-abm turn reads it>)
            return SellerKnowledge(
                documents_sha256=pin.documents_sha256,
                documents=tuple(
                    SellerDocument(path=d.ref.path, kind=d.ref.kind, version=d.ref.version, status=d.ref.status, body_text=d.body_text)
                    for d in documents
                ),
                confirmed_icp_path=None if icp is None else icp.path,
                product_set=None if product_set is None else {"selection_version": product_set.selection_version, "product_ids": list(product_set.product_ids)},
            )

        try:
            return self._bridge.wait(read)
        except DesignPlatformReadError:
            raise
        except Exception:
            log.warning("design_platform_reads.seller_knowledge_failed", exc_info=True)
            raise DesignPlatformReadError("read_failed") from None


DesignPlatformReadsFactory = Callable[[DesignTurnEnvelope], DesignPlatformReads | None]


def build_design_platform_reads_factory(
    *,
    invoker: ToolInvoker,
    storage: StorageBackend,
    conn_factory: ConnFactory = transaction,
    loop: asyncio.AbstractEventLoop | None = None,
    timeout_s: float = 20.0,
) -> DesignPlatformReadsFactory:
    """Capture the pool-owning loop once; hand each LEG turn its own reads object."""

    bridge = PlatformLoopBridge(loop=loop, timeout_s=timeout_s, error=DesignPlatformReadError)

    def factory(envelope: DesignTurnEnvelope) -> DesignPlatformReads | None:
        if not isinstance(envelope.config.get("leg"), dict):
            return None
        return DesignPlatformReads(envelope=envelope, invoker=invoker, storage=storage, conn_factory=conn_factory, bridge=bridge)

    return factory


__all__ = ["DesignPlatformReadError", "DesignPlatformReads", "DesignPlatformReadsFactory", "SellerDocument", "SellerKnowledge", "build_design_platform_reads_factory"]
```

Resolve the one placeholder in `seller_knowledge` by reading how `agent_turn_fleet_wiring.py` (~:611-640) obtains the project's ICP pin document id (`current_project_icp_pin` from `clue_api.arv2.icp_confirmation`) and calling the same function. Check `ConfirmedIcpRef` has `.path` (else use its document path field). Check `PinnedDocument.ref` field names (`path`, `kind`, `version`, `status` at `brand_knowledge_context.py:~120-130`).

- [ ] **Step 5: Run the tests**

Run: `set -a; source .env; set +a; uv run pytest tests/api/test_design_platform_reads_db.py tests/api/test_design_memory_runtime_db.py -q -p no:cacheprovider`
Expected: PASS. Then `uv run ruff check`/`format --check` on the three modules and the test, `uv run mypy platform/api/clue_api/design_platform_reads.py platform/api/clue_api/design_loop_bridge.py platform/api/clue_api/design_memory_runtime.py`, `uv run lint-imports` (28 kept, 0 broken — `clue_api` may import `clue_toolbelt`, `clue_spine`, `clue_storage`; if a contract refuses one, report it rather than weakening the contract).

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/design_loop_bridge.py platform/api/clue_api/design_memory_runtime.py platform/api/clue_api/design_platform_reads.py tests/api/test_design_platform_reads_db.py
git commit -m "feat(design-leg): DesignPlatformReads — the account reads and the seller's pinned knowledge, callable from the design worker thread"
```

---

### Task 3: Inject the reads into the design turn: host, handler, lane, executors, runtime config

**Files:**
- Modify: `subsystems/clue-design/apps/api/lumen_api/fleet_handler.py` (`DesignTurnHost` ~:120-150; `build_design_job_handler` ~:675-701)
- Modify: `platform/api/clue_api/design_fleet.py` (`build_design_job_handler` extras ~:100-120; `build_design_leg_lane_driver` ~:448-475)
- Modify: `platform/api/clue_api/fleet_main.py` (~:1157 lane driver call; compose the factory beside `design_preference_resolver_factory` ~:1122)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`run_agent_turn_preview` signature ~:9236-9300; scene executor `_execute_agent_turn_job` where `scoped_preferences` is resolved ~:10613-10640 and the runtime call; `run_web_agent_turn` ~:9838 and `_execute_web_turn_job`'s runtime call)
- Modify: `subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py` (`AgentRuntimeConfig`)
- Test: `tests/design/test_design_fleet_turns_db.py` (a host with a fake factory reaches the executor), `subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py` (a leg turn hands `platform_reads` to the runtime; a direct turn hands `None`)

**Interfaces:**
- Produces: `DesignTurnHost.platform_reads_factory: Any = None`; `build_design_job_handler(..., platform_reads_factory=None)` on both sides; `build_design_leg_lane_driver(..., platform_reads_factory=None)`; `run_agent_turn_preview(..., platform_reads: Any = None)` and `run_web_agent_turn(..., platform_reads: Any = None)` → `replace(config, platform_reads=platform_reads)`; `AgentRuntimeConfig.platform_reads: Any | None = None`.

- [ ] **Step 1: Failing tests**

In `subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py`, beside `test_a_leg_scene_turn_runs_inside_the_documents_session` (Task 6 of the previous plan; copy its stub-runner capture pattern):

```python
def test_a_leg_turn_hands_the_platform_reads_to_the_runtime_and_a_direct_turn_does_not(client, monkeypatch) -> None:
    sentinel = object()
    seen: list[Any] = []

    def fake_turn(_prompt, config, **_kwargs):
        seen.append(config.platform_reads)
        return ({"outcome": "clarification_requested", "summary": "?", "run_id": config.run_id, "clarification": {"questions": ["q"]}}, _Tools(...))

    monkeypatch.setattr(agent_harness, "run_deepagent_turn", fake_turn)
    host = _turn_host(client, None); host.platform_reads_factory = lambda envelope: sentinel if "leg" in envelope.config else None
    execute_agent_turn_job(_scene_envelope(doc["id"], ws, _leg_config(doc, 0)), store=store, host=host, event_sink=None)
    execute_agent_turn_job(_scene_envelope(doc["id"], ws, {"request": {...}}), store=store, host=host, event_sink=None)   # no leg block
    assert seen == [sentinel, None]
```

Use the same `AgentRuntimeConfig.from_env` redirection and `assert_model_supports_image_input` stub the neighbouring session test uses. Add the web twin in `test_web_turns.py` if its harness allows the same capture cheaply; otherwise cover the web executor by the host-forwarding assertion only.

- [ ] **Step 2: Run to verify they fail** — `set -a; source .env; set +a; uv run pytest subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py -k platform_reads -q -p no:cacheprovider` → FAIL (`AgentRuntimeConfig has no attribute platform_reads`).

- [ ] **Step 3: Runtime config**

`config.py`, beside `run_id`:

```python
    # Design note 2026-09-19: the platform's reads for a LEG turn — the target account's
    # research through the governed tools, and the seller's pinned knowledge — injected by
    # value as one object the design side calls from its worker thread. None (editor preview,
    # CLI, fixtures, direct turns) means no such tools and no seller files.
    platform_reads: Any | None = None
```

- [ ] **Step 4: Host and handler**

`fleet_handler.py`: `DesignTurnHost` gains `platform_reads_factory: Any = None` with the comment "Authorized envelope → the platform reads for a leg turn, composed by the platform (design note 2026-09-19); the design API's own worker has none." `build_design_job_handler(..., platform_reads_factory: Any = None)` stores it on the host it builds (find how `host_provider`/`DesignTurnHost` is constructed there and thread it through; on the design API's embedded worker path in `main.py:~598-608` pass `getattr(app.state, "platform_reads_factory", None)`).

`design_fleet.py`: `build_design_job_handler(..., platform_reads_factory=None)` adds it to `extras` when not None; `build_design_leg_lane_driver(*, enabled, preference_resolver_factory=None, platform_reads_factory=None)` forwards it.

`fleet_main.py`, beside `design_preference_resolver_factory`:

```python
        design_platform_reads_factory = (
            build_design_platform_reads_factory(
                invoker=tool_invoker, storage=storage, conn_factory=transaction
            )
            if settings.design_runtime_enabled
            else None
        )
```

(imported from `clue_api.design_platform_reads`; `tool_invoker` and `storage` are already in scope at ~:1057 and ~:1153) and pass `platform_reads_factory=design_platform_reads_factory` to `build_design_leg_lane_driver(...)` at ~:1157 AND to the `design_job` drain handler's `build_design_job_handler(...)` call further down (grep `build_design_job_handler(` in `fleet_main.py`), so a queued design job and an inline leg turn get the same reads.

- [ ] **Step 5: Executors**

Scene executor, right after the `scoped_preferences` block (~:10613-10640):

```python
    platform_reads = None
    if leg_block:
        factory = getattr(host, "platform_reads_factory", None)
        if callable(factory):
            try:
                platform_reads = factory(envelope)
            except Exception:
                # Reads are a capability, not a precondition: a turn without them still designs
                # from the brief, exactly as before this note.
                logger.warning("design_turn.platform_reads_unavailable", run_id=envelope.run_id, exc_info=True)
                platform_reads = None
```

and pass `platform_reads=platform_reads` into `run_agent_turn_preview(...)`. `run_agent_turn_preview` gains `platform_reads: Any = None` and, after the session block, `if platform_reads is not None: config = replace(config, platform_reads=platform_reads)`. Same three edits on the web side (`_execute_web_turn_job` + `run_web_agent_turn`).

- [ ] **Step 6: Run** — the two persist/web suites, `tests/design/test_design_fleet_turns_db.py` (stack DOWN), `tests/api/test_fleet_wiring.py -k design`, ruff on changed files. Then commit:

```bash
git add subsystems/clue-design/apps/api/lumen_api platform/api/clue_api/design_fleet.py platform/api/clue_api/fleet_main.py subsystems/clue-design/apps/agent_runtime/lumen_agent/config.py subsystems/clue-design/apps/api/tests tests/design
git commit -m "feat(design): leg turns receive the platform's reads — host, handler, lane driver and executors thread DesignPlatformReads into the runtime config"
```

---

### Task 4: The design runtime: three tools, the seller files, the fence, the prompt

**Files:**
- Create: `subsystems/clue-design/apps/agent_runtime/lumen_agent/platform_reads.py`
- Modify: `.../lumen_agent/workspace.py` (`scaffold_workspace` after the brand card write ~:305)
- Modify: `.../lumen_agent/fs_backend.py` (`_assert_writable` ~:203-225)
- Modify: `.../lumen_agent/harness.py` (`create_design_deepagent` params ~:368-380; `orchestrator_tools` ~:735-760 and the solo `extend` ~:760-770; `author_tools` ~:640-655; `run_deepagent_turn` params ~:910-942 and its `create_design_deepagent(...)` call)
- Modify: `.../lumen_agent/harness_web.py` (`_scaffold_web_workspace` ~:210; `orchestrator_tools` ~:446; `run_deepagent_web_turn` params)
- Modify: `.../lumen_agent/prompts.py` (`build_scene_solo_prompt` gather step ~:1296-1300; `build_orchestrator_prompt`'s equivalent gather line)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_platform_reads.py` (create); `tests/test_workspace_run_isolation.py` (seller read-only); `tests/test_scene_solo_runtime.py` neighbour for the tool list

**Interfaces:**
- Consumes: `config.platform_reads` (duck-typed: `.read_project_accounts(**kw)`, `.read_account_research(**kw)`, `.read_claims(**kw)`, `.seller_knowledge()` returning an object with `.documents_sha256`, `.documents` (each `.path/.kind/.version/.status/.body_text`), `.confirmed_icp_path`, `.product_set`).
- Produces: `make_platform_read_tools(tools, reads) -> list` (three `@tool`s: `read_project_accounts(query: str | None = None, offset: int = 0)`, `read_account_research(account_entity_id: str, section: str = "overview", field_prefix: str | None = None, offset: int = 0)`, `read_claims(entity_id: str, field_prefix: str | None = None, tier: int | None = None, verification_status: str | None = None, since: str | None = None, offset: int = 0)`, each returning a JSON string, errors as an honest string `{"error": "<code>"}`, each recorded via `tools.record("orchestrator", "platform_read", payload={"tool": ..., "ok": bool, "code": ...})`); `write_seller_knowledge(workspace: Path, reads, *, record) -> bool` (writes `seller/index.md` + `seller/<path>` under a `.pin` stamp; returns whether it wrote).
- `AgentWorkspaceBackend(..., readonly_subdirs: tuple[str, ...] = ("seller",))`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_platform_reads.py
class _Reads:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.sha = "abc123"
    def read_project_accounts(self, **kw): self.calls.append(("accounts", kw)); return {"total": 1, "accounts": [{"canonical_name": "Premier"}]}
    def read_account_research(self, **kw): self.calls.append(("research", kw)); raise RuntimeError("boom")
    def read_claims(self, **kw): self.calls.append(("claims", kw)); return {"claims": [], "prefixes": []}
    def seller_knowledge(self):
        return SimpleNamespace(documents_sha256=self.sha, confirmed_icp_path="audience/icp-x.md",
            product_set={"selection_version": 1, "product_ids": ["p1"]},
            documents=(SimpleNamespace(path="company/overview.md", kind="company-overview", version=1, status="ready", body_text="# Acme\nWe do X."),
                       SimpleNamespace(path="product/catalog.md", kind="product-catalog", version=1, status="ready", body_text="# Products\n- p1")))


def test_tools_return_json_and_errors_as_strings_and_record(runtime_tools) -> None:
    reads = _Reads()
    accounts, research, claims = make_platform_read_tools(runtime_tools, reads)
    assert json.loads(accounts.invoke({"query": "prem"}))["total"] == 1
    assert json.loads(research.invoke({"account_entity_id": "x"})) == {"error": "read_failed"}
    assert reads.calls[0] == ("accounts", {"query": "prem", "offset": 0})
    events = [e for e in trace_events(runtime_tools) if e["event"] == "platform_read"]
    assert [e["payload"]["ok"] for e in events] == [True, False]


def test_seller_files_are_written_once_per_pin_and_never_by_the_agent(tmp_path, runtime_tools_with_workspace) -> None:
    reads = _Reads(); ws = workspace_root(runtime_tools_with_workspace)
    assert write_seller_knowledge(ws, reads, record=lambda *a, **k: None) is True
    assert (ws / "seller" / "company" / "overview.md").read_text().startswith("# Acme")
    index = (ws / "seller" / "index.md").read_text()
    assert "product/catalog.md" in index and "audience/icp-x.md" in index and "selection version 1" in index
    assert (ws / "seller" / ".pin").read_text() == "abc123"
    assert write_seller_knowledge(ws, reads, record=lambda *a, **k: None) is False   # same pin: no rewrite
    reads.sha = "def456"
    assert write_seller_knowledge(ws, reads, record=lambda *a, **k: None) is True   # new pin: rewritten


def test_empty_seller_knowledge_writes_nothing(...) -> None: ...
```

And in `test_workspace_run_isolation.py`: a session-scoped backend refuses `write`/`edit` under `/sessions/dsess_a/workspace/seller/x.md` (error result) while `read` works. And in `test_scene_solo_runtime.py` (or a new test beside it, using `offline_models` + `solo_config`): with `platform_reads=_Reads()` on the config the compiled solo graph's tool names include the three reads; without it they do not.

- [ ] **Step 2: Run to verify they fail** — `uv run pytest subsystems/clue-design/apps/agent_runtime/tests/test_platform_reads.py -q -p no:cacheprovider` → `ModuleNotFoundError`.

- [ ] **Step 3: `platform_reads.py`**

```python
"""The platform's reads, as the design agent sees them (design note 2026-09-19).

Three tools — the same three head-of-abm has for the target account — and the seller's pinned
knowledge written into ``workspace/seller/`` once per session. The design runtime never learns
where any of this comes from: ``reads`` is an object the platform injected (config.platform_reads),
and this module only calls it. Every tool answers a JSON string; a failure answers
``{"error": "<code>"}`` and is recorded, never raised — a read the agent could not make is a fact
to design around, not a reason to kill the turn.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from py_lumen_obs import get_logger

logger = get_logger("lumen_agent.platform_reads")

SELLER_DIR = "seller"
_PIN_FILE = ".pin"


def _call(tools: Any, reads: Any, name: str, **kwargs: Any) -> str:
    try:
        payload = getattr(reads, name)(**kwargs)
        tools.record("orchestrator", "platform_read", payload={"tool": name, "ok": True, "args": kwargs})
        return json.dumps(payload, ensure_ascii=False)
    except Exception as error:  # noqa: BLE001 - a refused read is a tool result, never a crash
        code = str(error) or error.__class__.__name__
        tools.record("orchestrator", "platform_read", payload={"tool": name, "ok": False, "code": code, "args": kwargs})
        return json.dumps({"error": code})


def make_platform_read_tools(tools: Any, reads: Any) -> list:
    from langchain_core.tools import tool

    @tool
    def read_project_accounts(query: str | None = None, offset: int = 0) -> str:
        """List the accounts of this project. query narrows by name or domain fragment
        (case-insensitive); the answer's total is the whole filtered membership and its
        accounts list is one page — read again with offset when total is larger. Use this to
        find the account the brief names before reading its research."""
        return _call(tools, reads, "read_project_accounts", query=query, offset=offset)

    @tool
    def read_account_research(account_entity_id: str, section: str = "overview", field_prefix: str | None = None, offset: int = 0) -> str:
        """What research found about one account. section="overview" returns the written
        sections; a researched account whose overview is not written yet answers
        overview_not_written — then read section="claims". Claims come in pages: when
        next_offset is not null, read again with offset=next_offset before you summarize or
        count. field_prefix narrows to one family named in the answer's prefixes."""
        return _call(tools, reads, "read_account_research", account_entity_id=account_entity_id, section=section, field_prefix=field_prefix, offset=offset)

    @tool
    def read_claims(entity_id: str, field_prefix: str | None = None, tier: int | None = None, verification_status: str | None = None, since: str | None = None, offset: int = 0) -> str:
        """A specific question about one account's or one contact's claims: one family
        (field_prefix), one source tier (1 deterministic API .. 4 LLM synthesis), only verified,
        or only since a date. Paged like read_account_research. Quote a fact only with a claim
        behind it; bind it to the claim id the answer gives you."""
        return _call(tools, reads, "read_claims", entity_id=entity_id, field_prefix=field_prefix, tier=tier, verification_status=verification_status, since=since, offset=offset)

    return [read_project_accounts, read_account_research, read_claims]


def _render_index(seller: Any) -> str:
    lines = ["# Seller knowledge", "",
             "The brand's own knowledge documents, as pinned for this design session. Paths are",
             "relative to seller/. Read a document when you need what it holds.", ""]
    if seller.product_set:
        lines.append(f"Confirmed products for this project (selection version {seller.product_set['selection_version']}): "
                     + ", ".join(seller.product_set["product_ids"]))
        lines.append("")
    if seller.confirmed_icp_path:
        lines.append(f"The project's confirmed ICP: {seller.confirmed_icp_path}")
        lines.append("")
    for doc in seller.documents:
        lines.append(f"- {doc.path} — {doc.kind} (v{doc.version}, {doc.status})")
    return "\n".join(lines) + "\n"


def write_seller_knowledge(workspace: Path, reads: Any, *, record: Callable[..., Any]) -> bool:
    """Write ``seller/`` once per pin. Returns True when it wrote, False when current or empty."""

    try:
        seller = reads.seller_knowledge()
    except Exception as error:  # noqa: BLE001
        record("orchestrator", "seller_knowledge_unavailable", payload={"code": str(error) or error.__class__.__name__})
        return False
    if not seller.documents or not seller.documents_sha256:
        return False
    root = workspace / SELLER_DIR
    pin = root / _PIN_FILE
    if pin.is_file() and pin.read_text(encoding="utf-8") == seller.documents_sha256:
        return False
    if root.exists():
        import shutil
        shutil.rmtree(root)
    for doc in seller.documents:
        target = root / doc.path
        if not target.resolve().is_relative_to(root.resolve()) if root.exists() else ".." in Path(doc.path).parts:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc.body_text, encoding="utf-8")
    (root / "index.md").write_text(_render_index(seller), encoding="utf-8")
    pin.write_text(seller.documents_sha256, encoding="utf-8")
    record("orchestrator", "seller_knowledge_written", payload={"documents": len(seller.documents), "pin": seller.documents_sha256[:12]})
    return True


__all__ = ["SELLER_DIR", "make_platform_read_tools", "write_seller_knowledge"]
```

(Implement the path-containment check as a clear two-liner: reject any `doc.path` whose `Path(doc.path).parts` contains `".."` or that is absolute, before any mkdir.)

- [ ] **Step 4: Scaffold, fence, harness, prompt**

`workspace.py` `scaffold_workspace`, after the brand card write: `if tools.config.platform_reads is not None: write_seller_knowledge(workspace, tools.config.platform_reads, record=tools.record)`.

`fs_backend.py`: `__init__(..., readonly_subdirs: tuple[str, ...] = ("seller",))`; in `_assert_writable`, after computing `run_root`, extend `readonly` with `run_root / "workspace" / name for name in self._readonly_subdirs` (the agent's workspace is `<scope>/workspace/`; the seller tree sits inside it). Add the same to the error sentence (`"seller/ is read-only"` when that is the refused root).

`harness.py`: `create_design_deepagent(..., platform_reads: Any = None)`; after `orchestrator_tools` is assembled (both paths) and before the solo `extend`: `if platform_reads is not None: read_tools = make_platform_read_tools(tools, platform_reads); orchestrator_tools[-1:-1] = read_tools` (before finalize, matching how `request_clarification` is inserted) and `author_tools.extend(read_tools)` on the trio path; `run_deepagent_turn(..., platform_reads=None)` forwards it; the scene executor's runtime entry passes `config.platform_reads` — simplest: inside `create_design_deepagent` read `runtime_config.platform_reads` directly instead of a new parameter (choose this; fewer signatures). Record `tools.record("orchestrator", "platform_reads_attached", payload={"tools": [t.name for t in read_tools]})`.

`harness_web.py`: same two edits (`_scaffold_web_workspace` writes seller; `orchestrator_tools` gains the reads when `runtime_config.platform_reads is not None`).

`prompts.py`: in `build_scene_solo_prompt` step 1, change "Gather {workspace}/brief.md, brand_card.json, state.json and" to "Gather {workspace}/brief.md, brand_card.json, state.json, seller/index.md when present, and"; add one sentence at the end of step 2: "When the brief names a target company, the account reads (read_project_accounts, read_account_research, read_claims) are how you learn what research found about it; the account-adaptation skill says how." Mirror the two sentences in `build_orchestrator_prompt`'s gather step. Nothing says optional.

- [ ] **Step 5: Run** — `uv run pytest subsystems/clue-design/apps/agent_runtime/tests/test_platform_reads.py subsystems/clue-design/apps/agent_runtime/tests/test_workspace_run_isolation.py subsystems/clue-design/apps/agent_runtime/tests/test_scene_solo_runtime.py subsystems/clue-design/apps/agent_runtime/tests/test_deepagent_harness.py subsystems/clue-design/apps/agent_runtime/tests/test_session_folder.py subsystems/clue-design/apps/agent_runtime/tests/test_web_substrate.py -q -p no:cacheprovider` (the known image-401 failure aside). Ruff per file vs baseline.

- [ ] **Step 6: Commit** — `git commit -m "feat(lumen-agent): the three account reads as tools and the seller's pinned knowledge as session files; seller/ is read-only"`.

---

### Task 5: The skills, and the report of their text

**Files:**
- Modify: `subsystems/clue-design/apps/agent_runtime/knowledge_docs/views/scene/skills/account-adaptation/SKILL.md` (after the "Bare claim IDs…" paragraph, ~:25-27)
- Modify: `.../views/scene/skills/scene-brief-copy/SKILL.md` (gather paragraph, ~:8-14)
- Modify: `.../views/scene/skills/tools/SKILL.md` (a new short section)
- Modify: `_memory/2026-09-18-design-session-continuity.md` (closing entry)
- Test: `subsystems/clue-design/apps/agent_runtime/tests/test_format_skill_library.py` or whichever test validates skill frontmatter/materialization (run it; no assertion change expected)

- [ ] **Step 1: account-adaptation — insert after the paragraph ending "…cannot support copy."**

```markdown
## Reading the account

When the brief names a target company, you can read what research found about it; you are
not limited to the sentences in the brief.

1. Find the account: `read_project_accounts(query=<name or domain from the brief>)`. Read the
   answer's `total`; if the name is not on the first page, read again with `offset`. Never
   guess a domain or a logo for an account you did not find.
2. Read its research: `read_account_research(account_entity_id, section="overview")`. An answer
   of `overview_not_written` is normal for an account whose write-up is not done; then read
   `section="claims"`. Claims come in pages: when `next_offset` is not null, read again with
   that offset before you state a count or say a field is empty. Narrow with `field_prefix`
   only to a family the answer's `prefixes` lists.
3. Ask a specific question with `read_claims(entity_id, ...)` — one family, one source tier,
   only verified, only since a date, or a contact's claims.

Put what you read into `evidence` (the source and the excerpt) and bind copy to it through
`evidence_refs` with the claim id the read gave you. A fact you did not read is not a fact.
An empty field is an honest answer; narrow the message rather than fill the gap.
A read costs nothing and starts no research.
```

- [ ] **Step 2: scene-brief-copy — extend the gather sentence**

Replace "Read the user request, brand card, available evidence and asset inventory in one gather." with "Read the user request, brand card, `seller/index.md`, available evidence and asset inventory in one gather; `seller/` holds the brand's own knowledge documents (company, products, audience) and the account reads answer for a named target company (see account-adaptation)."

- [ ] **Step 3: tools — a section after "Scene tools"' first paragraph**

```markdown
## Platform reads

`read_project_accounts`, `read_account_research` and `read_claims` answer from the platform's
research for this project: the accounts, one account's written overview or its claims, and a
narrowed claims question for an account or a contact. They return JSON; a refusal returns
`{"error": ...}` to design around. They are present on a chat-opened design session and absent
in the editor's own agent box and the CLI. The account-adaptation skill says when and how to
use them. `seller/index.md` lists the brand's knowledge documents written into this workspace.
```

- [ ] **Step 4: Memory closing entry** — commits, verification, the owed live acceptance (spec §6), and "skill text landed pending founder review (presented in the closing report)".

- [ ] **Step 5: Run the skill-library test and the solo runtime test** (a materialized workspace must still validate); commit:

```bash
git add subsystems/clue-design/apps/agent_runtime/knowledge_docs _memory/2026-09-18-design-session-continuity.md
git commit -m "docs(design-skills): account-adaptation teaches the account reads; scene-brief-copy and tools name seller/ and the reads"
```

---

### Task 6: Gates and live acceptance

- [ ] Static: `uv run ruff check` + `format --check` on every touched platform/clue_design/test file; `uv run mypy` (root gate; 0 errors expected on the changed modules, the pre-existing four elsewhere); `uv run lint-imports` (28 kept / 0 broken — a new contract break means `clue_api` must not import one of the libs used; report, do not weaken).
- [ ] Suites with the stack DOWN, `.env` sourced: `tests/api/test_design_platform_reads_db.py tests/api/test_design_memory_runtime_db.py tests/api/test_agent_registry_wiring.py tests/agents/test_catalog.py tests/design/test_design_fleet_turns_db.py tests/api/test_p37_exit_bridge_db.py tests/api/test_design_leg_session_db.py`; `subsystems/clue-design/apps/api/tests/test_scene_turn_persist.py test_web_turns.py test_agent_run_write_lock.py`; the agent-runtime suites named in Task 4. Stack UP after.
- [ ] Live acceptance (founder-triggered, spends money): spec §6 items 1–3. Evidence to capture: the turn's `trace.jsonl` showing `platform_reads_attached`, `seller_knowledge_written` (first turn of the session only) and `platform_read` events; `creative-direction.json` with an `evidence_refs` entry naming a claim id from a read; `tool_invocation` rows for the reads under the design run; Langfuse tool spans under `design-leg.turn`.

---

## Self-review

- **Spec coverage.** §3.1 brief unchanged → Global Constraints. §3.2 reads for the design role + the injection bridge → Tasks 1–3. §3.3 seller files → Task 2 (`seller_knowledge`) + Task 4 (`write_seller_knowledge`, read-only fence, index listing the ICP and product set — the "audience" open point is resolved by the pinned set already containing the ICP and personas). §3.4 skills → Task 5. §3.5 unchanged surfaces → no task touches them. §4 cost → reads journaled like Head-of-ABM's (Task 2). §5 open points: audience ships (in the pinned set); markdown rendering is the documents' own markdown; the spill path — the read tools' spilled receipts name a file under the HEAD-OF-ABM workspace, which the design backend cannot read; Task 2's `_invoke` returns `result.references` and a spilled receipt would carry `spilled_to` — **ruling for the implementer:** when a returned mapping has `spilled_to`, the platform side reads that artifact and inlines it as `body` before returning (find `spilled_to` in `arv2/read_tools.py` to see what it names); if it is not an artifact key, return the receipt unchanged and report. §6 acceptance → Task 6.
- **Placeholder scan.** One deliberate resolution instruction in Task 2 (the ICP pin document id: copy the head-of-abm turn's call) and one in Task 5 (`spilled_to` handling) — both name the file and lines to read; no TBDs.
- **Type consistency.** `platform_reads` is the same attribute name on `AgentRuntimeConfig` (Task 3), read by `create_design_deepagent`/`_scaffold_web_workspace`/`scaffold_workspace` (Task 4); `DesignPlatformReads` methods (Task 2) match the kwargs `make_platform_read_tools` passes (Task 4); `SellerKnowledge` fields (Task 2) match `write_seller_knowledge`'s reads (Task 4); `platform_reads_factory` is the same kwarg on both `build_design_job_handler`s and on `DesignTurnHost` (Task 3).
