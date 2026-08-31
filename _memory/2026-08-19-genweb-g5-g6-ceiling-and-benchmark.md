# 2026-08-19 — genweb G5 (multi-image vision ceiling) + G6 (terra/luna latency benchmark)

Branch `integration/frontend-design-part-iv-v2`. Brief:
`.superpowers/sdd/2026-08-19-chat-driven-website-generation/g5-g6-brief.md`.
Report: `.superpowers/sdd/2026-08-19-chat-driven-website-generation/g5-g6-report.md`.

## G5 — the provider rule, established with evidence

**The live failure (slice 2).** Design run `run_c6f448531a124f8ab7c6c0def696b95e`
(platform run `run_503a8ad2a62a5558beeb5ef6c0762200`, doc `doc_a37154cd…`, leg
`529b34a1…`), fleet log `/tmp/slice2_fleet_worker.log:1345`:

```
ValueError: ResponseError(code='invalid_prompt', message='messages.1.content.39.image.
source.base64.data: At least one of the image dimensions exceed max allowed size for
many-image requests: 2000 pixels')
```

Facts from that trace, worth keeping:

- the refusal hit the **orchestrator's** own call (`role: orchestrator`,
  `message_count: 58`), not the reviewer subagent — the orchestrator is the accumulator,
  because every `view` image it ever requested stays in its history;
- 48 view completions in the run, **38 of them image-bearing**
  (`preview:1440` ×17, `preview:375` ×9, `preview:768` ×4, `state:*` ×8);
- the serving model was `anthropic/claude-opus-4.8` through OpenRouter's
  `/api/v1/responses` endpoint (the endpoint the runtime calls);
- the turn is transactional, so the whole authored page was discarded (`current_version`
  stayed 0).

**The probe (cheap, three scripts under `/tmp/g5_vision_ceiling_probe*.py`).** Same
provider, same endpoint:

| images | per-image size | verdict |
|---|---|---|
| 20 | 200×7500 | ACCEPTED |
| 21 | 200×7500 | **REFUSED** (many-image message) |
| 25 / 40 | 200×7500 | REFUSED |
| 40 | 200×3000 / 4000 / 5000 / 6000 | REFUSED |
| 40 | 600×2500 | ACCEPTED |
| 40 | 200×2000 | ACCEPTED |
| 40 | 200×7500 on `openai/gpt-5.6-terra` | ACCEPTED (no such limit today) |

So: **the threshold is >20 image blocks in one request** (exactly the vendor's
documented number), and at that point the per-image dimension limit bites. The
enforced edge sat between 2500 and 3000 px in the probe while the refusal message
states **2000**; the vendor doc says the message "states the current limit in pixels"
and instructs "resize each image so that neither dimension exceeds 2000 px, or keep the
request to 20 or fewer image and document blocks". 2000 is therefore the number the
provider itself tells us, and it was accepted at 40 images — twice the count that killed
the run. Undocumented slack above it is folklore; the constant is 2000.

Also learned: OpenAI-served models (`gpt-5.6-terra` / `-luna`, the current pin) enforce
no such limit today. The clamp is for the provider set, not one pin.

## G5 — the fix (commit `ddd19dfd`)

`lumen_agent/tools/view.py`: `_VISION_MANY_IMAGE_MAX_PX = 2000` beside the existing
`_VISION_MAX_PX = 7500`; `_normalize_image_bytes(raw, max_px=…)` and
`_image_block(path, max_px=…)` take the ceiling as an argument (default unchanged).
`web_substrate.py` passes the many-image ceiling at both attach points (preview widths
and state captures).

**Why unconditional and not count-aware** (the plan had suggested count-awareness): an
image is encoded ONCE, at attach time, and then lives in the history every later request
replays. By the time a request is "many-image" the earlier images are already inside it
at their original size — a clamp that tightened on the 21st image would still send the
first twenty oversized and still be refused. Count-awareness only works if you also
rewrite history, which is a different (middleware-shaped) mechanism. The fidelity cost is
small: providers downscale to their own long-edge budget anyway (Claude's high-resolution
tier renders at most a 2576px long edge), so a 1440×14325 page capture was never being
judged at 7500px.

**Scene path deliberately untouched** — it attaches one artboard preview per view call
and has never hit this refusal; a test pins that divergence. Residual: a very long scene
turn could in principle accumulate >20 images on its orchestrator too. Not observed; the
mechanism is now one argument away if it ever is.

Tests (TDD, red first): 4 clamp/constant tests + a scene-divergence guard in
`tests/test_view_and_finalize_hygiene.py`; 3 web-path tests in `tests/test_web_substrate.py`
(preview, state capture, and 6 review rounds × 3 widths all under the ceiling);
1 diagnostics test in `apps/api/tests/test_web_turns.py` asserting the verbatim
many-image refusal reaches `diagnostics` (`web_turn.no_result`) if it ever recurs.

## G6 — the latency benchmark (terra/luna), 2026-08-19

Stack: design API 8010 relaunched onto HEAD `da644813` (G5 `ddd19dfd` + G7 `957a1e09`
both in) via `/tmp/slice0-relaunch-8010.sh`; the BFF web-turn path (`POST
/documents/{id}/web/turns`) on a FRESH scratch web document each time; istanbul fleet
worker not needed for this path (8010 runs its own embedded worker). tunis (16459) and
missoula untouched.

**Brief (verbatim, from `design_agent_run(run_503a8ad2…).payload.config.request.prompt`
— the turn that died at ~28 min in slice 2):** *"Yes please — go ahead and build it.
Hero with the launch headline, three benefit cards, and a 'Book a demo' call to action
at the bottom."* on a document titled "Insight Health launch landing page". (The plan
text remembers a FAQ section; the recorded prompt has none. The recorded one was used.)

**Per-role model landing — verified LIVE**, from the governed gateway's
`model_call_usage` records (`role` + `requested_model` + `served_model`):

| role | model requested | model served |
|---|---|---|
| `design_orchestrator` | `openai/gpt-5.6-terra` | `openai/gpt-5.6-terra` |
| `design_author` | `openai/gpt-5.6-terra` | `openai/gpt-5.6-terra` |
| `design_reviewer` | `openai/gpt-5.6-luna` | `openai/gpt-5.6-luna` |

No fallback, no drift, on both runs. (`llm_call_*` trace events log
`"model": "unknown"` — the gateway usage record is the authority for model id.)

### The numbers

| | run A (`doc_cf2aa052…`, lumen `run_d0386178…`) | run B (`doc_aab0e9ac…`, lumen `run_ce71a624…`) |
|---|---|---|
| **wall clock** | **600.1 s (10.00 min)** | **195.1 s (3.25 min)** |
| outcome | applied / accepted, v0→v1 | applied / accepted, v0→v1 |
| author: delegations / model calls / seconds | 5 / 59 / 363.9 s (60.6 %) | 2 / 19 / 118.7 s (60.8 %) |
| orchestrator: calls / seconds | 24 / 165.9 s (27.6 %) | 10 / 46.5 s (23.8 %) |
| **reviewer: rounds / calls / seconds** | **1 of 6 cap** / 3 / 36.7 s (6.1 %) | **1 of 6 cap** / 2 / 20.4 s (10.5 %) |
| renders (`render_web_preview`) | 5 | 2 |
| `view` calls (image-bearing) | 78 (68) | 28 (23) |
| tool time (all tools) | 13.7 s (2.3 %) | 3.8 s (1.9 %) |
| model time as share of wall | 94.4 % | 95.1 % |
| mean author call | 6.2 s | 6.2 s |
| cumulative author prompt tokens | 1.39 M | 0.38 M |
| `web_apply_ops` helper errors | 8 (recovered) | 0 |

**Verdict vs the 3–5 min target: MET ONCE, NOT RELIABLY.** Run B is inside the band;
run A is 2× over. The difference is not provider latency — mean author call latency is
identical (6.2 s) — it is *how much work the agent chose to do*: 5 author rounds / 5
renders / 78 views versus 2 / 2 / 28. Run A additionally built a modal dialog component
(and ate 8 malformed `web_apply_ops` retries); run B routed the CTA to an on-page
section. Wall clock ≈ (number of model calls) × ~6 s: 86 calls → 600 s, 31 calls → 195 s.

**Next lever, in evidence order:** (1) bound AUTHOR delegations the way G4 bounded
reviewer rounds — author time is ~61 % of both runs and the delegation count is what
varies; (2) collapse the orchestrator's `view` traffic (78 calls = 78 model round-trips
at ~6.9 s; returning all three widths in one call and refusing an identical re-view
would remove most of them); (3) the 8 `web_apply_ops` schema errors in run A (3 ×
"missing field `kind`", node-kind/id mistakes) each cost an author round-trip.

### What the runs say about G5

Both runs crossed the >20-image threshold — **68** and **23** image-bearing view calls
in a single accumulating conversation — and both completed. Honest caveat: the pinned
models are OpenAI-served and enforce no many-image limit today (probe: 40 × 200×7500
accepted on terra), so these runs do not by themselves prove the clamp; the proof is the
probe + unit tests. What they do show is the shape the clamp must survive, and it is
comfortably past the threshold that killed slice 2 on an Anthropic model.

Second-order finding from G7: with the Tailwind runtime restored the pages now LAY OUT,
so whole-page captures are far shorter — 1440×1774 and 768×1737 (in-band, passed through
byte-identical) versus the 1440×14325 of the layout-less era. Only `preview:375`
(375×2757) is still clamped (→ 272×2000). The many-image ceiling therefore costs almost
nothing at desktop/tablet widths today.

### Residual / notes

- One orphaned `running` design-run row (`run_322d1ace…`) from an earlier benchmark
  attempt whose server was killed mid-run; harmless, ignore.
- The design API's `execute_web_turn_job` does NOT apply `render_leg_turn_prompt`, so a
  web-turn leg's `delegation_bundle` brief and leg history never reach the runtime prompt
  (the scene executor does apply it). Slice-2's dead run shows the same: the runtime saw
  only the user's sentence. Not G5/G6's to fix — recorded for whoever owns the leg→web
  prompt contract.
