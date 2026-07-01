
## Verdict: harden the platform first, then prove it, then build more. Do **not** start Slice 1 next.

Concretely: **(1) tool consolidation + cheap doc-link fixes → (2) live e2e DoD gate → (3) close Slice-0 gaps the gate exposes → (4) Slice 1, ROI-ordered.**

## The one fact that decides the order

**Every remaining capability item you listed *adds tools to a budget you are already over.*** `place_icon` (+1), `generate_svg` (+1), `vectorize_image` (+1) — and you're at 26 tools against a hard 20-strict cap that is an *active crash*, currently survived only by the hack of giving **both subagents empty tool lists** (`prompts.py:337–354`).

That hack isn't free. Your `lumen-dsl-author` and `lumen-visual-reviewer` subagents **can't call any tools right now** — not `generate_image`, not `place_asset`, not `inspect`. So the deepagent imagery loop is running half-crippled, and it's the exact loop the e2e gate is about to measure.

So the sequencing writes itself: **you can't pour more capability onto a cracking foundation, and you shouldn't spend credits validating a system you've intentionally hobbled.** Fix the budget → un-hobble the subagents → *then* measure → *then* add.

The audit makes this nearly free: 26→17 with **zero changes to the Scene/Operation/DSL contract**, Group A flagged "highest value, lowest risk." And the cost of this refactor *only rises* — every tool you add later means more call sites to consolidate. This is the cheapest it will ever be.

## The sequence

**Sprint 1 — Harden the agent platform (~3–5 days, low risk, high leverage). Do this now.**
- Tool consolidation: Group A `inspect` multiplexer (−5), Group B `asset` dispatcher (−3, keep the node-vs-slot branch the critic flagged), Group C drop `persist_trace_event` (−1) → **26→17**.
- **Remove the subagent `tools:[]` workaround** — at 17 tools you're under the strict cap, so subagents can hold real (consolidated) tools again. This likely *directly improves* the deepagent imagery loop, for free.
- Bundle the **Tier 0–1 doc cross-link fixes** (~½ day): wire `loop/authoring-and-repair` into `AGENT.md §3`, link the critic to its rubrics, the `images↔assets` boundary. Better retrieval → better output → a fairer e2e read.
- *Defer Tier 4 (`assumes:` frontmatter).* It's the right cure but it's a bigger build — do it as the **first** Slice-1 task, to pave the road before Slice 1 adds ~10 docs.

**Sprint 2 — Prove it (de-risk the core hypothesis).**
- Run the **live e2e DoD gate** with credits, *on the consolidated architecture* (social ad w/ hero, deck w/ icon row → `.context/post-imageslice0-runs/`), capture baseline + acceptance numbers.
- Why after Sprint 1, not before: validating the hobbled-subagent system would give a pessimistic, throwaway read — you wouldn't know if a bad result is the *architecture* or the *workaround*. Measure the system you're keeping.
- This is the go/no-go for "Slice 0 is production-usable," and it tells you whether the **quality-loop-generate gap** actually bites in practice.

**Sprint 3 — Close the Slice-0 gaps the gate exposes (data-driven, not a priori).**
- Quality-loop generate path and/or editor icon UI + `place_icon` — now cheap, you have headroom. Prioritize by what the e2e actually showed was missing, not by the list order.

**Sprint 4 — Slice 1, ROI-ordered (never as a monolith).**
- First: Tier 4 doc graph (`assumes:` + CI linter) — pave before the traffic.
- Then the genuinely enterprise-blocking items: **PDF image+gradient fidelity** (decks silently drop images *today* — `pdf.rs:286`), **reference-image style-lock** (brand consistency), then `generate_svg`/`vectorize_image`. Defer filters/shaders/crop-editor/WebGL until pulled by real demand.

## The one thing NOT to do
Don't touch Slice 1 features next, and **stop running parallel work-threads in other chats** — these items are *dependent*, not independent. Consolidation enables clean Slice-1 tool additions; the e2e validates before you build more. Serializing them is the whole point.

---

**Immediate next action:** start **Sprint 1**, beginning with **Group A `inspect` multiplexer** (pure reads over `self.scene`, no core call — the safest possible first cut, and it proves the consolidation pattern before touching the asset/op tools).

I have the agent-runtime context loaded from this session. Want me to kick off the tool consolidation now — Group A first, then B/C, restoring subagent tools, gated on the agent suite staying green — and fold in the Tier 0–1 doc links as I go?
