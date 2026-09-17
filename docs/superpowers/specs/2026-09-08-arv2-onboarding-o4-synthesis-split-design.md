# ARV2 Onboarding O4 follow-up — Synthesis split (ICP turn, per-ICP persona turns, inputs up front)

Status: design approved by the founder 2026-09-08 (chat); implementation plan
`docs/superpowers/plans/2026-09-08-arv2-onboarding-o4-synthesis-split.md`.

## 1. Why

Measured on the two successful Insight Health runs (`280cd8f5`, `54246e39`), the synthesis step
took 12 and 14 minutes and behaved like this:

| Phase | Wall clock | What happens |
|---|---|---|
| Reading inputs | ~100 s | seven sequential model calls, each reading one or two files; context grows 16k → 66k tokens |
| Writing ICPs | ~130 s | one call, ~10k output tokens, all three ICP files |
| Personas | 8–10 min | 15 evidence searches in three batches, then two long write calls (134 s, 215 s) |
| Registration | at the end | every output row is inserted only after the whole turn finalizes |

So the ICPs are finished about four minutes into synthesis but reach the Knowledge page
eight to ten minutes later, and the three personas queue behind each other inside one turn.

Two things nobody chose also showed up:

- the launcher feeds the agent **every** servable document, so a re-run's ICP turn read the
  previous run's ICPs *and personas* (about 90 KB of derived text);
- the prompt says "read every file under `product/`" (22 files, ~350 KB), which the agent
  cannot do and does not do; it reads a sample.

## 2. Goal

The ICP documents become visible about six minutes after the onboarding request instead of
about seventeen, and the persona phase runs in parallel per ICP, with **no change to what the
model reasons over or writes**: same model, same skills' rules, same evidence pass per role.

## 3. Rulings (founder, 2026-09-08)

1. On a re-run the ICP turn sees the ICPs already on file; prior personas stay out.
2. The prompt gains a "known ICPs" rule shaped like the lineup's known-products rule:
   reuse a key when the buyer motion is the same; propose a new key only when it is genuinely
   different; never carry a key forward just to fill a slot.
3. Product files stay on disk; the prompt reads the product file for each product a profile
   names rather than every product file.
4. Persona turns run one per ICP, in parallel, as visible `persona` steps.

## 4. Design

### 4.1 Turn topology

One onboarding run makes `1 + N` governed turns under the existing per-brand system project and
the existing `onboarding-synthesis-unit@1` recipe:

- **ICP turn** (one per run). Objective: write `outputs/audience/icp-<key>.md` for two to
  three profiles, then `finalize_turn`. Runs on a declared surface `onboarding-icp` that
  withholds `exa_search_evidence` (the ICP skill already says "from the files and nothing
  else"; a surface makes that governed rather than promised).
- **Persona turn** (one per registered ICP). Objective: write
  `outputs/audience/persona-<key>.md` for the one ICP it is given, with the evidence pass per
  role exactly as today. Full surface.

Identity:

| | execution id | turn id |
|---|---|---|
| ICP | `operation_id_from_key(f"{run_id}:icp", "onboarding-synthesis-unit@1")` | `uuid5(TURN_NAMESPACE, f"{run_id}:icp")` |
| Persona for `k` | `operation_id_from_key(f"{run_id}:persona:{k}", "onboarding-synthesis-unit@1")` | `uuid5(TURN_NAMESPACE, f"{run_id}:persona:{k}")` |

Each turn keeps the launcher's replay short-circuit (`load_committed_outcome`) and its
per-turn `$5` budget envelope. Old-style runs (one turn keyed on the bare run id) are dev data
and are not migrated.

### 4.2 Inputs and opening context

The **core documents** go into the opening context through the L5 focus layer:
`DbCompiledContextCardReader` gains the object type `brand_knowledge_document`, whose card body
is the verified artifact text (`read_verified_artifact`) and whose version is the document
version. The launcher passes exact-version `DomainObjectRef`s as `AgentTurnRequest.focus_refs`.
Every included candidate becomes a message in the opening context, so the model sees the text
on its first call.

The same documents are **also** seeded under `inputs/brand/knowledge/…` so citations keep
their paths. The seed paths and the focus card paths (`context/focus/…`) never collide.

| Turn | Opening context (L5) | Seeded under `inputs/` |
|---|---|---|
| ICP | `company-overview`, `product-catalog`, `customer-reviews` (if any), every servable `icp-definition` | the same, plus every servable `product-research` file |
| Persona for `k` | the registered ICP `k` (exact version), `company-overview`, `product-catalog`, `customer-reviews` | the same, plus only the `product-research` files whose product ids ICP `k` names |

`audience-persona` documents are excluded from both turns' inputs. A `product-research` file
carries its `product_id` in its own front matter (`product_research_document` writes it), so the
persona turn keeps the product files whose `product_id` is in the ICP's `product_ids`; a product
file with no readable `product_id` is kept (over-inclusion is harmless, omission is not).

The L5 budget rises from 8 000 to 262 144 (the counter is `utf8-bytes-v1`; the largest core set
measured is ~110 KB). The synthesis card lists what was put in context and what was seeded.

### 4.3 Prompt, skills, profile

- `prompts/onboarding-synthesis/v2`: one task per turn, named in the user message (`icp` or
  `persona:<key>`). States that the core documents are already in the opening context and are
  also on disk for citation; the product files are on disk; cite file paths as today.
- `skills/icp-synthesis/v2`: adds the known-ICPs rule (ruling 2), replaces "every file under
  product/" with "the product file for each product a profile names" (ruling 3). Format block
  unchanged.
- `skills/audience-persona/v2`: "the ICP you were given" instead of "each ICP file you wrote";
  `icp_version` is the registered document version the user message names, not a literal `1`.
  Sections 1–11, the evidence rule and the format block unchanged. The flat
  `platform/agents/skills/audience-persona-v1/SKILL.md` stays (the recipe pins `v1` of the flat
  skill for the execution layer's discovery; it is a pointer file).
- `profiles/onboarding-synthesis/v2`: pins prompt v2 and the two v2 skills; everything else
  identical to v1 (grok-4.6, 60 s, 1200 s turn timeout, 48 rounds). The registry digest test
  re-pins.

### 4.4 Driver and steps

- The `synthesis` step keeps its kind and its fast phase and now covers the ICP turn only.
  On `completed` the launcher returns the registered ICPs: `(document_id, icp_key, version)`.
- Each persona turn is a step `kind='persona'`, `subject_ref=<icp_key>`, `phase='background'`,
  started after the ICP step lands and joined before the run settles, under the existing
  `onboarding_max_parallel_runs` semaphore together with the product fan-out.
- Migration: widen `onboarding_step_kind` to admit `'persona'`; reversible.
- The `SynthesisLauncher` seam becomes two calls: `launch_icps(...) -> IcpSynthesisOutcome`
  and `launch_persona(..., icp: RegisteredIcp) -> SynthesisOutcome`; `_SynthesisSeam` in
  `fleet_main` adapts both.

### 4.5 Failure law

- ICP turn `failed` or `empty`: no persona steps; the run settles `completed_with_gaps`.
- One persona turn failing: that `persona` step is `failed`; the others land; the run settles
  with gaps. Persona turns never write or supersede ICP rows.
- Every launcher failure is a step outcome, never a raise (unchanged).

### 4.6 Read surface

No change to the O5 endpoints. `persona` steps appear through the existing `steps` list
(kinds are plain strings on both sides), and the page's refresh hook re-renders on every landed
step, so each persona document shows as its turn finishes.

## 5. Out of scope

What the ICPs or personas say; the generation model; the O6 confirmation gate; migrating
historical runs; the flat-skill pointer arrangement.

## 6. Acceptance (live, founder-triggered)

One unseeded Insight Health re-run on the current catalog:

- the three ICP documents are servable within ~6 minutes of the request (`synthesis` step
  `completed`, ICP rows present) while `persona` steps are still running;
- three `persona` steps run concurrently and the run settles `completed`;
- the ICP keys on file are reused (no new `audience/icp-*` path);
- each persona front matter's `icp_version` equals the ICP row's version;
- fifteen `exa_search_evidence@1` invocations, as before;
- no `exa_search_evidence@1` invocation attributed to the ICP turn.
