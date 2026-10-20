# Versioned project root and document skills Implementation Plan (Lane 1, plan 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Head of ABM writes the project's documents with deepagents' own `write_file` and `edit_file` under `project/`: an ICP proposal, a persona document, the plan. Each write lands a new immutable document version through the existing writers, the library file is refreshed in place, the plan card appears from the rows the turn wrote, and the three bespoke tools retire. Three short document skills say what each document contains.

**Architecture:** The `project` mount becomes a *versioned root* (`mode="versioned"`): reads serve the library file; a write resolves the document kind from the folder, takes the expected version from the mounted index, and runs the matching async writer on a dedicated bridge loop with its own DB engine, then re-materializes the library (plan 2's `ensure_project_library`) and updates the mount's version map. Successful writes are recorded on the lease; the turn's finalization merges them into `domain_refs` so the plan card and inspector keep reading receipts/envelopes, not files. Skills carry the document rules; the profile grants the skills and ungrants the tools; the recipe drops their addresses.

**Tech Stack:** Python 3.12, deepagents 0.6.12 backend protocol, asyncio bridge thread, SQLAlchemy async engine (second engine on the bridge loop), pydantic, pytest.

**Spec:** `docs/superpowers/specs/archive/2026-09-13-agent-workspace-reorganization-design.md` — W6, W7, W8, §4.4, §4.6, §4.7.

## Global Constraints

- **Kinds by folder (ruling P3-a, amends spec §4.1/§4.4's `personas/` folder to the platform's existing convention):**
  `audience/icp-<key>.md` → `icp-definition` (writer `icp_authoring.author_icp_document`, scope `project`);
  `audience/persona-<key>.md` → `audience-persona` (new writer `project_documents.write_project_persona`);
  `plan.md` → `project-plan` (writer `project_documents.write_project_plan`);
  `status.md`, `decisions.md`, `index.json`, `artifacts/**` → refused `compiled_file_read_only`;
  anything else → refused `unknown_project_path`.
- **Expected version is never a model argument.** The versioned mount carries `versions: dict[path, int]` loaded from the mounted `index.json`; a write passes that as `expected_version` (`None` when absent). After a successful write the map is updated, so a second write in the same turn is consistent.
- **Pins stay human (W7):** an ICP write stores a `proposed` version; the skill then opens `open_icp_confirmation_gate@2`. Nothing in this plan confirms or pins.
- **Errors are the write tool's error string**, worded for the model, prefixed with the stable code: `revision_conflict: plan.md is at version 3, you read version 2 — read it again`; `icp_key_taken_by_brand: …`; `compiled_file_read_only: status.md is compiled …`.
- **Retirement:** `author_icp_document@1`, `write_project_document@1`, `request_persona_synthesis@1` stay registered (replay of historical receipts) but leave `C6_AGENT_TOOL_AUTHORITY` grants, the profile, the skill and the recipe. Their tests keep passing against the registry; the trial-surface and authority-audit counts move.
- **Versions:** skill `stage0-interview@v30`; new skills `icp-authoring@v1`, `persona-authoring@v1`, `plan-authoring@v1`; profile `head-of-abm@v53` (`writable_prefixes` adds `project`); recipe `recipe0-stage0-v27` = v26 minus the three addresses; `CONVERSATION_RECIPE_VERSION = 27`; recipe promoted on the lane DB.
- **Skill text is founder-reviewed:** the three skills' bodies below are the text to present.
- **Tests:** as in plans 1–2. **Commits:** local only, no push, no AI attribution.

---

### Task 1: The bridge — running an async writer from the sync backend

**Files:**
- Create: `platform/agents/clue_agents/bridge.py`
- Test: `tests/agents/test_bridge.py`

**Interfaces:**

```python
class AsyncBridge:
    """One background event loop per process for sync callers that must await.

    deepagents calls the backend synchronously; the document writers are async and need a DB
    connection bound to *some* loop. This loop is that loop: it owns its own SQLAlchemy async
    engine (built lazily from ``CLUE_DATABASE_URL``), so it never touches the worker's main loop
    or its pool."""

    def __init__(self, *, name: str = "clue-agent-bridge") -> None: ...
    def run(self, coro: Coroutine[Any, Any, T], *, timeout_s: float = 30.0) -> T:
        """Submit and block; a timeout cancels the coroutine and raises BridgeTimeout."""
    def close(self) -> None: ...

_bridge: AsyncBridge | None = None
def process_bridge() -> AsyncBridge: ...   # lazily created singleton, closed atexit
```

- [ ] **Step 1: Failing tests** — `run` returns the coroutine's value from a foreign thread; two concurrent `run` calls from two threads both complete; a coroutine that sleeps past `timeout_s` raises `BridgeTimeout` and the loop stays usable; `run` called *from* the bridge's own thread raises `RuntimeError("bridge re-entered")`.
- [ ] **Step 2: FAIL. Step 3: Implement** with `threading.Thread(daemon=True)` + `asyncio.new_event_loop()` + `run_coroutine_threadsafe`. **Step 4: PASS. Step 5: Commit** — `feat(agent-workspace): AsyncBridge — a process-local loop for sync backends that must await`.

---

### Task 2: The versioned mount in the backend

**Files:**
- Modify: `platform/agents/clue_agents/workspace.py` (`MountMode` adds `"versioned"`; `WorkspaceMount` gains `writer: VersionedRootWriter | None` and `versions: dict[str, int]`; `write_text_sync`/`edit_text_sync` route; the deepagents `write`/`edit` facade)
- Create: `platform/agents/clue_agents/versioned_root.py` (the protocol and outcome types)
- Test: `tests/agents/test_workspace_backend.py`

**Interfaces:**

```python
# clue_agents/versioned_root.py
@dataclass(frozen=True, slots=True)
class VersionedWriteOutcome:
    path: str                 # virtual path under the mount, e.g. "plan.md"
    version: int
    document_id: UUID
    kind: str
    status: str               # "proposed" | "ready"
    replayed: bool

class VersionedWriteRefused(Exception):
    def __init__(self, code: str, message: str) -> None: ...

class VersionedRootWriter(Protocol):
    def write(self, *, path: str, content: str, expected_version: int | None) -> VersionedWriteOutcome:
        """Sync (the backend is sync); implementations bridge to async. Raises VersionedWriteRefused."""
    def refresh(self) -> dict[str, int]:
        """Re-materialize the library and return the new path→version map."""
```

Backend behaviour for a `versioned` mount:
- `read_text_sync`/`ls`/`glob`/`grep`: as a read-only mount.
- `write_text_sync(path, content)`: `writer.write(path=rel, content=content, expected_version=mount.versions.get(rel))`; on success `mount.versions = writer.refresh()`, then re-open the mount fd (`LibraryTree.open_fd()` on the new tree — the factory hands the backend a `reopen: Callable[[], int]` per versioned mount) and return the entry; on `VersionedWriteRefused` raise `WorkspaceConflict(f"{code}: {message}")`; append the outcome to `self.written_documents`.
- `edit_text_sync(path, old, new)`: read the current library bytes, apply the single-occurrence replacement exactly as today's `edit_text_sync` does, then `write_text_sync` with the result.
- The deepagents facade maps `WorkspaceConflict` to `WriteResult(error=f"conflict: {exc}")` already; the code prefix inside makes it model-readable.
- `materialize_bytes` into a versioned mount stays refused.

- [ ] **Step 1: Failing tests** — with a `_RecordingWriter` (returns outcomes, refuses `revision_conflict` when asked): a write under `project/plan.md` calls the writer with `expected_version` from the mount's map and updates the map from `refresh()`; an edit reads-then-writes with a single occurrence; a refusal surfaces as `WriteResult(error="conflict: revision_conflict: …")`; `written_documents` lists the outcome; `ls("project")` after the write shows the refreshed tree (the recording writer's `refresh` swaps a new `LibraryTree`).
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: PASS** (whole backend file). **Step 5: Commit** — `feat(agent-workspace): a versioned mount — write_file/edit_file under project/ go through a VersionedRootWriter and re-read the refreshed library`.

---

### Task 3: The project writer — kinds by folder, over the existing document writers

**Files:**
- Create: `platform/api/clue_api/project_root_writer.py`
- Modify: `platform/api/clue_api/arv2/project_documents.py` (new `write_project_persona`; `ProjectPlanWrite` reused), `platform/api/clue_api/arv2/icp_authoring.py` (no change; called with scope `project`)
- Test: `tests/api/test_project_root_writer_db.py`

**Interfaces:**

```python
# clue_api/project_root_writer.py
_ICP = re.compile(r"^audience/icp-([a-z0-9-]+)\.md$")
_PERSONA = re.compile(r"^audience/persona-([a-z0-9-]+)\.md$")
_COMPILED = {"status.md", "decisions.md", "index.json"}

@dataclass(frozen=True, slots=True)
class ProjectRootWriter:                       # implements VersionedRootWriter
    bridge: AsyncBridge
    storage: StorageBackend
    artifacts: DurableAgentArtifactStore
    workspaces: AgentWorkspaceFactory
    workspace_id: str
    brand_id: str
    project_id: str
    turn_id: UUID
    user_id: str

    def write(self, *, path, content, expected_version) -> VersionedWriteOutcome:
        if path in _COMPILED or path.startswith("artifacts/"):
            raise VersionedWriteRefused("compiled_file_read_only", f"{path} is compiled from the project's rows; it cannot be written")
        if m := _ICP.match(path):      return self.bridge.run(self._write_icp(m.group(1), content))
        if m := _PERSONA.match(path):  return self.bridge.run(self._write_persona(m.group(1), content, expected_version))
        if path == "plan.md":          return self.bridge.run(self._write_plan(content, expected_version))
        raise VersionedWriteRefused("unknown_project_path", "write an ICP at audience/icp-<key>.md, personas at audience/persona-<key>.md, or the plan at plan.md")

    def refresh(self) -> dict[str, int]:
        return self.bridge.run(self._refresh())
```

`_write_icp`: `IcpAuthoringRequest(workspace_id, brand_id, project_id, turn_id, user_id, icp_key=key, document_text=content, scope="project", derived_from_icp_key=<front matter `derived_from` if present else None>)` → `author_icp_document`; map `IcpAuthoringRefused(code, message)` → `VersionedWriteRefused`. The expected-version rule for an ICP is the writer's own (a new version under the key; the race is the unique index).
`_write_persona`: new `write_project_persona(conn, storage, ProjectPersonaWrite(workspace_id, project_id, turn_id, user_id, icp_key, body, expected_version))` — mirrors `write_project_plan` (replay key turn+expected_version+body sha; `_lock_project` first; `version:` in front matter; kind `audience-persona`, path `audience/persona-<key>.md`, status `ready`); refuses `icp_not_pinned` when the project's pinned ICP key differs from `<key>` (personas follow the pinned ICP, W8).
`_write_plan`: `ProjectPlanWrite(...)` → `write_project_plan`; `ProjectDocumentRefused` → `VersionedWriteRefused` (`project_document_revision_conflict` → `revision_conflict` with the message pattern in the constraints).
`_refresh`: `ensure_project_library(...)` → `{entry.path (minus "project/"): entry.version for entry in snapshot.index.files if entry.version is not None}`.

Every coroutine opens its own transaction on the bridge engine: `async with bridge_transaction() as conn:` (a `transaction`-shaped factory built on the bridge's engine in `bridge.py`).

- [ ] **Step 1: Failing DB tests** — plan write v1 then v2 with expected 1 (ok) then expected 1 again (`revision_conflict`); persona write for the pinned key (ok) and for another key (`icp_not_pinned`); ICP write lands `proposed` under the project scope with `derived_from` honoured; `status.md` refused; `artifacts/x.json` refused; after each successful write `refresh()` returns the new version and the library file bytes equal the stored version's body.
- [ ] **Steps 2–5:** implement, run, commit — `feat(project-root): the project's versioned root writer — ICP, persona and plan writes by folder over the existing document writers`.

---

### Task 4: Wire the writer into the turn; plan card from the turn's writes

**Files:**
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py` (build `ProjectRootWriter` per turn; `MountRequest(project_library=True, project_writer=writer)`), `platform/agents/clue_agents/workspace.py` (`MountRequest.project_writer`), `platform/api/clue_api/agent_runtime_wiring.py` (finalize: merge `lease.backend.written_documents` into the envelope's `domain_refs` as `DomainObjectRef(object_type="project_document", object_id=str(document_id), version=version)`, deduped), `platform/api/clue_api/conversation_turns.py:472-487` (unchanged; it already renders `project_document` refs as the plan card — extend: an `icp-definition` outcome renders title "ICP", a persona "Personas", both with `v<n>`)
- Test: `tests/api/test_o6_conversation_composition_db.py` (a fake model that calls `write_file("project/plan.md", …)` then finalizes; assert a `brand_knowledge_document` row at `project/plan.md` v1 for the project and a `plan` part with title "Plan" and `v1` in the stream), `tests/api/test_lane_d5_gate_read_and_rich_parts_db.py` (titles)

- [ ] **Steps:** failing test → implement → run → commit — `feat(agent-turn): the versioned project root is mounted per turn; documents the turn wrote surface as plan cards from the rows`.

---

### Task 5: The three document skills, skill v30, profile v53, recipe v27

**Files:**
- Create: `platform/agents/catalog/skills/icp-authoring/v1/SKILL.md`, `persona-authoring/v1/SKILL.md`, `plan-authoring/v1/SKILL.md`, `stage0-interview/v30/SKILL.md` (copy of v29 with §5b, §5c, §6b replaced by one-paragraph pointers and the tool list dropping the three tools), `profiles/head-of-abm/v53/profile.yaml` (skills: stage0-interview v30 + the three; tools: minus the three; `writable_prefixes: ["scratch", "outputs", "project"]`), `platform/execution/recipes/recipe0-stage0-v27.json`
- Modify: `agent_registry_wiring.py` (`C6_AGENT_TOOL_AUTHORITY` three entries → `()`; profile pin v53), `recipe_contracts.py` (`RECIPE_0_TOOL_ADDRESSES` minus three), `recipe_wiring.py` (`SYSTEM_RECIPE_FILENAMES` + v27), `conversation_turns.py` (`CONVERSATION_RECIPE_VERSION = 27`), `stage0_recipe.py` pin branch, the catalog/registry/recipe/authority/trial-surface tests, `apps/frontend/.../chat-tool-presentation.ts` (labels stay for history)

Skill front matter for each new skill: `schema_version: "1"`, `kind: skill`, `name`, `version: v1`, `summary` (≤512), `roles: [head_of_abm]`, `readiness_requirements: []`, `tools: []`, `framework: deepagents`, `framework_version: ">=0.6,<0.7"`.

**`icp-authoring@v1` body (founder-reviewed with this plan):**

```markdown
# Author an ideal customer profile

You may write an ICP document. You may not confirm one — the human does that through the gate.

Draft only from `brand/knowledge/` (company/overview.md, product/catalog.md, the product files, proof/customer-reviews.md, the existing audience/icp-*.md) and from what the human told this project (project/decisions.md). Every hard gate must trace to one of those; if it cannot, leave it out. Never invent a product id: take `product_ids` from product/catalog.md's front matter.

Write the whole file — front matter and body — in the shape the existing ICP files use: `kind: icp-definition`, `icp_key`, `product_ids`, `hard_gates` (each `{key, rule, test}`), `exclusions`, `persona_map` (only the roles that exist at this account type), `qualifier_fields`; then the body in priority order: who fits and why, the list math, disqualifiers and red flags, the client's own phrasing quoted from the files, the qualification-floor verdict. A project variant of a brand profile needs its own lowercase kebab-case key and `derived_from: <brand key>` in the front matter.

Save it with `write_file` at `project/audience/icp-<key>.md`. The platform stores it as a proposed version and tells you if the key is taken or a product id is unknown; fix exactly what it names and write again. In the same turn, open the ICP confirmation gate on that key and end the turn awaiting the human. Do not write a profile before the founding questions are answered, and never one the human did not ask for.
```

**`persona-authoring@v1` body:** the `audience-persona@v2` skill's text (sections 1–11 and the front-matter format), with these changes: it addresses the Head of ABM; the ICP is `project/audience/icp-<key>.md` for the project's pinned key only; no `exa_search_evidence` (this surface has no web tool): sections 3, 6 and 10 are written from the ICP, the product files and the reviews file, and marked inference where they are; save with `write_file` at `project/audience/persona-<key>.md`; write it only when the human asks, on or after the turn the ICP was confirmed; a redraft is a new write of the same path.

**`plan-authoring@v1` body:** skill v29 §6b's text with the tool call replaced by: "Read `project/plan.md` if it exists. Save with `write_file` at `project/plan.md` (or `edit_file` for a small change). If the platform answers `revision_conflict`, the human edited the plan since you read it: read it again, keep their edits, and write again."

Stage-0 v30: §5b → "To write a profile, open the `icp-authoring` skill."; §5c → "To write personas for a confirmed profile, open the `persona-authoring` skill."; §6b → "To write or update the plan, open the `plan-authoring` skill."; §10 drops the retired tools from what you cannot do / can do.

- [ ] **Steps:** create files; measure the summary lengths; pin; re-measure the manifest digest; run catalog, registry, recipe, authority-audit, trial-surface, toolbelt-wiring tests; promote recipe v27 on the lane DB (`recipe`/`recipe_revision` rows, the `_memory` note of plan 3 has the SQL); commit — `feat(head-of-abm): v53 writes project documents with write_file — icp/persona/plan authoring skills; the three document tools ungranted; recipe v27`.

---

### Task 6: Retire the personas-only onboarding entry point; docs and memory

**Files:**
- Modify: `platform/api/clue_api/persona_request_tools.py` (module docstring: retired from the profile, kept for replay), `platform/api/clue_api/arv2/README.md`, `docs/specs/ARV2-ONBOARDING-PLAN.md` §8 addendum, `_memory/2026-09-13-…` note, the spec §4.1/§4.4 (`personas/` → `audience/persona-<key>.md`, ruling P3-a)
- No code path deleted (standing rule: never delete uncomposed machinery).

- [ ] **Steps:** docs, memory, live proof checklist (a new thread: "write the personas" → `write_file` on `project/audience/persona-<key>.md` → a `ready` row; "write the plan" → `plan.md` v1 and the card; edit the plan through the PUT; "add a step" in a new thread → v3 keeping the edit), commit.

---

## Self-review

- **Spec coverage:** W6 (Tasks 2–4), W7 (icp skill + writer store `proposed`), W8 (persona writer + skill), §4.4 error strings and kind table (Task 3), §4.6 skills (Task 5), §4.7 retirements (Tasks 5–6). ✔
- **Placeholders:** the persona skill body is defined by reference to `audience-persona@v2` plus an explicit change list, so the implementer copies and edits rather than invents; the founder reviews the resulting text before it is committed. ✔
- **Type consistency:** `VersionedWriteOutcome`, `VersionedRootWriter`, `AsyncBridge.run`, `ProjectRootWriter.write/refresh`, `MountRequest.project_writer`, `written_documents` used identically in Tasks 1–4. ✔
