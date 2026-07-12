# Case study: cutting deepagent turn latency

**A living document.** Each latency tier appends one section with the same
shape — finding → probe → build → measurement. Numbers over adjectives;
caveats and failures recorded as prominently as wins. See the *Maintenance
protocol* at the end before you append.

**Status as of 2026-07-12:** Tier 0+1 shipped and acceptance-measured
(commits `0a8458d` → `7b0fc24` → `7a83450` → `5e28d5a`, ledger `c128d57`).
Tier 2 parked pending evidence.

---

## The problem

A typical design turn ran **6–10+ minutes**; the worst observed run was
**29.3 minutes**. The user set a target: a typical turn should finish in
**~3 minutes**.

The turn is the deepagent harness — a director/author/reviewer trio of
tool-bearing subagents that compile DSL, render previews, and gate on a
fidelity review. The obvious suspicion was that all this machinery — the
compiles, the renders, the exports, the asset ops — was the cost. It was not,
and measuring that was the whole first move.

The binding constraint on every fix: **quality is invariant.** Nothing that
weakens the design output was on the table. Explicitly ruled out from the
start (and re-listed here so no future tier quietly reaches for one):

- **Round caps / resurrecting `max_iterations`** as a quality guillotine.
- **Weaker or smaller models** for any of the three roles.
- **Skipping the reviewer's** kit-asset or reference views, or relaxing the
  fidelity gate.
- **Collapsing the author's compile-repair micro-rounds** — that loop *is* the
  quality mechanism.
- **Parallelizing the think→act chain itself** — it is inherently sequential,
  and tools are only 4–5% of wall, so tool-level parallelism is a rounding
  error today.

Every lever below is either provably quality-neutral by construction, or
flagged as needing a calibration proof before it ships.

---

## Diagnosis: measure before touching

Three explorers mapped the execution path, mined timing from `trace.jsonl`
across 10 real runs, and audited the LLM plumbing. The numbers overturned the
intuition:

- **LLM inference = 93–97% of wall-clock.** All tools combined (compile,
  preflight, render, export, asset ops) came to **4–5%**, never exceeding 77s
  even inside a 29-minute run. `view` is ~0.1s/run. The machinery was not the
  problem.
- **Wall-clock ≈ call-count × ~7.2s.** Pearson **r = 0.944** between
  model-call count and wall time across 11 runs. A 6-minute turn ≈ 40 calls; a
  10-minute turn ≈ 90–120; the 29.3-minute worst case = 225 calls.
- **The smoking gun: input:output ratio of 53–128×.** Each turn re-sent
  **3.2M–12.9M input tokens** for only 45–112K output. Author context grows
  monotonically within a repair round to ~99–110K tokens/call, then resets at
  the round boundary (subagents wake fresh; files are the cross-round memory —
  that design is already right).
- **No prompt caching anywhere.** Zero cache markers; every one of those
  millions of input tokens was prefilled cold on every call.
- **No per-call timeout/watchdog.** Individual calls of 60–97s were observed
  (a director call at 96.7s, an author call at 78.7s). One 18.7-minute run was
  slow purely on per-call latency, not call count.

**One-line diagnosis:** the deepagent is not slow because it thinks too much —
it is slow because it pays full cold prefill on an ever-growing 50–110K-token
context for every one of 40–225 sequential calls, with no caching, no
straggler control, and one tool call per round-trip.

**The 3-minute arithmetic.** 180s ÷ 7.2s/call = **25 sequential calls** at
today's per-call latency. A one-round happy path is ~20–30 calls. So the
target needs *both* levers, neither touching quality: per-call latency 7.2s →
~3–4s (caching + routing + straggler control), and call count −25–40%
(batched reads, wasted-round elimination). A typical 1–2-round turn of 40–60
calls → 28–45 after batching → ×3.5s ≈ **100–160s** — the 3-minute p50.

The full ratified analysis is `.context/next-wave/deepagent-latency-analysis.md`.

---

## The method

Five disciplines held across every slice:

1. **Evidence-first.** Every lever was probed live against the real model
   before any source was built. The probe scripts live in
   `.context/latency-probes/` and are reproducible.
2. **One slice at a time**, each with line review, full test gates, and a live
   smoke.
3. **Measurement landed first.** L0 (trace enrichment) shipped before anything
   else, so every later claim was checkable against real recorded fields
   rather than asserted.
4. **Hard bugs root-caused, never worked around** — the black-PNG class (L4)
   was fixed at the engine, then the residual reviewer-facing hole was closed
   at the choke point.
5. **Cache-safety as an invariant**, documented in the harness so later tiers
   cannot silently break it.

---

## The five slices

### L0 — Trace enrichment (measure first) · `0a8458d`

**Finding.** `model_call_usage` recorded tokens and role but **no
`duration_ms`, no model id, no cached-token count**. Every downstream latency
claim would have been unfalsifiable.

**Build.** Every `model_call_usage` event now carries client-side
`duration_ms` (a run-id-paired start→end wall clock around the invoke), the
served `model_id`, and — when the provider reports them — `cached_input_tokens`
and `reasoning_output_tokens`. `init_model` sends OpenRouter
`usage:{include:true}` (measurement-only) so the cached-prefill breakdown
surfaces. All fields additive, omitted when absent
(`llm.py`, `usage_capture.py`).

**Measurement.** Live-smoked against OpenRouter; grok-4.5 reports cached
tokens. Post-tier acceptance confirmed the fields present on **60/60 calls**
(pre-tier: 0/36).

**Quality safety.** None — observability only.

### L1 — Prompt caching (the biggest lever) · `7b0fc24`

**Finding, and the discovery that mattered most.** The append-only ReAct
history is a stable, growing prefix — the ideal cache shape. A live probe
(`l1_cache_probe.py`, experiment B) confirmed our real pattern hits **89–95%
cached prefill** from the 2nd call on: `cached_tokens` tracks the growing
prefix, and prefill drops from a full ~39K to only the ~2K delta.

**But the replica-scatter discovery** (`l1_cache_locality_probe.py`):
OpenRouter serves `x-ai/grok-4.5` from **4 xAI replicas**, cache is per-server,
and default routing load-balances across them. A byte-identical 30K prefix
sent 8× on default routing cached only **2/8**. With
`provider:{sort:"latency"}` pinning, it cached **8/8** — including the cold
first call being reused. This is the single most important robustness fact:
without pinning, the beautiful cache shape is mostly wasted.

A dedicated follow-up (`l1_sort_alone_probe.py`) **verified sort ALONE is
sufficient** — `allow_fallbacks:false` was *not* needed and was deliberately
left off (it trades resilience for nothing; `sort` alone disables
load-balancing and pins the endpoint). Grok-4.5 turned out to be
first-party-xAI-only (4 endpoints, all provider `xAI`), so `provider.sort`
buys no cross-vendor throughput here — its entire value for this model is
cache locality (and future model choices).

**Build.** `init_model` sends `provider:{sort:"latency"}` (default);
`allow_fallbacks` untouched. The **append-only cache-stability invariant** is
documented in `harness.py`: prune only by *appending* a summary, never by
editing earlier messages — an in-place history edit invalidates the cache from
the edit point onward and forfeits the 95% saving. This is the guardrail L2
and L5 must honor.

**Measurement.** See acceptance below: **93.1% cached** overall, author 95%.

**Quality safety.** Caching changes cost/latency, not output tokens — the
model sees identical context. It is treated as an optimization, never a
correctness dependency (entries evict under memory pressure; caching is never
guaranteed).

### L3 — Straggler control · `7b0fc24` (shipped with L1)

**Finding.** Caching cuts prefill cost but **not** straggler variance — the
probe saw even 100%-cached calls range 3.5s→14.8s, and a 94%-cached call spike
to 14.4s. The 60–97s stragglers from real traces are a *separate* problem, so
the watchdog is independently justified. A `.venv`-source audit established the
timeout/retry seam: `ChatOpenAI(timeout=...)` maps to `request_timeout`; the
OpenAI SDK retries internally then raises `openai.APITimeoutError`, which
langchain/deepagents do **not** catch — it would propagate out of
`agent.invoke` and crash the turn.

**Build.** Per-call timeout (default **60s**, validated positive) +
`max_retries=2` on every deep-agent LLM call. 60s sits comfortably above
genuine calls (≤~3.5s cached, ~5–7s normal) yet catches the 60–97s stragglers
for a retry; calibrate against the now-recorded `duration_ms` p95 before
tightening. Exhausted retries land in the pre-existing honest failed-finalize
path (now pinned by test) so a dead straggler degrades loudly instead of
crashing silently. Both settings blank-disable to byte-identical pre-slice
requests.

**Measurement.** Config active in acceptance (`agent_llm_timeout_s = 60.0`,
`agent_provider_sort = "latency"`); **0 calls > 60s** this turn, so the
watchdog was present but un-triggered.

**Quality safety.** A retried straggler "typically returns at normal latency" —
same call, same model, same context. No output change.

### L2 — Batched tool calls · `7a83450`

**Finding.** Independent read-only lookups ran one per completion — the
reviewer's `view(preview)` + N `view(asset:…)` + M `view(reference:…)` were
N+M+1 sequential calls. A live probe (`l2_batch_probe.py`) confirmed grok-4.5
**emits all six independent reads as one completion, 3/3 trials** when the
prompt teaches batching.

**Build.** Additive batching teaching in all three role prompts: independent
read-only lookups (`view`/`inspect`/`read_file`) are requested as multiple
tool calls in ONE response. An explicit **never-batch list** (task,
`compile_dsl_block`, `render_preview`, `preflight_design`, asset ops, writes)
keeps the shared substrate single-writer. langgraph's `ToolNode` executes
batches concurrently with **deterministic result order**, so the L1
prefix-cache invariant holds. `record()` gained a lock because batched reads
now invoke it from concurrent `ToolNode` threads (`prompts.py`,
`substrate.py`).

**Measurement.** Wired but **lightly exercised** — the happy-path acceptance
turn produced only 2 batches of 3 reads (the reviewer made just 4 calls, so
the gather path had little to stress). Present and non-regressive; not strongly
proven. A reference/kit-heavy turn would exercise it.

**Quality safety.** Same reads, same images, same evidence, same judgments —
purely fewer round-trips. Writes and compiles stay strictly sequential.

### L4 — Wasted-round elimination · `5e28d5a`

**Finding — the black-PNG mechanism.** Two real runs (`run_1c2c517…`,
`run_5054a27…`) burned repeated author+reviewer rounds because the PNG raster
went **solid black after the first export while the SVG stayed correct**. The
reviewer re-attached ~40K-token images round after round on an already-valid
scene. Root cause: an unresolved token paint led to a skipped artboard fill,
leaving alpha-0 that flattened to black in the PNG — while the SVG carried a
white fallback, so it *looked* fine. This was already root-cause-fixed in the
engine (`925bdec` white-clear + magenta sentinel) and agent (`055264d`
token-paint refusal); the L4 investigation **reproduced the old bug
deterministically** from recovered run artifacts
(`.context/latency-probes/png-black/repro_png_black.py`) and proved the fix
live.

**The residual hole, and why it needed care.** A magenta `LUME0213` sentinel
frame could still reach the reviewer as `status=ok`, because preview
validation only checked PNG magic bytes. The fix is a pixel guard at the
artifact-validation choke point, and its **asymmetry is deliberate**:

- **≥99% sentinel pixels ⇒ hard `validation_error`** (export flips to error;
  the frame never reaches review as ok).
- **≥99% near-uniform anything ⇒ loud NON-blocking warning** — because a
  minimalist design can be legitimately near-uniform. **Never block a design
  on a heuristic.** A false sentinel is a bug; a near-uniform poster might be
  the intended art.

The guard never raises and counts on a 64px NEAREST thumbnail
(`substrate.py`, `render.py`).

**L4b — the unchanged-scene guard.** When a valid export re-renders a scene
with zero mutations since the last render, the result carries a deterministic
`unchanged` fact (+ trace event `unchanged_rerender_recorded`) and the
orchestrator is taught to reuse the standing critique instead of re-delegating
a review of identical pixels (definitionally zero-information). This is
**advisory, not a hard block** — deliberately, so it cannot deadlock the RC
anti-rubber-stamp `REFUSED → re-review` path (that exception is preserved).

**Quality safety.** L4a is also a *correctness* fix — a black raster blocks
honest pixel review. L4b never suppresses a legitimate re-review; it only
declines to re-review byte-identical pixels, and yields to the fidelity guard.

---

## Acceptance results

One live turn on a fresh server built from HEAD `5e28d5a`. Brief: a "Pulse"
analytics-dashboard launch poster, no references, minimal-scene fixture, all
three roles on `openai:x-ai/grok-4.5`. Full write-up:
`.context/latency-probes/tier1-acceptance/ACCEPTANCE.md`.

> **One turn is a sample, not a proof.**

| Metric | Baseline (plan) | PRE-TIER sample | **UPGRADED sample** |
|---|---|---|---|
| Wall-clock | 6–10+ min | 3.32 min | **4.98 min** |
| Model calls | 40–120 | 36 | **60** |
| s/call (wall÷calls) | ~7.2s | 5.54s | **4.98s** |
| Mean LLM invoke | (unmeasured) | n/a | **4.52s** (p50 3.35s, p95 12.9s, max 19.6s) |
| Cached fraction | 0% | 0% | **93.1%** |
| Total input tokens | 3.2M–12.9M | 1.31M | 3.15M |
| **Uncached prefill input** | = total (cold) | 1.31M | **0.22M** |
| input:output ratio | 53–128× | 69.6× | 111.1× (93% from cache) |

Per-role (UPGRADED):

| role | calls | input tok | cached % | mean ms | p95 ms | max ms |
|---|---|---|---|---|---|---|
| author | 41 | 2,699,768 | 95.0% | 4620 | 10750 | 19601 |
| orchestrator | 15 | 392,391 | 83.7% | 3874 | 5807 | 12916 |
| reviewer | 4 | 57,301 | 65.4% | 5890 | 14405 | 14405 |

The author dominates (41/60 calls, 86% of input) exactly as predicted, and is
where caching pays most. A single 132K-token author call paid only ~2.7K
uncached prefill.

**Honest caveats — read the wall-clock carefully:**

- **Wall-clock did not drop in this sample** (299s vs the 199s pre-tier
  control) — because it ran **more calls** (60 vs 36; 41 author micro-rounds
  vs 17). Call-count is the plan's own #1 wall driver (r=0.944) and varies
  turn-to-turn independent of the tier. The per-call metrics the tier isolates
  all moved the right way: **s/call 5.54→4.98, cached 0%→93.1%, uncached
  prefill 1.31M→0.22M.**
- **One turn is a sample, not a proof.** The 7.2→3–4s target is *partially*
  realized: p50 invoke 3.35s is in-target; the 4.52s mean is dragged by a
  handful of stragglers.
- **Straggler tail persists.** Max author call 19.6s (a 130K-token call), p95
  12.9s — under the 60s watchdog, so not killed.
- **Batching lightly exercised** — only 2 batches this happy-path turn.

**The stale-server trap (an operational lesson).** The first turn fired
against an API already running on :8000 — launched at 05:14, *hours before* the
tier commits landed at 19:29–20:43, with no `--reload`. It ran the OLD pre-tier
code: `model_call_usage` carried no `duration_ms`/`cached_input_tokens`/
`model_id` (0/36 calls), cached fraction 0%. The real measurement required a
fresh server from HEAD on :8010. **Restart the API after pulling these commits
or none of this fires.**

Gates for the tier: runtime 474 · api 309 · zero regressions. No engine
sources touched, so no wasm/handshake implications.

---

## What's next (Tier 2 — parked pending evidence)

The parked levers, and the honest reason each waits:

- **L5 — author-context pruning.** The monotonic climb to ~100K is largely
  superseded compile-diagnostic payloads (errors already fixed in later
  attempts). *But L1's 93% caching weakens L5's case:* pruning rewrites
  history, which invalidates the cached prefix from the edit point and
  forfeits the ~95% prefill saving. L5 now has to **beat the cache** to be
  worth shipping — and if it prunes at all, it must do so by appending, never
  by editing earlier messages. Behind a flag, A/B'd on
  acceptance/fidelity/round-count before default-on.
- **L6 — vision-payload downscale.** Cap the `view` image long side to
  ~1024–1280px — **only with a K4-style calibration proof** that judge scores
  on a fixed scene set do not move. Not shipped without that evidence.
- **L7 — per-role reasoning effort.** `reasoning=medium` is uniform; author
  mechanical-repair steps plausibly don't need it. This is a quality knob —
  A/B on acceptance metrics only, default to leaving it alone.
- **Batching-adoption watch.** L2 is wired but lightly exercised; a
  reference/kit-heavy turn should confirm it fires under load.

**The real next lever is call count, not per-call latency.** Per-call cost is
now mostly cached away; the wall is dominated by the number of author
micro-rounds (41 in the sample). Reducing *unnecessary* round-trips — without
touching the compile-repair loop that produces quality — is where the next
minutes live.

---

## Maintenance protocol

This document is **appended per tier or slice**, never rewritten. Each new
section follows the same shape:

1. **Finding** — the measured or probed fact that motivates the change (with
   numbers).
2. **Probe** — the live experiment that de-risked it before any source was
   built; leave the script in `.context/latency-probes/` and reference it.
3. **Build** — the mechanism and the key file(s); the quality-safety argument.
4. **Measurement** — before/after numbers from a real run; state plainly when
   a result is a single sample.

Rules of the register:

- **Numbers over adjectives.** Every claim carries a figure traceable to a
  probe, a trace, or an acceptance run. No invented figures.
- **Record failures and caveats as prominently as wins** — the stale-server
  trap, the flat wall-clock, the un-triggered watchdog all belong in the story.
- **Never weaken quality to buy latency.** If a lever could touch output, it
  ships behind a calibration proof or an A/B, or it does not ship.
- **Honor the cache-stability invariant** (append-only history) — it is the
  guardrail every future pruning idea must respect.
