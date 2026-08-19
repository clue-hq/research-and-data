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
