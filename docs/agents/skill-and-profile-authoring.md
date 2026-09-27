# Agent prompts, skills, and profiles

This is the maintainer guide for changing what the platform Head-of-ABM and its specialist
subagents know how to do. The production source is the reviewed, versioned folder catalog:

```text
platform/agents/catalog/
  prompts/<prompt-name>/<version>/SYSTEM.md
  skills/<skill-name>/<version>/SKILL.md
  profiles/<profile-name>/<version>/profile.yaml
```

Runtime workspace copies under `.deepagent/` are immutable materializations, not source files.
Never edit a runtime workspace to change agent behavior.

## Research-field scope amendment — 2026-09-16

The workspace-local agent-proposal change has a
[detailed plan](../superpowers/plans/2026-09-16-workspace-agent-proposed-fields.md) and
[prepared operating instructions](research-field-scope.md). Its release must update the actual
Head-of-ABM manual, both ARV2 research bundles and platform-only snapshot generation. A repository
prose edit alone does not reach the running agent.

Current code selects Head of ABM **v58**, manual **v5**, and ARV2 account/person bundles **v1**.
The table below describes the original C6 baseline, not the current selector inventory. Inspect
`C6_ACTIVE_PROFILE_VERSIONS`, the selected profile and `arv2/account_research_catalog.py` before
choosing new versions. The scope amendment is not active; publish replacement guidance alongside
compatible backend/data changes.

## Original C6 resource map (historical baseline)

| Role | System prompt | Progressively disclosed skills | Active profile |
|---|---|---|---|
| Head of ABM | `prompts/head-of-abm/v3/SYSTEM.md` | `skills/stage0-interview/v5/SKILL.md` | `profiles/head-of-abm/v7/profile.yaml` |
| Research specialist | `prompts/research-specialist/v2/SYSTEM.md` | `skills/research-task/v1/SKILL.md` | `profiles/research-specialist/v4/profile.yaml` |
| Content drafter | `prompts/content-drafter/v2/SYSTEM.md` | `skills/content-exemplar/v1/SKILL.md` | `profiles/content-drafter/v4/profile.yaml` |
| Reviewer | `prompts/reviewer/v2/SYSTEM.md` | `skills/artifact-review/v1/SKILL.md` | `profiles/reviewer/v4/profile.yaml` |
| Account research worker | `prompts/account-research/v3/SYSTEM.md` | `skills/account-gap-research/v3/SKILL.md` | `profiles/account-research/v5/profile.yaml` |

The active version selector is
`platform/api/clue_api/agent_registry_wiring.py::C6_ACTIVE_PROFILE_VERSIONS`. Historical versions
remain loadable evidence and must not be deleted or modified.

## What each resource controls

`SYSTEM.md` is the role's always-on constitution-facing behavior: identity, authority boundaries,
non-negotiable prohibitions, durable-output rules, and honest finalization. It should be compact
and stable.

`SKILL.md` is task-specific operating guidance. The model sees only the skill summary and immutable
path at first. It opens the body when the current task needs it. Skill frontmatter pins admitted
roles, readiness requirement ids, and exact governed tools. A skill cannot grant a tool absent
from its profile.

`profile.yaml` is executable policy, not prose. It pins:

- exact prompt and skill versions plus SHA-256 digests;
- exact tool version and input/output schema digests;
- per-role model, output-token, call-timeout, retry, temperature, turn-time, and round limits;
- isolated workspace quotas, extensions, and readable/writable prefixes;
- delegation roles, child tool grants, depth/count limits, and plan-node ceiling.

The loader rejects unknown fields, mutable aliases, duplicate addresses, symlinks, executable or
hard-linked files, mismatched folder identities, invalid UTF-8, changed hashes, unavailable tools,
human steering tools, replay-unsafe tools, and child authority wider than the parent grant.

## Skill references in prompts and other skills

Use `{{skills.claim_ready_account_dossier.path}}` wherever instructions need the path of
the profile's `claim-ready-account-dossier` skill. The key is the skill name with hyphens
replaced by underscores; the hyphenated spelling is also accepted. The renderer substitutes
the absolute virtual path, for example `/.deepagent/skills/claim-ready-account-dossier/v2/SKILL.md`.
This works in system-prompt bodies and in skills that refer to other skills. It does not
evaluate expressions, expand arbitrary variables, or fetch files from the network.

The effective profile selects the versions. Rendering uses exactly the same skill set as
workspace materialization and disclosure, after tool/authority filtering. A missing, withheld,
ambiguous or malformed skill reference fails during profile resolution, before model calls.
Do not use a placeholder for a skill the profile does not grant. Other placeholders such as
`{{account_name}}` remain untouched.

Catalog files and saved resource snapshots retain the original template bytes and hashes.
Model prompts, `open_skill` reads and read-only workspace files receive the rendered text.
When substitution occurs, `.deepagent/rendered-resources.json` records each affected path's
source and rendered SHA-256 plus renderer version `skill-paths-v1`. The existing manifest
continues to identify the original resources. Cold-resume verification derives and checks the
rendered bytes from the pinned snapshot, and repairs altered workspace copies.

Promote a new skill by selecting its exact version/hash in a new approved profile and launch
revision. Adding a newer folder alone has no effect. Existing runs retain their original pins;
resources without placeholders retain byte-for-byte materialization. Revision 21 of quality
account/person research uses this mechanism; older revisions and other agent profiles keep
their existing instructions until explicitly migrated.

## How specialist delegation transfers context

The Head uses the governed `delegate_specialist` tool. The framework's built-in `task` tool is
always removed because it would bypass the C5 plan/delegation journal.

The tool freezes one `SpecialistTaskEnvelope`:

- `goal` and `instructions`;
- bounded small source material copied verbatim;
- canonical parent files copied byte-for-byte to content-addressed artifacts, then materialized
  read-only below the child's `context/delegated/` prefix;
- domain state as typed object refs;
- one fixed role output path.

Every child gets a distinct execution id, turn, checkpoint namespace, isolated virtual workspace,
profile/model instance, budget, and seven-layer context bundle. Conversation history is explicitly
empty. Research writes `outputs/research-strategy.md`, the drafter writes
`outputs/content-exemplar.md`, and the reviewer writes `outputs/review-verdict.md`. A completed
return is rejected until that non-empty file and the finalization envelope are durable. Children
return artifact/domain refs only. Human gate refs and `awaiting_input`/`blocked` status propagate
unchanged to the parent.

## Safe change workflow

Published resource bytes are immutable. To change behavior:

1. Copy the current resource folder to the next version; never edit the existing version.
2. Change both the folder name and frontmatter `version`.
3. Keep prompts and skills declarative text only. Source/executable extensions are forbidden.
4. Hash the complete file bytes:

   ```bash
   shasum -a 256 platform/agents/catalog/prompts/<name>/<version>/SYSTEM.md
   shasum -a 256 platform/agents/catalog/skills/<name>/<version>/SKILL.md
   ```

5. Create the next profile version and paste those exact digests into its prompt/skill pins.
6. If a tool changed, obtain the live descriptor's version and both schema digests from
   `build_toolbelt(...)`; do not copy a guessed schema or grant a tool by name alone.
7. Update `C6_ACTIVE_PROFILE_VERSIONS` only after the new resources and tests are reviewed.
8. Update the expected aggregate resource-manifest digests in
   `tests/api/test_agent_registry_wiring.py`. The aggregate is computed from exact resource and
   tool refs; it is deliberately sensitive to any policy change.
9. Add or update qualitative fixtures for the changed behavior. Prompts are policy-bearing code.
10. Run:

   ```bash
   pytest -q tests/agents tests/api/test_agent_registry_wiring.py \
     tests/api/test_agent_runtime_wiring_db.py
   make check
   make db-smoke
   ```

If a tool pin is rejected, fix the profile or the reviewed authority map; do not weaken the
loader. If a skill disappears from effective disclosure, one of its required tool pins was
removed by the profile, engine ceiling, or delegated parent grant.

## Relevant implementation files

- Strict folder schemas/loaders: `platform/agents/clue_agents/catalog.py`
- Profile resolution, resource maps, skill disclosure: `platform/agents/clue_agents/registry.py`
- Immutable materialization: `platform/agents/clue_agents/resources.py`
- Exact model tool filtering: `platform/agents/clue_agents/runtime.py`
- Active versions and tool authority: `platform/api/clue_api/agent_registry_wiring.py`
- Governed tool and delegation wrappers: `platform/api/clue_api/agent_runtime_wiring.py`
- Durable parent/child delegation lifecycle: `platform/api/clue_api/agent_execution_wiring.py`
- Fresh-wake specialist construction: `platform/api/clue_api/specialist_wiring.py`
- Per-account research-agent construction and fleet substitution:
  `platform/api/clue_api/account_research_wiring.py`

Future prompt-hub support must implement the existing catalog protocols and return the same exact,
immutable resource descriptors. It must not change consumers or make a mutable remote alias the
production identity.
