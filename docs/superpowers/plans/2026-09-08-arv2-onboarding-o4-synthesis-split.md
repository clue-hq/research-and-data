# ARV2 Onboarding O4 follow-up — Synthesis Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The ICP documents reach the Knowledge page about six minutes after the onboarding request instead of about seventeen, and the persona phase runs one turn per ICP in parallel — with no change to what the model reasons over or writes.

**Architecture:** The one synthesis turn becomes `1 + N` governed turns under the same recipe and system project: one ICP turn (evidence tool withheld by a declared surface) whose outputs are registered the moment it finalizes, then one persona turn per registered ICP, fanned out by the driver as visible `persona` steps under the existing concurrency cap. The core input documents are delivered in the opening context through the L5 focus layer (a new `brand_knowledge_document` card type) and are also seeded on disk so citations keep their paths; prior ICPs are shown to the ICP turn with a "known ICPs" rule, prior personas are shown to nobody.

**Tech Stack:** Python 3.12, `clue_agents` context/runtime, `clue_api` composition, SQLAlchemy async `text()` SQL, Alembic, pytest with `rollback_conn` and `ScriptedAgentChatModel`.

**Spec:** `docs/superpowers/specs/2026-09-08-arv2-onboarding-o4-synthesis-split-design.md` (approved 2026-09-08). Parent: `docs/specs/ARV2-ONBOARDING-PLAN.md` §5–§6 (S5–S7). Facts file: none — every signature is quoted inline below.

## Evidence (why this shape)

Runs `280cd8f5` and `54246e39` (Insight Health, 2026-09-08): synthesis 717 s and 863 s. Workspace file times and `agent_model_call` rows show the ICPs written at 3m50s and 3m56s after the turn started (seven read calls, then one 133 s write of ~10k tokens), then 15 evidence searches in three batches and two persona write calls of 134 s and 215 s. All six `brand_knowledge_document` rows carry the same `created_at` — the turn's end. The launcher's `_current_input_documents` has no kind filter, so run 4 read run 3's ICPs **and personas**. Run 2's aborted synthesis had chosen a different ICP key set, so key drift between runs is real. The persona front matter says `icp_version: 1` while the ICP row is version 2, because the skill hardcodes `1`.

## Global Constraints

- **Standing rule (catalog contract §10):** no Client-KB version, readiness decision or Stage-0 pin anywhere on this path.
- **Import guard:** `clue_api.arv2` imports only `clue_*` libs and `clue_research.claimstore`; the launcher lives in `clue_api/onboarding_synthesis_wiring.py` (outside `arv2`) because it composes the agent substrate — keep it there.
- **No model, effort, timeout or budget change.** Profile v2 differs from v1 only in the prompt and skill pins.
- **Governed, not promised:** the ICP turn's inability to call `exa_search_evidence` is a surface policy (`AgentSurfacePolicy`), never prose.
- **Replay stays exact per turn:** every turn keeps `load_committed_outcome` short-circuit; document ids stay `uuid5(NAMESPACE_URL, f"onboarding-synthesis-doc:{turn_id}:{path}")`.
- **Failure law:** every launcher failure is a step outcome, never a raise. A persona turn never writes or supersedes an ICP row.
- **Alembic:** hash id off the single head `a3602967bb73` (2026-09-08). The parallel catalog-identity-ladder lane also chains off `a3602967bb73`; whichever merges second runs `alembic merge`. Reversible; smoke on the throwaway `clue_o4_agent` only.
- **Tests:** offline suites via `uv run pytest tests/arv2 tests/api/test_onboarding_synthesis_wiring_db.py tests/api/test_agent_registry_wiring.py tests/api/test_fleet_wiring.py tests/api/test_recipe_contracts.py --ignore-glob='*_live.py'`; DB tests on `clue_o4_agent`; never `make check` or a broad pytest with keys in `.env`.
- **Commits:** local only, never push; no AI attribution; one commit per task with the message given.

---

## File Structure

| Path | Responsibility |
|---|---|
| `alembic/versions/<hash>_arv2_onboarding_persona_step.py` | **Create.** Widen `onboarding_step_kind` to admit `'persona'`. |
| `platform/api/clue_api/account_research_turn_wiring.py` | **Modify.** `DbCompiledContextCardReader.read` gains `object_type == "brand_knowledge_document"`. |
| `platform/agents/catalog/prompts/onboarding-synthesis/v2/SYSTEM.md` | **Create.** One task per turn. |
| `platform/agents/catalog/skills/icp-synthesis/v2/SKILL.md` | **Create.** Known-ICPs rule; product-file rule. |
| `platform/agents/catalog/skills/audience-persona/v2/SKILL.md` | **Create.** One ICP per turn; `icp_version` from the user message. |
| `platform/agents/catalog/profiles/onboarding-synthesis/v2/profile.yaml` | **Create.** Pins prompt v2 + skills v2; v1 → `status: retired`. |
| `platform/api/clue_api/agent_registry_wiring.py` | **Modify.** `ONBOARDING_ICP_SURFACE = "onboarding_icp"`; a policy in `C6_SURFACE_POLICIES` withholding `exa_search_evidence`. |
| `platform/api/clue_api/onboarding_synthesis_wiring.py` | **Modify.** `launch_icps` / `launch_persona`; input selection; focus refs; identities; `RegisteredIcp`; L5 budget. |
| `platform/api/clue_api/arv2/onboarding_driver.py` | **Modify.** `SynthesisLauncher` protocol (two calls); `_synthesis_step` returns the ICPs; `_persona_step`; fan-out join. |
| `platform/api/clue_api/fleet_main.py` | **Modify.** `_SynthesisSeam` adapts both calls. |
| `docs/specs/ARV2-ONBOARDING-PLAN.md`, `platform/api/clue_api/arv2/README.md`, `_memory/…` | **Modify/Create.** |
| Tests | `tests/db/test_arv2_onboarding_persona_step_migration.py`, `tests/api/test_agent_platform_wiring.py` (extend: card reader), `tests/api/test_agent_registry_wiring.py` (re-pin + surface), `tests/api/test_recipe_contracts.py` (unchanged, must stay green), `tests/api/test_onboarding_synthesis_wiring_db.py` (rewrite the scenario for two turns), `tests/arv2/test_onboarding_driver.py` (extend), `tests/api/test_fleet_wiring.py` (extend). |

---

### Task 1: The `persona` step kind (migration) and the knowledge-document context card

**Files:**
- Create: `alembic/versions/<hash>_arv2_onboarding_persona_step.py`
- Modify: `platform/api/clue_api/account_research_turn_wiring.py` (`DbCompiledContextCardReader.read`)
- Test: `tests/db/test_arv2_onboarding_persona_step_migration.py`, `tests/api/test_agent_platform_wiring.py` (extend)

**Interfaces:**
- Produces: `onboarding_step.kind` admits `'persona'` (CHECK `onboarding_step_kind` becomes `kind IN ('overview','lineup','catalog_sync','reviews','synthesis','product_research','persona')`); `downgrade()` restores the six-value CHECK and fails loud (`RAISE`) if a `persona` row exists.
- Produces: `DbCompiledContextCardReader.read(workspace_id=, object_type="brand_knowledge_document", object_id=<document_id>)` returns a `CompiledContextCard` whose `body` is the document's verified markdown (`read_verified_artifact(conn, storage, storage_key=artifact_key, workspace_id=workspace_id)`) and whose `ref.version` is `brand_knowledge_document.version`; returns `None` when the row is absent, belongs to another workspace, or has no `artifact_key`. The reader needs a `StorageBackend` for this type: add `storage: StorageBackend | None = None` to `__init__`; when `storage is None` the new type returns `None` (every existing caller passes nothing and is unaffected).
- Consumes: `brand_knowledge_document` (`document_id, workspace_id, brand_id, path, kind, version, status, artifact_key, artifact_sha256`).

**Steps:**
- [ ] Write the migration test: after upgrade, the CHECK definition contains `'persona'`; a `persona` step row with `subject_ref` inserts; `alembic downgrade <prev>` then `upgrade head` round-trips on `clue_o4_agent`.
- [ ] Write the card-reader test: seed one `brand_knowledge_document` + artifact through `DurableAgentArtifactStore.persist_body` on a `rollback_conn`; `read(...)` returns the body and version; cross-workspace read returns `None`; a reader built without `storage` returns `None` for this type.
- [ ] `uv run alembic revision -m "arv2 onboarding persona step"`; `down_revision = "a3602967bb73"`; `ALTER TABLE onboarding_step DROP CONSTRAINT onboarding_step_kind; ADD CONSTRAINT … CHECK (kind IN (...,'persona'))`; reversible.
- [ ] Implement the card type; keep the existing types byte-identical.
- [ ] Run: `uv run pytest tests/db/test_arv2_onboarding_persona_step_migration.py tests/api/test_agent_platform_wiring.py -q` on `clue_o4_agent`.
- [ ] Commit: `feat(arv2 o4): persona step kind + brand_knowledge_document context card`

---

### Task 2: Prompt v2, skills v2, profile v2, the ICP surface

**Files:**
- Create: `platform/agents/catalog/prompts/onboarding-synthesis/v2/SYSTEM.md`, `platform/agents/catalog/skills/icp-synthesis/v2/SKILL.md`, `platform/agents/catalog/skills/audience-persona/v2/SKILL.md`, `platform/agents/catalog/profiles/onboarding-synthesis/v2/profile.yaml`
- Modify: `platform/agents/catalog/profiles/onboarding-synthesis/v1/profile.yaml` (`status: retired`), `platform/api/clue_api/agent_registry_wiring.py`
- Test: `tests/api/test_agent_registry_wiring.py`

**Interfaces:**
- Produces: `ONBOARDING_ICP_SURFACE = "onboarding_icp"` and `AgentSurfacePolicy(surface=ONBOARDING_ICP_SURFACE, role=AgentRole.ONBOARDING_SYNTHESIS, withheld_tools=frozenset({"exa_search_evidence"}))` appended to `C6_SURFACE_POLICIES`. `profiles.resolve(AgentRole.ONBOARDING_SYNTHESIS, surface=ONBOARDING_ICP_SURFACE)` yields an effective tool set without the evidence tool and the same `profile_ref`/manifest digest.
- The v2 texts are reviewed by the founder in this plan and copied **verbatim**. The format blocks (front matter shapes) are unchanged from v1 and are not repeated here — copy them from v1.

**Prompt v2 (`SYSTEM.md`, front matter as v1 with `version: v2`):**

```
You are the onboarding synthesis agent for a B2B account-based marketing platform. Your client is
the company described in inputs/brand/knowledge/company/overview.md. Each turn gives you exactly
one task in the user message: either "icp" (write the client's ideal customer profiles) or
"persona:<icp_key>" (write the audience-persona document for that one profile). Do only the task
you were given.

The documents you need most are already in your context, and the same text is on disk under
inputs/brand/knowledge/ so you can cite it by path: company/overview.md, product/catalog.md,
proof/customer-reviews.md when it exists, and the ICP files. Product research files are on disk
under inputs/brand/knowledge/product/; read the ones the task needs. Do not state a fact about
the client that these files do not contain, unless the evidence tool returns a cited passage.
Cite the file path in parentheses after any specific fact. When a file lists something under
"Not established", you may not assert it.

Write every output file under outputs/audience/. When the task is done, call finalize_turn with
status "completed" and a one-paragraph user message naming each file you wrote.

Write plainly. No em-dashes. No platitudes. Prefer fewer, sourced bullets over a filled quota.
When you are inferring, say "inference".
```

**ICP skill v2 (`SKILL.md`, front matter as v1 with `version: v2`; body):**

```
# ICP synthesis

Produce two to three ideal customer profiles for the client. Each profile is one markdown file
outputs/audience/icp-<key>.md in the ICP artifact format (front matter + body, see the format
block below). Decide the number of profiles from the product lineup and the customer segments in
inputs/brand/knowledge/company/overview.md: one profile per distinct buyer motion, not one per
product. Each profile names the product_ids it sells, from
inputs/brand/knowledge/product/catalog.md. Read the product research file for each product a
profile names (inputs/brand/knowledge/product/<slug>.md) before writing that profile's gates.

ICPs already on file. When the user message lists ICPs already on file, they are in your context
under their paths (inputs/brand/knowledge/audience/icp-<key>.md). For each buyer motion you
would propose, first check whether an ICP on file already describes that motion. If it does,
reuse its icp_key exactly and rewrite the profile from the current research; a re-run refines a
profile, it does not rename it. Propose a new icp_key only for a buyer motion that no ICP on file
describes. Do not carry a key forward just to fill a slot: if the research no longer supports an
ICP on file, leave it out and say so in your finalize_turn message.

For each profile:
- hard_gates: pass/fail rules with a test a researcher can run (industry, size band, geography,
  stack or system in use, hiring, regulatory status). Write the rule and its test.
- exclusions: who is explicitly out, and why.
- persona_map: which of economic_buyer, champion, user, technical_evaluator, blocker exist at
  this account type, each with the titles that hold it.
- qualifier_fields: the client-specific facts research must find per account, each as
  {field_key, description}; the description is the research instruction. Reuse an existing key
  when one fits; otherwise name a new one under account.*.
- body: the human-readable definition in priority order; TAM/list-math estimate and whether to
  widen, tier or shrink; disqualifiers and red flags; the client's own phrasing of who they sell
  to, quoted from inputs/brand/knowledge/company/overview.md or reviews; the qualification-floor
  verdict.

Every gate must trace to something in the files: a customer segment, a named customer, a
regulatory posture, an integration, a review theme. If you cannot trace it, drop it. Set
status: proposed. Never write a project id, a version number or a product id you were not given.
Do not call any evidence tool in this task; the profiles come from the files.

## The ICP artifact format (write exactly this front matter)
<the v1 block, unchanged>

Omit a persona_map role that does not exist at this account type. The body follows the front matter.
```

**Persona skill v2 (`SKILL.md`, front matter as v1 with `version: v2`; body — only the first paragraph and the format block change):**

```
# Audience personas

You are a customer research strategist writing for a B2B account-based marketing team. The user
message names one ICP: its key, its file (inputs/brand/knowledge/audience/icp-<key>.md, also in
your context) and its version. Write outputs/audience/persona-<key>.md for that ICP with one
section per role in its persona_map, in this order: economic_buyer, champion, user,
technical_evaluator, blocker. Skip a role only if the ICP omits it.

<paragraphs 2–4 and the numbered sections 1–11 and the Rules paragraph: verbatim from v1>

## The persona artifact format (write exactly this front matter)

---
kind: audience-persona
icp_key: <the ICP's key>
icp_version: <the ICP version the user message names>
personas:
  - role: economic_buyer
    titles: [<the section-2 titles>]
    buying_triggers: [<the section-7 triggers>]
    evidence_urls: [<every URL the evidence tool returned that you used>]
---
```

**Profile v2:** copy v1, set `version: v2`, `prompt.version: v2` + its sha, `skills[*].version: v2` + shas, header comment updated ("ICP turn and per-ICP persona turns; the ICP turn runs on the `onboarding_icp` surface"). Set v1 `status: retired`.

**Steps:**
- [ ] Write the registry test changes: `AgentRole.ONBOARDING_SYNTHESIS` digest re-pinned (measure off the tree after the resources exist — run the test once, copy the printed/asserted digest, never hand-derive); a new test that `resolve(..., surface=ONBOARDING_ICP_SURFACE)` withholds `exa_search_evidence` and keeps `profile_ref` and `aggregate_sha256` equal to the unnarrowed resolution.
- [ ] Create the four resource files verbatim from this plan; compute each sha as `hashlib.sha256(<file bytes>).hexdigest()`, which is what `clue_agents.catalog` does at load (`catalog.py:366`); retire v1.
- [ ] Add the surface constant and policy; keep `ONBOARDING_SYNTHESIS_UNIT_SURFACE` as is.
- [ ] Run: `uv run pytest tests/api/test_agent_registry_wiring.py tests/api/test_recipe_contracts.py -q`.
- [ ] Commit: `feat(arv2 o4): onboarding-synthesis@v2 — one task per turn, known-ICPs rule, icp surface`

---

### Task 3: The launcher — ICP turn, persona turn, inputs up front

**Files:**
- Modify: `platform/api/clue_api/onboarding_synthesis_wiring.py`
- Test: `tests/api/test_onboarding_synthesis_wiring_db.py` (rewrite the scenario)

**Interfaces (all in `onboarding_synthesis_wiring.py`):**

```python
@dataclass(frozen=True)
class RegisteredIcp:
    document_id: UUID
    icp_key: str
    version: int
    path: str  # "audience/icp-<key>.md"

@dataclass(frozen=True)
class IcpSynthesisResult:
    status: Literal["completed", "empty", "failed"]
    failure_code: str | None
    failure_message: str | None
    cost_usd: Decimal
    icps: tuple[RegisteredIcp, ...]

class OnboardingSynthesisLauncher:
    async def launch_icps(self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID) -> IcpSynthesisResult: ...
    async def launch_persona(self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID, icp: RegisteredIcp) -> OnboardingSynthesisResult: ...
```

- `launch(...)` (the old one-turn entry) is **deleted**; `OnboardingSynthesisResult` keeps its shape and is the persona result.
- Identities: ICP `execution_id = ExecutionId(operation_id_from_key(f"{run_id}:icp", EXECUTION_NAMESPACE_KEY))`, `turn_id = uuid5(TURN_NAMESPACE, f"{run_id}:icp")`; persona `…(f"{run_id}:persona:{icp.icp_key}", …)`, `uuid5(TURN_NAMESPACE, f"{run_id}:persona:{icp.icp_key}")`; `thread_id = f"onboarding-synthesis-{run_id}-icp"` / `-persona-{icp_key}`.
- Input selection (one private function, tested directly):

```python
@dataclass(frozen=True)
class _TurnInputs:
    focus: tuple[dict[str, Any], ...]   # document rows put in the opening context (L5)
    seeds: tuple[dict[str, Any], ...]   # document rows seeded under inputs/ (superset of focus)

def _select_inputs(rows: Sequence[dict[str, Any]], *, task: Literal["icp", "persona"],
                   icp: RegisteredIcp | None = None,
                   product_ids_of: Callable[[dict[str, Any]], frozenset[str] | None] = ...) -> _TurnInputs
```
  Rules: `audience-persona` rows are never selected. Core = `company-overview`, `product-catalog`, `customer-reviews`. ICP task: focus = core + every `icp-definition`; seeds = focus + every `product-research`. Persona task: focus = core + the one `icp-definition` row whose `document_id == icp.document_id` (fail the turn `icp_document_missing` if absent); seeds = focus + the `product-research` rows whose front-matter `product_id` is in the ICP's `product_ids` or whose `product_id` is unreadable. `_REQUIRED_INPUT_KINDS` unchanged.
- Focus refs: `DomainObjectRef(workspace_id=..., object_type="brand_knowledge_document", object_id=str(document_id), version=int(version))` for each focus row, in `_TurnInputs.focus` order, passed as `AgentTurnRequest.focus_refs`. `DbCompiledContextCardReader(conn_factory=..., storage=self._storage)`.
- `onboarding_synthesis_context_policy()`: L5 budget `8_000 → 262_144`; version string `onboarding-synthesis-context-v2`.
- The card (`SYNTHESIS_CARD_MEDIA_TYPE`) gains `"task": "icp" | "persona"`, `"icp": {key, document_id, version} | None`, `"context_paths": [...]`, `"seeded_paths": [...]`; `schema_version` stays `"1"` → bump to `"2"`.
- User message artifact: `objective` is, for ICP: `Task: icp. Write the ICP documents, then finalize_turn.` plus, when any `icp-definition` row was selected, `ICPs already on file: <key> (inputs/brand/knowledge/audience/icp-<key>.md, version <n>); ...`. For persona: `Task: persona:<key>. The ICP is inputs/brand/knowledge/audience/icp-<key>.md, version <n>. Write outputs/audience/persona-<key>.md, then finalize_turn.` Keep `onboarding_run_id`, `onboarding_step_id`, `input_paths`.
- Surface: ICP turn resolves `self._components.profiles.resolve(AgentRole.ONBOARDING_SYNTHESIS, surface=ONBOARDING_ICP_SURFACE)`; persona turn resolves unnarrowed (as today).
- Registration: `_register_documents` unchanged in mechanism; `launch_icps` returns `RegisteredIcp` per registered `icp-definition` row (query the inserted rows back by `document_id` for `version`); a persona turn that wrote an `icp-definition` output gets that output skipped and logged `onboarding_synthesis.persona_wrote_icp` (never registered). A persona turn whose output `icp_key != icp.icp_key` is skipped and logged likewise.
- Failure law unchanged: both public calls catch and return a failed result.

**Steps:**
- [ ] Write the tests first, on `rollback_conn` with `for_tests` (add `storage` to the card reader it composes):
  - `_select_inputs` table test (offline): the six rules above, including "unreadable product_id is kept" and "persona turn with the ICP row missing fails `icp_document_missing`".
  - Two-turn scenario: seed overview + catalog + one product-research file with `product_id: prd_aura` + one with `product_id: prd_other`; script the ICP turn as `write_file(icp) → finalize_turn` (no reads — assert via the receipts that the overview/catalog bodies are in L5 `included` with `materialized_path` under `context/focus/`), assert `IcpSynthesisResult.icps == (RegisteredIcp(..., "gi-groups", 1, "audience/icp-gi-groups.md"),)` and the ICP row exists with `status='proposed'` **before** any persona turn; then script the persona turn as `exa_search_evidence → write_file(persona) → finalize_turn`, assert the persona row, `icp_version` honoured as the ICP's version, and that the seeded `inputs/` tree of the persona turn contains `product/aura.md` and not `product/other.md`.
  - Re-run scenario: a second `launch_icps` on a new `run_id` gets the prior ICP in focus (receipt), writes version 2 with `supersedes_document_id`; a persona turn for version 2 writes `icp_version: 2`.
  - Surface: the ICP turn's scripted `exa_search_evidence` call is refused as not-installed (turn still completes — assert on the tool-result outcome, mirroring the existing docstring's reasoning) while the persona turn's call reaches the toolbelt (`exa_not_configured`).
- [ ] Implement; delete `launch`; update `__all__`, module docstring, `for_tests`.
- [ ] Run: `uv run pytest tests/api/test_onboarding_synthesis_wiring_db.py -q` on `clue_o4_agent`.
- [ ] Commit: `feat(arv2 o4): split synthesis into an ICP turn and per-ICP persona turns; inputs in opening context`

---

### Task 4: The driver fan-out and the composition seam

**Files:**
- Modify: `platform/api/clue_api/arv2/onboarding_driver.py`, `platform/api/clue_api/fleet_main.py`
- Test: `tests/arv2/test_onboarding_driver.py` (extend), `tests/api/test_fleet_wiring.py` (extend)

**Interfaces (`onboarding_driver.py`):**

```python
@dataclass(frozen=True)
class IcpRef:            # the driver's view of RegisteredIcp; no import from clue_api outside arv2
    document_id: UUID
    icp_key: str
    version: int
    path: str

@dataclass(frozen=True)
class IcpSynthesisOutcome:
    status: Literal["completed", "empty", "failed"]
    failure_code: str | None
    failure_message: str | None
    cost_usd: Decimal
    icps: tuple[IcpRef, ...]

class SynthesisLauncher(Protocol):
    async def launch_icps(self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID) -> IcpSynthesisOutcome: ...
    async def launch_persona(self, *, workspace_id: str, brand_id: str, run_id: UUID, step_id: UUID, icp: IcpRef) -> SynthesisOutcome: ...
```

- `_synthesis_step(scope) -> tuple[IcpRef, ...]`: opens `kind="synthesis", phase="fast"` as today; calls `launch_icps`; lands the step with the outcome; returns `outcome.icps` on `completed`, `()` otherwise.
- `_persona_step(scope, icp: IcpRef) -> None`: `kind="persona", phase="background", subject_ref=icp.icp_key`; calls `launch_persona`; lands the step; contained like the others; `_NO_SYNTHESIS` empties apply only to the `synthesis` step (no persona steps are opened when no launcher is composed).
- Run flow: after the fast gather, `synthesis_task` stays a task; the persona fan-out is `bounded(self._persona_step(scope, icp)) for icp in await synthesis_task`, awaited **together with** the product fan-out under the one semaphore, then `finish_run`. Concretely: create `synthesis_task`; start the product `bounded(...)` tasks; `icps = await synthesis_task`; gather the persona `bounded(...)` tasks; gather the product tasks; `finish_run`. The order guarantees persona turns start the moment ICPs land, not after products finish.
- `fleet_main._SynthesisSeam`: two methods, field-for-field copies (`RegisteredIcp → IcpRef`, `IcpRef → RegisteredIcp`).

**Steps:**
- [ ] Driver tests first (offline `FakeStore`/`FakeExa` harness):
  - ICP completes with two ICPs → `start_step("synthesis")`, then `start_step("persona", "<key>")` ×2, all finish `completed`, run `completed`.
  - ICP `failed` → no `persona` step opened; run `completed_with_gaps`.
  - One persona `failed`, the other `completed` → run `completed_with_gaps`; the ICP step stays `completed`.
  - Persona steps respect the cap with the product fan-out (extend the existing cap test: peak concurrency ≤ `onboarding_max_parallel_runs` when 3 personas + 6 products compete).
  - Persona turns start before the product fan-out finishes (record start order).
- [ ] Fleet wiring test: `_SynthesisSeam` maps both calls (a stub launcher).
- [ ] Implement; update the driver docstring's "the synthesis turn" sentence and `README.md`'s step table (add `persona`).
- [ ] Run: `uv run pytest tests/arv2/test_onboarding_driver.py tests/api/test_fleet_wiring.py -q`.
- [ ] Commit: `feat(arv2 o3/o4): persona fan-out per ICP on the driver; seam carries both launcher calls`

---

### Task 5: Docs, checklist, memory

**Files:**
- Modify: `docs/specs/ARV2-ONBOARDING-PLAN.md` (§5 + §6.2: the turn split, the known-ICPs rule, `icp_version` semantics; O4 row in §9 gains a dated note), `platform/api/clue_api/arv2/README.md`
- Create: `_memory/2026-09-08-arv2-onboarding-o4-synthesis-split.md`; pointer in `_memory/README.md`

**Steps:**
- [ ] Run the 7-item checklist in `_memory/2026-09-07-no-old-lane-gate-may-block-new-lane.md` and record the result in the memory note.
- [ ] Memory note: what changed, the identities, the input rules, the surface, the digest, the migration id, the owed live proof.
- [ ] Commit: `docs(arv2 o4): synthesis split — plan §5/§6 notes, README, memory`

---

### Task 6: Live proof (founder-triggered; ~$3 per run)

Not a subagent task. After merge to `integration/design-improvement`, upgrade `clue_semarang`, restart the semarang fleet worker (reproduce the `.env`, never `pkill`), trigger one Insight Health onboarding from the Knowledge page, and record under `.context/arv2-onboarding-o4-split-acceptance/`:

- [ ] `synthesis` step `completed` and the three `audience/icp-*` rows present within ~6 min of `requested_at`, while `persona` steps are `running` (poll `onboarding/current` + the DB).
- [ ] Three `persona` steps with overlapping `started_at`/`finished_at`; run `completed`.
- [ ] No new `audience/icp-*` path (the three keys on file reused); each ICP at version 3.
- [ ] Each persona front matter `icp_version` equals its ICP row's version.
- [ ] `tool_invocation` rows for `exa_search_evidence@1` in the window: 15, none under the ICP turn's execution id.
- [ ] Per-step cost and wall clock in the memory note.
