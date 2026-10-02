role: arv2-account-research
framework: langchain.agents.create_agent
contract: arv2-r2-account-research-v1

# The arv2-account research profile — executable policy, not prose

This file is the sha-pinned authorization for a job; a change relaunches, never resumes.

**Identity.** `agent-profile:arv2-account:v1`. The prompt and the three skills beside this file are
pinned by sha at composition.

**Model.** `ARV2_ACCOUNT_AGENT_MODEL` / `_EFFORT` from the consolidated agent-model env block (a
model change is an env change, never a profile version). Structuring and media models stay the R1
settings (`CLUE_ARV2_STRUCTURING_MODEL`, `_MEDIA_*`) — the agent never picks them.

**Stop policy — founder ruling 2026-09-08.**

| Limit | Value | Note |
|---|---|---|
| Model rounds | `CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS` | a safety net against a runaway loop, not a budget |
| Tool calls per round | `CLUE_ARV2_ACCOUNT_MAX_TOOL_CALLS_PER_ROUND` | in practice the model issues a handful; the ceiling exists so a wide parallel wave is never refused |
| Total tool calls | **none** | ruled out |
| Consecutive zero-yield rounds | **none** | ruled out |
| Wall-clock | `CLUE_ARV2_ACCOUNT_MAX_RUNTIME_S` | per account job |

The numbers behind those three keys are carried by the `CLUE_ARV2_ACCOUNT_*` env settings, not by
this file: a limit change is an env change, never a profile version. The values this job actually
runs under are given in the runtime context block under `stop_policy`.

Reaching any ceiling pushes the agent to finalize honestly with what it has — never raise, never a
job death (failure law). If a run loops, that run is read and the cause fixed; the profile is not
tightened pre-emptively.

**Effort: full mode only.** The seam-1 directive still carries `effort` and `committee_cap`, but
profile v1 implements one behaviour: the full ladder (the dossier skill). The driver records the
rung it was launched with and runs full regardless; `reduced` and `cheap-pass` behaviours are not
built until a user asks for them. `committee_cap` is honoured as the maximum number of named people
the agent confirms (correct beats many; the PoC settled on 3–6).

**Spend policy.** Money is *recorded*, never enforced (`over_ceiling` is a row, not a stop); the one
enforced ceiling is media seconds (`CLUE_ARV2_MEDIA_SECONDS_CEILING`). A money-truth halt (402 /
credit exhaustion) latches that provider for the run; the agent is told, and continues with the
others.

**Context.** There is no filesystem workspace. The read-only context arrives as sections of the
system prompt and is served again on demand by `read_account_state`: `context/icp.md` (the pinned
ICP artifact, verbatim), `context/persona.md` (the persona document — `titles[]` are the committee
search keys), `context/catalog.md` (the compiled field menu) and
`context/already-established.md`. Output leaves the agent only through the governed tools —
`structure_material`, `write_claims`, `verify_links` and `finalize_research` — never through a file.
