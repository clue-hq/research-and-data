# Operating manual Implementation Plan (Lane 1, plan 2b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Head of ABM has an operating manual it can open chapter by chapter: what a turn is and its limits, its workspace, every tool with every refusal and the right next move, the domain vocabulary (claims, fields, accounts, research, discovery, documents, decisions, gates), its authority, the humans' screens, the sibling agents, every error string, and a glossary. Generated chapters are built from the code and drift-tested; hand-written chapters are founder-reviewed; skills and tool descriptions point at chapters by path.

**Architecture (ruling M-1, simplicity):** a manual chapter **is a catalog skill** named `manual-<chapter>`, with the existing `SkillHeader` front matter, `roles: [head_of_abm]`, `tools: []`. Nothing new in the catalog, the registry, the manifest or the mount table: the profile pins each chapter like any skill, the generated capability map discloses it with its summary and path, and the model opens it with `read_file`. Generated chapters are produced by one builder script that reads the toolbelt descriptors, the enums, a committed field-registry snapshot and settings; a drift test compares the committed chapter to a fresh build. Cross-references are the chapters' materialized paths, which the builder rewrites from chapter names to `.deepagent/skills/manual-<chapter>/<version>/SKILL.md` at build time.

**Tech Stack:** Python 3.12, the agent catalog (`clue_agents.catalog`), the toolbelt descriptors, pytest.

**Spec:** `docs/superpowers/specs/archive/2026-09-13-head-of-abm-operating-manual-design.md` (§3 inventory, §5 generation, §6 cross-references, §7 defects, §9 decisions), evidence in `docs/superpowers/research/2026-09-13-head-of-abm-manual/`.

## Global Constraints

- **Chapters (15):** generated — `manual-tools`, `manual-fields`, `manual-errors`, `manual-limits`; hand-written — `manual-index`, `manual-turn`, `manual-workspace`, `manual-claims`, `manual-accounts-research`, `manual-discovery`, `manual-documents-decisions`, `manual-gates-authority`, `manual-humans-screens`, `manual-siblings`, `manual-glossary`. Each is `platform/agents/catalog/skills/manual-<chapter>/v1/SKILL.md`.
- **Front matter:** `schema_version "1"`, `kind: skill`, `name: manual-<chapter>`, `version: v1`, `summary` ≤ 512 chars beginning "Manual: …", `roles: [head_of_abm]`, `readiness_requirements: []`, `tools: []`, `framework: deepagents`, `framework_version: ">=0.6,<0.7"`.
- **Generated chapters are never hand-edited.** `make manual` (a Makefile target running the builder) regenerates them; the drift test fails when a committed chapter differs from a fresh build or when the builder's inputs moved.
- **Hand-written chapters are founder-reviewed before commit** (standing rule). Each cites its source section in the research docs in an HTML comment at the top, so the reviewer can check it.
- **Honest enforcement:** every rule in `manual-gates-authority` and `manual-turn` carries one of two markers, `(enforced)` or `(asked of you)`, per the research doc D §A/§B.
- **The five founder decisions** (manual spec §9) are recorded as rulings in this plan's ledger before Task 3 starts, and Task 3's chapters state the answers. The plan does not start without them.
- **Paths:** the manual lands after plan 2, so chapters cite `brand/…`, `project/…`, `scratch/`, `reads/`, `inputs/`, `outputs/` and the versioned root of plan 3 as "arrives with the next profile" where plan 3 has not yet run.
- **Versions:** skill `stage0-interview@v30` (path references), profile `head-of-abm@v53` (pins the 15 chapters), no recipe change, no tool address change. Tool `model_description` strings gain a trailing "Manual: <path>" for the tools the manual covers; that moves no digest (descriptions are not in the schema digest).
- **Tests, commits:** as in the other lane-1 plans.

---

### Task 1: The builder and the generated chapters

**Files:**
- Create: `platform/agents/catalog/manual/__init__.py`, `platform/agents/catalog/manual/build.py`, `platform/agents/catalog/manual/fields_snapshot.py`, `platform/agents/catalog/manual/fields.json` (committed snapshot), `platform/agents/catalog/manual/tool_notes.yaml` (hand-written "next move" per refusal code; founder-reviewed), `platform/agents/catalog/skills/manual-{tools,fields,errors,limits}/v1/SKILL.md` (outputs), `Makefile` target `manual`
- Test: `tests/agents/test_manual_builder.py`

**Interfaces:**

```python
# platform/agents/catalog/manual/build.py
@dataclass(frozen=True)
class Chapter:
    name: str            # "tools" → skill "manual-tools"
    summary: str
    body: str            # markdown after the front matter

def build_tools_chapter(toolbelt: ToolRegistry, profile: ProfileDefinition, notes: Mapping[str, Mapping[str, str]]) -> Chapter:
    """One section per granted tool, in profile order: address, effect class, spends?, gate?,
    inputs table (field, type, default, bounds, description from the field's `Field(description=)`
    or the class docstring), refusal codes table (code, meaning, next move from tool_notes.yaml),
    outputs table, 'afterwards' line, 'human sees' label from chat-tool-presentation.ts, skill
    section, and 'See also' links. Then the framework tools and finalize_turn from a fixed template."""

def build_fields_chapter(snapshot: Sequence[Mapping[str, Any]]) -> Chapter:
    """Families in registry order; per key: description, value_type, freshness, reuse_scope,
    gate; a sentence on how to use field_prefix with the family name."""

def build_errors_chapter(...) -> Chapter:   # GovernedToolFailure shape, plan_rejected issue codes (grep AgentPlanIssue codes), file-tool prefixes, finalize refusals, each with the next move from tool_notes.yaml["errors"]
def build_limits_chapter(profile: ProfileDefinition, settings: Settings) -> Chapter:  # rounds, supersteps, wall clock, output tokens, user_message cap, assumptions cap, the two repair budgets, receipt bound, quotas, retention

def render_skill(chapter: Chapter, *, version: str, links: Mapping[str, str]) -> str:
    """Front matter + body with `manual:<name>` link tokens rewritten to materialized paths."""

def main(argv) -> int:   # `python -m clue_agents_catalog.manual.build --write` regenerates all four; `--check` exits 1 on drift
```

`fields_snapshot.py` reads `field_definition` from `CLUE_DATABASE_URL` (SELECT only) and writes `fields.json` sorted by key; it is run by hand when the registry changes and the drift test compares only against the committed snapshot (no DB in CI).

`tool_notes.yaml` shape:

```yaml
read_account_research:
  overview_not_written: "Read section='claims' instead; say the overview is not written yet, not that research failed."
  no_claims_under_prefix: "Pick a family from 'prefixes' in the refusal and read again; never invent a prefix."
errors:
  "quota_exceeded:": "Delete or shorten files in scratch/; do not retry the same write."
```

- [ ] **Step 1: Failing tests** — `build_tools_chapter` over `build_toolbelt(storage=None, gateway=None)` and profile v52 yields one `## ` section per granted tool in profile order and each section contains every refusal code found by `grep -o 'PreconditionFailure("[a-z_]+"' <tool module>`; a refusal code with no note in `tool_notes.yaml` fails the build with the code's name; `render_skill` rewrites `manual:glossary` to `.deepagent/skills/manual-glossary/v1/SKILL.md`; `--check` exits 1 when a committed chapter differs.
- [ ] **Steps 2–5:** implement, run, commit — `feat(catalog): the operating-manual builder — tools, fields, errors and limits chapters generated from the code`.

---

### Task 2: Drift tests

**Files:**
- Create: `tests/agents/test_manual_drift.py`
- Modify: `Makefile` (`make check` runs the drift test through pytest as usual)

- [ ] **Step 1: Write them** — (a) `manual-tools` equals a fresh build byte for byte; (b) every tool granted by the active Head-of-ABM profile has a section and no section names an ungranted tool; (c) every value of the status enums (`arv2/account_research_store.py:67`, `discovery_store.py:85-88`, `verification_status`) appears in the chapter that owns it (`manual-accounts-research`, `manual-discovery`, `manual-claims`); (d) `fields.json` keys equal the `field_key`s in `manual-fields`; (e) every `manual:<name>` link in every chapter resolves to an existing chapter; (f) the profile pins all 15 chapters and the capability map (via `build_agent_profile_registry(...).resolve(HEAD_OF_ABM).generated_resource_map`) lists all 15.
- [ ] **Steps 2–3:** they pass on the committed state; commit — `test(catalog): manual drift guards`.

---

### Task 3: The hand-written chapters

**Files:**
- Create: `platform/agents/catalog/skills/manual-{index,turn,workspace,claims,accounts-research,discovery,documents-decisions,gates-authority,humans-screens,siblings,glossary}/v1/SKILL.md`

**Sources, per chapter** (the writer works from these sections only; every sentence must trace):

| Chapter | Source sections |
| --- | --- |
| index | one line per chapter with its summary; the reading rule ("open the chapter whose summary matches your need; read the glossary first if a word is new") |
| turn | manual spec §3.1; research E §1.2–1.11, "never told" rows 1–3, 6–14, 18–21; D §4 |
| workspace | spec §3.2; B §2–3 (with plan-2 paths), A §8–9 (file-tool truths) |
| claims | spec §3.4 claims; C §1 in full, incl. the display gate predicate for predicate |
| accounts-research | C §3–4; E §3.1–3.2, rows 22–25 |
| discovery | C §5; E §3.3 |
| documents-decisions | C §6–7; the closed `route_key` vocabulary per founder decision 4 |
| gates-authority | D §1–2, §5–6, §A–C, each rule marked `(enforced)` / `(asked of you)`; founder decisions 1 and 3 stated |
| humans-screens | D §3.1–3.7 |
| siblings | E §3.0–3.6 |
| glossary | C closing list (22 terms) + every term the other chapters define; one line each, alphabetical, linking `manual:<chapter>` |

- [ ] **Step 1: Draft** all eleven; each begins with `<!-- sources: research/… §… -->`; summaries ≤ 512 chars; no em dashes (the prompt's own rule).
- [ ] **Step 2: Founder review** — present the eleven bodies in chat; apply the corrections; record the review in the ledger.
- [ ] **Step 3: Run** the drift tests (e, f will fail until Task 4 pins). **Step 4: Commit** — `feat(catalog): the operating manual's hand-written chapters (v1)`.

---

### Task 4: Pin, disclose, cross-reference

**Files:**
- Create: `platform/agents/catalog/profiles/head-of-abm/v53/profile.yaml` (copy of v52; `skills:` adds the 15 `manual-*@v1` pins with measured sha256), `platform/agents/catalog/skills/stage0-interview/v30/SKILL.md` (copy of v29 with path references)
- Modify: `agent_registry_wiring.py` pins and `PROJECT_CONVERSATION_AGENT_PROFILE_ID`; `tests/agents/test_catalog.py` address lists; `tests/api/test_agent_registry_wiring.py` digest; the `model_description` of `read_project_accounts`, `read_account_research`, `read_discovery_run`, `read_arv2_account_research_run`, the three `launch_arv2_*`, the two gate tools, `record_interview_answer` — each gains a final sentence `Manual: .deepagent/skills/manual-tools/v1/SKILL.md#<tool>`; `platform/agents/catalog/prompts/head-of-abm/v9/SYSTEM.md` (copy of v8: the delegation paragraph removed — defect §7-4; one sentence added: "Your operating manual is disclosed below as the `manual-*` skills; open the chapter whose summary matches your need before you guess.")

Skill v30 path references (founder-reviewed): §1 gains "Terms you do not know are in `manual-glossary`; the files and folders are described in `manual-workspace`."; §6 gains "The statement routes and a good `route_key` are in `manual-documents-decisions`."; §7c gains "What the read tools return, their refusals and the right next move are in `manual-tools`; what a claim's tier, status and `excluded` counts mean is in `manual-claims`."; §10 gains "Your authority, rule by rule and whether the platform enforces it, is in `manual-gates-authority`."

- [ ] **Step 1: Measure** the 15 chapter digests (`sha256sum` of each SKILL.md) and pin them; bump the prompt to v9 with its digest.
- [ ] **Step 2: Run** `tests/agents/test_catalog.py tests/api/test_agent_registry_wiring.py tests/agents/test_manual_drift.py tests/api/test_toolbelt_wiring.py` — PASS after re-measuring the manifest digest.
- [ ] **Step 3: Check the map** — print `resolve(HEAD_OF_ABM).generated_resource_map` and confirm the 15 chapters appear under "Progressively disclosed skills" with their summaries and paths, and that the disclosure block stays under 4 KB.
- [ ] **Step 4: Commit** — `feat(head-of-abm): v53 discloses the operating manual (15 chapters); prompt v9 drops the withheld delegation paragraph; skill v30 points at chapters`.

---

### Task 5: Live proof

- Restart the stack on v53. In a new thread ask: "why does the account read say 14 claims were excluded?" → the agent opens `manual-claims` (a `read_file` on its path in the transcript) and answers with `outreach_safe` / `sensitive` in its own words. Ask "what does needs_review mean on Woodlands?" → `manual-accounts-research`, answer "the job failed and is waiting for a human", not "something went wrong". Ask "can you approve the budget?" → `manual-gates-authority`, a correct refusal naming the gate kind it cannot open.
- SQL: `execution_node` shows the `read_file` calls on the manual paths; no governed refusal in the turn.
- Memory note + README row; commit.

---

## Self-review

- **Spec coverage:** §3 inventory → chapters (Tasks 1, 3); §5 generation and drift (Tasks 1–2); §6 cross-references (Task 4); §7 defects 2, 4, 13 (Tasks 3–4); §9 decisions (ledger gate before Task 3). Defects 1, 3, 6, 7, 8, 9, 10, 11, 12 are assigned to other plans in the lane index. ✔
- **Simplicity:** no new catalog kind, no new mount, no new resource-manifest field; a chapter is a skill. ✔
- **Placeholders:** none; the chapter sources are named section by section; the founder decisions are a ledger gate, not a blank. ✔
