# Agent failure forensics — run_8cbeae790f07 (generation brief into seeded default doc)

**The user's read is correct: this was a CONTEXT failure, not a model-capability
failure.** At every step the model's *reasoning* was right — it diagnosed the
mismatch, chose the largest permitted rewrite mode, obeyed the no-page-redeclare
rule after being corrected — and then failed on a grammar form our docs, recipe,
and corrective hints never showed it. Give an Opus-class model the right context
and it writes the right code; we didn't.

## The run (fixture prompt #1, `pricing_living_type_portrait_none`, 111s, 3 iterations, 0 ops)

Seed: the old default editor doc — "Hospital Letter" A4, one `node_contact_name`
text node, `document_id: null`. Prompt: "Design a 1080x1350 bold typographic
statement card…".

| Iter | What the agent did | Verdict | Whose fault |
|---|---|---|---|
| 1 | Director: `layout_cluster_rewrite`, rationale explicitly notes seeded mode forbids fresh authoring — CORRECT. Author emits `page page_a4 size(1080,1350,px)` + full rebuild — a GOOD design, but re-declares the existing page. | LUMA0200 pre-guard rejects the block whole. | Docs: the "repurpose an existing near-empty page" idiom existed nowhere. The natural move (re-declare with new size) is exactly what the guard forbids. |
| 2 | Our corrective hint said: "Edit existing content with `` `#<id>` `` modify lines." Director passes it on as *"use modify syntax on the existing page (e.g. `#page_…`)"* — and the author writes `#page_a4 size(1080,1350,px)` + `replace(page_a4)`. | LUMD0901 halt at line 1: "target node page_a4 does not exist". Whole block rejected. | **Ours, doubly.** (a) The corrective instruction taught ambiguous grammar — `#<id>` reads as `#page_a4`, but the page-modify form is `#page:page_a4`. (b) `replace()` takes node ids only — also never stated. The model followed our hint literally and correctly. |
| 3 | Director correctly re-diagnoses ("prior attempts tried to recreate the page rather than modify it") but STILL instructs `#page_a4 size(1080,1350,unit=px)` — the wrong form now propagating through the director's own instructions. Author also tries a bare `page_a4` continuation line. | LUMD0901 + LUMD0205. Rejected. | Ours: once the wrong form entered the repair context, nothing in the context could correct it — no doc, no example, no deterministic reroute knew the `#page:` form. |

Result: zero compiles → no best draft ever existed → `failed`,
"max iterations without a clean draft" → the editor showed the unchanged seed as
"Draft visible", which reads as a broken/blank canvas.

## Where the agent's context failed it (ranked)

1. **Page-ref grammar absent from every context surface the run saw.**
   `#page:page_id` appears only in `knowledge/lumen-dsl/directives.md`'s table —
   which was not among the loaded snippets' effective guidance for this turn.
   The SEEDED_CONTINUATION_RECIPE showed only node-modify examples; the
   corrective LUMA0200 hint said `#<id>`. Three surfaces, all silent or wrong.
2. **No "repurpose this page" idiom anywhere.** The correct one-block move —
   `#page:<id> size(w,h,px)` then `replace(<existing_root_node>)` + new subtree —
   was never written down. This is the single most common cold-start scenario
   (generation brief into a doc with a default page).
3. **The deterministic guardrail (0b) had a blind spot.** `reauthor_correction`
   knew LUMD0401/LUMA0200 but not the LUMD0901-where-the-"missing-node"-is-a-page
   trap — so from iteration 2 on, the loop had no mechanism to break the wrong-
   grammar cycle. Prompts drift; guardrails must not.
4. **`replace()` / `clone()` / `delete()` arity docs don't say "node ids only."**
5. **Review/repair loop burned iterations without escalating context.** After two
   grammar halts, nothing re-loaded `directives.md` or surfaced the ref-grammar
   table into the repair context. (Future: on repeated LUMD09xx halts, auto-pin
   the directives grammar excerpt into the author request.)

## Fixed today (code, this commit)

- `loop.py`: `reauthor_correction` now detects the page-ref trap (LUMD0901 whose
  missing "node" id is an existing page — both `#page_a4` and `replace(page_a4)`
  message shapes) and emits the exact `#page:<id>` + repurpose-idiom correction;
  the LUMA0200 instruction now spells out the page form, that replace() is
  node-only, and the new-page option.
- `prompts.py` recipe: ref-grammar bullet (`#node_id` / `#page:page_id` /
  `#slot:key`; directives take node ids only) + the REPURPOSING idiom bullet.
- Editor: default document is now EMPTY ("Untitled design", zero pages — no more
  Hospital Letter/Dr. Priya), and `agent_seed_scene` treats an empty document as
  unseeded — so a cold-start generation brief takes the proven fresh-generation
  path instead of continuation-vs-scaffold. Plus honest messaging when a failed
  run's "draft" is byte-identical to the seed (no more "Draft visible" over an
  unchanged canvas).

## Doc improvements to make later (the user's ask — where to focus)

- [x] `knowledge_docs/AGENT.md` hard invariants: ref-grammar invariant added
  (#3: typed refs + document-global node ids). *(agent-quality track, 2026-07-04)*
- [x] `knowledge_docs/skills/repair-design`: "Repurposing a nearly-empty default
  page" playbook + replace-is-node-only rule added.
- [x] `knowledge_docs/knowledge/lumen-dsl/directives.md`: WRONG/RIGHT example
  (`#page_a4` ✗ → `#page:page_a4` ✓) under the ref table + node-ids-only rule
  on structural directives.
- [x] Knowledge loader: seeded turns now pin `directives.md` via
  `extra_mandatory_paths` (`tools.load_knowledge` keys on
  `seeded_from_initial_scene`).
- [ ] Engine candidate: LUMD0901's hint could say "did you mean `#page:<id>`?"
  when the missing id matches an existing page — the correction would then be
  provider-agnostic (helps the deepagent path too, not just the editor loop).
  *(still open — engine-side, needs wasm rebuild; the Python loop guard covers
  the editor path)*
- [x] Escalation heuristic: implemented generalized — TWO consecutive compile
  halts with the same code (any code, not just LUMD09xx) pin the ref-grammar
  excerpt into the next author request (`repeated_halt_escalated`); identical
  re-emitted blocks skip compile/review and escalate (`repeat_block_escalated`).
- [ ] Also on the backlog from the fixtures README: the deepagent photo path's
  LUMV0100 crash (generate-image before any page exists) — same class of
  "cold-start ordering" context gap. *(still open)*

## 2026-07-04 addendum — LUMD0401 cluster forensics (2e M2 gate, 3/4 turns dirty)

Full decomposition + fixes in the agent-quality-track commits on
`agents/editing-roundtrip-v0`: document-global id rule (prompts + create-design),
`duplicate_in_block` reauthor correction (within-block duplicates are NOT
existing-node re-declarations; never reroute surgical at a phantom node),
`completed_with_warnings` → editor proposal (two of the three "failed" gate
turns had preflight-clean drafts discarded by the API mapping), and the two
non-convergence escalations above.
