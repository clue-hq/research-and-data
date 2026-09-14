# Paged and spilled reads Implementation Plan (Lane 1, plan 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every read tool the Head of ABM has pages with `offset`/`limit`/`next_offset`; a governed result that would exceed the receipt bound is spilled into the thread's `reads/` folder and the receipt points at it; a general claims query and a gallery-artifact read join the three ARV2 reads; the skill says how to read to the end.

**Architecture:** Pagination lives in `clue_api.arv2.read_tools` (the hotfix's byte budget stays as the page's ceiling). Spilling lives in the governed execution adapter (`agent_execution_wiring.C5AgentExecutionAdapter._execute_tool`), which receives a `SpillSink` bound to the thread's lease backend: when the canonical references exceed the budget it writes them to `reads/<operation_id>.json` and records a reference-only receipt. `read_claims@1` reuses the display gate; `read_artifact@1` reads a design document through the same DAL the artifact route uses. Skill v31 / profile v54 / recipe v28 grant the two new tools.

**Tech Stack:** Python 3.12, pydantic, SQLAlchemy async, the toolbelt, pytest.

**Spec:** `docs/superpowers/specs/2026-09-13-agent-workspace-reorganization-design.md` — W4 (read side), W9, §4.5. Builds on `2026-09-13-read-tools-hotfix.md` (byte budget, `offset` on the claims read, W10).

## Global Constraints

- **Receipt bound unchanged** (16 KiB); `READ_REFERENCES_BUDGET_BYTES = 12 * 1024` is the page ceiling and the spill threshold.
- **Spill file contract:** `reads/<operation_id>.json`, UTF-8 JSON, the full canonical references; the receipt's `reference_values` becomes `{"spilled_to": "<path>", "count": <int>, "summary": "<≤300 chars>", "tool": "<address>"}`. The file counts toward the thread quota and persists in `reads/` until the folder's size cap trims the oldest. The model reads it with `read_file` (offset/limit in lines).
- **Display gate:** `read_claims@1` holds back exactly what `read_account_research`'s claims do, and counts it.
- **Pagination contract, all reads:** `offset: int = Field(default=0, ge=0)`, `limit: int = Field(default=<per tool>, ge=1, le=<max>)`; output `offset`, `next_offset: int | None`, `total: int` where a total is one query away, else `truncated: bool`.
- **Versions (after plan 3 landed at v32/v55/27 on 2026-09-14):** skill `stage0-interview@v33`, profile `head-of-abm@v56`, recipe `recipe0-stage0-v28` (v27 plus `read_claims@1`, `read_artifact@1`), `CONVERSATION_RECIPE_VERSION = 28`; the operating manual re-mints at `manual-*@v3` because the grant moves (`MANUAL_VERSION = "v3"`, `PROFILE_VERSION = "v56"`, the `manual-tools`/`-errors`/`-limits` chapters re-rendered, hand-written chapters copied with `/v3/` links); context policies `project-conversation-context-v3` and `stage0-trial-context-v3` (Task 0); digests re-measured; recipe promoted by the workers' boot seeding.
- **Context budgets are observability, never a gate (founder ruling 2026-09-14, Task 0):** no layer budget may raise or drop; the only ceiling is the provider's context window.
- **Tests, commits:** as in the previous plans.

---

### Task 0: Context budgets become observability — no layer budget may fail or trim a turn

**Founder ruling (2026-09-14, plan 3 debrief):** "We should not put any hard budget limit on the LLM for anything, like if the L1 budget exceeds the LLM would fail. We should just keep a track of what all things are there." Today `DeterministicAgentContextAssembler._retain` raises `ValueError("required <layer> context exceeds its hard layer budget")` when a *required* candidate does not fit (this killed the first v54 turn at ~273 bytes of headroom) and silently **excludes** optional candidates that do not fit (`exclusion_reason_code="layer_budget_exceeded"`, and for L6 the *oldest* messages are the ones dropped). Both become tracking only.

**Files:**
- Modify: `platform/agents/clue_agents/context.py` (`_retain`, `assemble`), `platform/api/clue_api/agent_turn_fleet_wiring.py` (`project_conversation_context_policy`: docstring + `version="project-conversation-context-v3"`), `platform/api/clue_api/stage0_trial.py` (`version="stage0-trial-context-v3"`)
- Test: `tests/agents/test_context.py` (`test_context_budget_excludes_atomic_items_with_stable_reason` becomes `test_context_budget_records_an_over_budget_layer_and_keeps_every_item`), `tests/agents/test_context_l6_retention.py` (`test_a_long_thread_keeps_its_newest_messages_and_still_reads_in_order` becomes `test_a_long_thread_keeps_every_message_in_order_and_records_its_size`), `tests/agents/test_manual_drift.py` (`test_the_resolved_system_prompt_fits_the_production_identity_budget` becomes `test_the_resolved_system_prompt_size_is_reported_against_the_identity_budget`: it asserts the prompt's byte count is a positive number below the provider window and *prints* its share of L1; `PROMPT_BUDGET_SHARE` and the ceiling assertion go), `tests/agents/test_context_receipt*.py` if any pins `layer_budget_exceeded`
- No migration: `agent_context_layer` already persists `token_budget` and `token_count` per layer, so "over budget" is `token_count > token_budget` on the receipt as it stands.

**Interfaces:**
- `_retain(layer, candidates, budget) -> dict[str, int]` returns a count for **every** candidate; it never raises and never skips. `budget` is kept as a parameter only to report against.
- `assemble` keeps emitting `ContextLayerManifest.token_count` (now the whole layer) and `ContextReceiptRef(disposition="included", token_count=…)` for every candidate; `excluded_refs`/`exclusion_reason_codes` stay in the contracts (older receipts carry them) but budgeting never produces them.
- One structured log per over-budget layer at assembly: `log.warning("agent_turn.context_layer_over_budget", execution_id=…, layer=layer.value, token_count=used, token_budget=budget, policy_version=…)`; nothing else changes shape.
- The policy `version` strings move to `-v3` because the *meaning* of `max_tokens` changed (a reporting line, not a ceiling); a turn assembled under v2 replays against v2's own receipt.

- [ ] **Step 1: Failing tests** — a layer whose candidates total 1,000 tokens under a 400 budget assembles all of them, in canonical order, with every ref `included` and the layer manifest `token_count == 1000`; a required L1 candidate over budget assembles (no `ValueError`); a 40-message L6 thread under a budget that fits 5 keeps all 40 in chronological order and records 40 included refs; the receipt's `budgets` still carry the policy numbers; one warning event per over-budget layer is emitted (capture with the structlog test helper the repo uses).
- [ ] **Step 2: FAIL. Step 3: Implement** (delete the raise and the skip; add the log line; move the two policy versions; rewrite the two policy docstrings so they no longer promise a hard failure — the L1 paragraph in `project_conversation_context_policy` currently says "a required candidate that does not fit raises, it is never silently dropped"). **Step 4: PASS** — `uv run pytest tests/agents/test_context.py tests/agents/test_context_l6_retention.py tests/agents/test_manual_drift.py tests/agents -q -p no:cacheprovider --ignore-glob='*_live.py'`, plus the DB test that pins a production turn's receipt (`tests/api/test_o6_conversation_composition_db.py`) on the lane DB. **Step 5: Commit** — `feat(agent-context): layer budgets are tracked, never enforced — no turn fails or loses context at assembly (founder ruling 2026-09-14)`.

**Open item for the founder (not decided by this task):** with no assembly ceiling, a thread that outgrows the provider's context window fails at the provider with the provider's error. Whether L6 gets a *window-sized* newest-first trim (a fact of the model, not a policy) or the turn is allowed to fail loudly is a separate decision; this task only records the size.

---

### Task 1: Pagination on the discovery read and `limit` on the claims read

**Files:**
- Modify: `platform/api/clue_api/arv2/read_tools.py` (`read_discovery_run` 680–777: `offset`/`limit` over the ordered candidates; `ReadDiscoveryRunInput` replaces `candidate_limit` with `offset`/`limit` (`default 25, le 50`), output adds `offset`, `next_offset`; `ReadAccountResearchInput.limit` (`default 40, le MAX_CLAIMS`); `_account_claims` window = `kept[offset:offset+limit]` before the byte budget), `DbArv2ReadService`, `Arv2ReadService`
- Test: `tests/arv2/test_read_tools_db.py`, `tests/api/test_arv2_read_tools.py`

- [ ] **Step 1: Failing tests** — discovery: seed 60 candidates; page 1 (`limit 25`) has `next_offset 25`; page 3 ends with `next_offset None`; pages partition the ordered list; `candidate_total == 60` on every page. Claims: `limit 5` serves five and `next_offset 5`.
- [ ] **Steps 2–5:** implement, run both files, commit — `feat(arv2): the discovery and claims reads page with offset/limit/next_offset`.

---

### Task 2: `read_claims@1` — the general claims query

**Files:**
- Modify: `platform/api/clue_api/arv2/read_tools.py` (new section), `platform/api/clue_api/toolbelt_wiring.py` (`build_toolbelt` registers it, ungranted), `agent_registry_wiring.py` (`C6_AGENT_TOOL_AUTHORITY["read_claims"] = ()`), composition at `fleet_main`/`projections_main` (the read service is already composed), count bumps in `tests/api/test_toolbelt_wiring.py` `_MATRIX`, `tests/agents/test_tool_authority_audit.py`, `tests/api/test_c8_trial_surface.py`
- Test: `tests/arv2/test_read_tools_db.py`, `tests/api/test_arv2_read_tools.py`

**Interfaces:**

```python
class ReadClaimsInput(ToolInput):
    entity_id: str                                   # account or contact entity id in this workspace
    field_prefix: str | None = Field(default=None, max_length=80)
    tier: int | None = Field(default=None, ge=1, le=4)
    verification_status: Literal["unverified", "verified", "rejected"] | None = None
    since: str | None = None                         # ISO date; collected_at >= since
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=40, ge=1, le=MAX_CLAIMS)

class ReadClaimsOutput(ToolOutput):
    entity_id: str
    entity_type: str                                 # "account" | "contact"
    claims: tuple[AccountClaimView, ...]             # the same view; the name is historical
    excluded: dict[str, int]
    prefixes: dict[str, int]
    offset: int
    next_offset: int | None
    truncated: bool
```

Service: `read_claims(conn, *, workspace_id, entity_id, filters…, settings)`; resolves the entity type by checking `account_entity` then `contact_entity` in the workspace (refuse `entity_not_found`); loads through `claims_for_entities` with `WorkspaceScope`; applies the hotfix's gate and `claim_prefixes`; filters; pages; byte-bounds. `model_description`: "Query the live claims about one account or contact: by field family (field_prefix), source tier, verification status, or collected since a date; paged; the same display gate as the account pages. Use read_account_research for the written overview. Effect-free."

- [ ] **Steps:** failing DB + offline tests (filters, paging, contact entity, gate) → implement → register ungranted → run the matrix/audit/trial tests → commit — `feat(arv2): read_claims@1 — a paged, gated claims query by entity, family, tier, status and date, registered ungranted`.

---

### Task 3: `read_artifact@1` — one gallery artifact by reference

**Files:**
- Create: `platform/api/clue_api/artifact_read_tools.py`
- Modify: `toolbelt_wiring.py` (register; needs the design DAL the router uses: `get_design_document` from `design_leg_wiring` — the exact import is the one `chat/router.py:1138` (`design_artifact_route`) uses), `agent_registry_wiring.py` (`"read_artifact": ()`), the count tests
- Test: `tests/api/test_artifact_read_tool_db.py` (seed a design document with the fixture the router tests use — `grep -rl design_artifact_route tests`)

**Interfaces:**

```python
class ReadArtifactInput(ToolInput):
    artifact_id: str                                  # the design document id from project/artifacts/index.json
    section: Literal["summary", "content"] = "summary"

class ReadArtifactOutput(ToolOutput):
    artifact_id: str
    kind: str                                         # "web" | "ad"
    title: str
    status: str
    current_version_id: str
    origin_thread_id: str
    updated_at: str
    #: ``content`` only: the document's page JSON as text, capped at READ_REFERENCES_BUDGET_BYTES
    #: (the spill in Task 4 carries the rest when it is larger).
    body_text: str
    body_truncated: bool
```

Preconditions: the document belongs to a leg of a thread of the ambient workspace (the same join `project_design_documents` uses); else `artifact_not_found`. Effect-free, `pin_requirements=("project",)`.

- [ ] **Steps:** failing tests → implement → register ungranted → commit — `feat(design): read_artifact@1 — a gallery artifact's summary or content by id, registered ungranted`.

---

### Task 4: Spilling — the execution adapter writes oversized results to `reads/`

**Files:**
- Modify: `platform/agents/clue_agents/workspace.py` (`AnchoredAgentWorkspaceBackend.write_spill(operation_id: str, data: bytes) -> str` — trusted write under `reads/`, bypasses `writable_prefixes` but not the quota or the atomic install; returns the virtual path), `platform/agents/clue_agents/execution.py` (a named constant `RECEIPT_MAX_BYTES = 16_384` replacing the literal at :149), `platform/api/clue_api/agent_execution_wiring.py:1868-1882` (`_execute_tool`: measure `canonical_result.references` with `receipt_bytes`; if `> SPILL_THRESHOLD_BYTES (12 KiB)` and `self._spill is not None`, write and substitute), constructor `spill: SpillSink | None = None`; `head_of_abm_wiring.py:100` and `account_research_wiring.py:165` (pass `spill=lease.backend` where a lease exists; the onboarding-synthesis site passes none)
- Test: `tests/api/test_agent_execution_wiring.py` (a fake tool returning 20 KiB of references → the receipt's `reference_values` is the spill stub, the file exists in the fake backend, and the journaled artifact still holds the full result), `tests/agents/test_workspace_backend.py` (`write_spill` lands under `reads/`, counts toward quota, refuses a path outside `reads/`)

**Interfaces:**

```python
class SpillSink(Protocol):
    def write_spill(self, operation_id: str, data: bytes) -> str: ...

SPILL_THRESHOLD_BYTES = 12 * 1024

def spill_stub(*, address: str, path: str, references: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """count = the length of the largest list-valued top-level field (or 1); summary = the
    references' ``summary`` field if it is a string, else the first 300 characters of the
    canonical JSON."""
```

The full result is still journaled as the operation's result artifact (`result_ref` on the receipt is unchanged), so replay and the inspector keep the whole payload; only the receipt's inline values shrink.

- [ ] **Steps:** failing tests → implement → run `tests/api/test_agent_execution_wiring.py tests/agents/test_workspace_backend.py tests/agents/test_governed_tool_feedback.py` → commit — `feat(agent-execution): a governed result over the receipt budget is spilled to reads/<operation>.json and the receipt points at it`.

---

### Task 5: Skill v31, profile v54, recipe v28 — grant the two reads, teach paging and spills

**Files:**
- Create: skill `stage0-interview/v31`, profile `head-of-abm/v54`, `recipe0-stage0-v28.json`
- Modify: registry/recipe constants and tests as in plan 3's Task 5; `chat-tool-presentation.ts` labels: `read_claims: "Query the claims"`, `read_artifact: "Open an artifact"`

Skill v31 §7c (founder-reviewed with this plan; replaces the hotfix's §7c):

```markdown
## 7c. Read before you speak about accounts, claims and artifacts

- **How many accounts, which are researched:** `read_project_accounts`.
- **What research found about one account:** `read_account_research`, `section: "overview"` first; a researched account whose overview is not written yet answers `overview_not_written` — then `section: "claims"`.
- **A specific question about claims** (one family, one tier, only verified, only since a date, or a contact's claims): `read_claims`.
- **What discovery found:** `read_discovery_run`.
- **What a gallery artifact is or says:** `read_artifact` with an id from `project/artifacts/index.json`; `section: "content"` only when you need its text.

Every read comes in pages. A page ends with `next_offset`; when it is not null, read again with `offset: next_offset` before you summarize or count. Narrow with `field_prefix` using a family from `prefixes`; never invent one. When a result was too large for its receipt, the receipt says `spilled_to`: read that file with `read_file`, in chunks with `offset` and `limit`, and note what you found in `scratch/notes.md` so you do not read it twice. Read accounts one at a time, in the order the human named them. A read costs nothing and is never a launch. Quote a fact only with a claim behind it; say when a field is empty. Never state a fact from memory of an earlier thread.
```

- [ ] **Steps:** create, pin, measure, promote recipe v28 on the lane DB, run the grant tests, commit — `feat(head-of-abm): v54/v31/recipe v28 — read_claims and read_artifact granted; §7c reads pages and spills to the end`.

---

### Task 6: Live proof and close-out

- Stack restart; in a new thread: the Arthur Direct Care question completes across pages; "what verified claims do we have about Woodlands since September?" → `read_claims`; "what is in the gallery?" → `read_artifact` summary; a deliberately huge claims page (limit 120, no prefix) shows a `spilled_to` receipt and the agent reads the file.
- SQL: `execution_node` tool names for the four reads; `reads/` file present in the turn directory on disk.
- Memory note + README row; commit.

---

## Self-review

- **Spec coverage:** W9 pagination (Task 1), `read_claims` (Task 2), W4 read side (Task 3), spill contract (Task 4), skill (Task 5), proof (Task 6). W10 shipped in the hotfix. ✔
- **Founder ruling 2026-09-14 (no hard context budgets):** Task 0; the policy version bump is what keeps v2 receipts replay-exact. ✔
- **Placeholders:** the design DAL import and the router-test fixture are named by their call sites, not invented. ✔
- **Type consistency:** `READ_REFERENCES_BUDGET_BYTES`/`receipt_bytes` from the hotfix; `SpillSink.write_spill` matches `AnchoredAgentWorkspaceBackend.write_spill`; `AccountClaimView` reused by `read_claims`. ✔
