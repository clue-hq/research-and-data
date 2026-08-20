# 2026-08-20 — why every generated web page had zero imagery (D1–D4)

Branch `integration/frontend-design-part-iv-v2`, worked directly. Founder-ordered fix
following a completed study that named four independent causes. Commits `dcd4d47a`
(D1), `209f4514` (D2 wiring), `a5e6b832` (D3), `deb718e5` (D4).

The complaint: chat-driven website generation works, but every page comes out with no
generated imagery, no brand-library imagery, and not even the brand's real logo. Four
causes, each sufficient on its own.

## D1 — image generation had never once worked (`dcd4d47a`)

`web_substrate._generate_image_record` sent `"brand_notes": None` into the Rust
generation request. `AssetGenerationConstraints.brand_notes` is a `Vec<String>` behind
`#[serde(default)]`, and serde's default fires on an **absent** key, never on an
explicit null. Every web-lane generation died with `invalid type: null, expected a
sequence`; the author got `asset.image_failed` back and moved on.

Red-proved first: `test_generate_image_falls_back_to_the_stub_provider` fails on the
pre-fix code with exactly that serde message. The path had **zero** coverage —
`generate_image` never appeared in `test_web_substrate.py` — which is why it survived
since the feature shipped. The scene/ad lane always passed a real list
(`substrate.py:~1275`), so this was web-only.

Fix: send the list. Plus `test_generate_image_request_never_sends_a_null_for_a_rust_vec`,
a shape guard over every Vec-typed field in that request. Checked the siblings:
`width`/`height`/`transparent_background` are `Option<T>` (null is fine),
`target_node_id`/`target_slot_id` are `Option` (fine); `reference_asset_ids` is the only
other `Vec` and the web request never sends it — the guard covers it anyway.

Two more repairs in the same function:

- The real-provider branch swallowed everything in `except Exception: pass`. A provider
  outage was indistinguishable from an authoring choice. Now logs and emits LUMA0710 to
  the author (LUMA0711 when nothing is configured), reusing the scene lane's
  `_image_warning` helper and its exact wording.
- Generated imagery is now **brand-conditioned**: `_brand_image_notes()` sends the kit's
  characterization words, imagery rules, tone and palette as style direction, and
  `_brand_style_references()` passes up to two of the kit's own brand IMAGES as style
  anchors. **Images only, never a logo** — a logo handed to a T2I model as a style
  reference gets drawn into the picture. Missing blob bytes degrade to a plain
  text-conditioned generation.

## D2 — the real T2I provider was unconfigured (`209f4514`)

`image_model_configured()` needs `IMAGE_MODEL_BASE_URL` + `IMAGE_MODEL_API_KEY`; both
default `""`, and neither was set in any launch recipe. So even with D1 fixed, only the
grey stub ran.

**The seam needed no change.** `lumen_api/image_provider.py::_invoke_model` already
speaks OpenRouter's chat-completions image modality, already decodes
`choices[0].message.images[*].image_url.url`, and already frames reference images as
style anchors. Verified live, out of process, against four models.

### Model probe (live, 2026-08-20, `CLUE_OPENROUTER_API_KEY`)

Of 414 models OpenRouter served, **11** list `image` in `architecture.output_modalities`
(9 real + `openrouter/auto{,-beta}`). Probed with a real 16:9 hero prompt through
`image_provider.generate`:

| model | result | time | cost/image |
|---|---|---|---|
| `google/gemini-3.1-flash-image` | 1376x768 PNG, 1.74 MB | 14.0s | **$0.0683** |
| `google/gemini-3.1-flash-lite-image` | 1376x768 JPEG, 896 KB | 5.0s | ~$0.034 |
| `google/gemini-3-pro-image` | 1376x768 JPEG, 904 KB | 26.8s | ~$0.14 |
| `google/gemini-2.5-flash-image` | **1024x1024** PNG, 1.15 MB | 6.8s | ~$0.039 |
| `openai/gpt-5-image-mini` | **1024x1024** PNG, 1.24 MB | 51.3s | cheap, slow |

Cost is measured, not inferred: `usage.cost = 0.0682555` on gen
`gen-1787231375-GfUb8LdZEHlfzlUVz1I2` (1120 image tokens). OpenRouter's `image_output`
pricing field is **per token**, not per image — an image is ~1120–1290 tokens.

**Chosen: `google/gemini-3.1-flash-image`.** The deciding property is that it honors the
aspect-ratio hint. A page's hero band is not square, and the 2.5-flash and gpt-5-image
families return 1024x1024 regardless of the hint, so their output is cropped to nonsense
in a 16:9 frame. Among the three that honor it, this is the fastest. The lite model is
half the price and 3x faster but visibly sloppier (a generic sci-fi cityscape where
flash-image produced a restrained lattice); it is the obvious lever if per-image cost
becomes the binding constraint.

**Reference conditioning verified live**: a desk-scene prompt conditioned on the earlier
lattice image came back carrying the reference's palette and edge character. This is what
makes `_brand_style_references` worth having.

### Env / launch recipes

- Root `.env` (gitignored, secret never committed): `IMAGE_MODEL_BASE_URL`,
  `IMAGE_MODEL_API_KEY=${CLUE_OPENROUTER_API_KEY}`, `IMAGE_MODEL_ID`.
- `/tmp/slice4-relaunch-8010.sh` and `/tmp/slice15_fleet_worker.sh` both export all three
  explicitly after sourcing `.env`. **The fleet worker is the one that matters** — it runs
  the design deepagent, so it is the process that generates web imagery.
- `subsystems/clue-design/.env.example` documents the setting with the full probe table
  and a placeholder key.

## D3 — one bad icon voided the whole page (`a5e6b832`)

Proven from the real run trace
(`.deepagent-workspace/run_13a2a40bd7dc4c1cb26f552caa5a9b44/trace.jsonl`): the author DID
write `<img data-asset=…>` for Stripe's real logo in the header, and the whole batch was
rejected — `1 error diagnostic(s); page not stored` — because of `LUMW0114: unknown icon
'globe' on 'ico_64'` elsewhere. The retries were smaller rebuilds; the logo never
returned. So "the page has no logo" was never a missing capability.

**The brief's premise was wrong and this is worth remembering.** The icon list was
ALREADY in the create-website skill and had been since the skill was written
(`893c04cd`). The author was told and guessed anyway. A skill is read once and skimmed;
the author prompt is in context for every token it emits. So the closed set now rides
`build_web_author_prompt` (beside `theme_token_names`, the existing house idiom for a
closed vocabulary), with the penalty stated — *rejects the WHOLE page* — and an
instruction for what to do when the concept it wants is absent.

`tests/test_web_icon_vocabulary.py` parses `const ICONS` out of
`crates/lumen-core/src/icons.rs` and fails if either prose copy drifts. The Rust registry
stays the single source of truth. Deliberately no engine change: no new binding, no wasm
rebuild, no handshake risk.

Engine validation is **untouched** — this informs the author, it does not loosen the gate.

## D4 — the web lane never had to decide about imagery (`deb718e5`)

The scene director declares an imagery choice every create round
(`prompts.py:~126-128`) and its reviewer gates on it (`~467`). The web lane had neither,
while its skills carried ~6 "omit rather than decorate / at most one hero image /
restraint" rules and zero rules requiring imagery. With no forcing step and a one-sided
thumb on the scale, "no imagery" is where the author lands by omission.

Ported without inventing a mechanism: the director declares per-band imagery after
actually looking at the inventory, and it rides into both subagent briefs verbatim (the
guarantee the brand anchor already has); the author executes and reports it band by band
and is told what `mode: "placeholder"` means; the reviewer gets an *Imagery — the decision
check* section in `review-website` (delivered / brand-generic / missing brand mark
[blocking] / placeholder [blocking]) plus an explicit instruction not to score deliberate
restraint as failure or bareness as restraint. It builds on the brief content the
reviewer already receives (slice 4) rather than duplicating it.

## Verification

- `apps/agent_runtime/tests` — **636 collected, 0 failed** (+24 new: 10 in
  `test_web_substrate.py`, 4 in `test_web_icon_vocabulary.py`, 12 in
  `test_web_imagery_decision.py`), run WITHOUT the platform root `.env`.
- Live D2 evidence is the probe table above — a direct out-of-process
  `image_provider.generate(...)`. **No server restarted, no design generation run**
  (the stack is shared with another session's verification and a concurrent implementer).

### Two pre-existing flakes, proven pre-existing, NOT caused by this work

1. **`agent_runtime` intermittently fails one random test with
   `FileNotFoundError: target/debug/lumen-api-helper`.** Without `LUMEN_CORE_HELPER` set,
   `CoreClient._command()` falls back to `cargo run -p lumen-api-helper`, which
   **relinks** that binary — an exec racing the relink loses. A different test fails each
   run. Pinning `LUMEN_CORE_HELPER=<repo>/target/debug/lumen-api-helper` gives a clean
   636/636 every time. **Recommendation for anyone running this suite: pin
   `LUMEN_CORE_HELPER`.** (Recorded, not fixed — out of scope for this wave.)
2. **`apps/api/tests/test_api.py` is order-dependent flaky.** Three runs at the parent
   commit `2ebb3976` in a throwaway worktree failed
   `test_scene_replace_cannot_smuggle_finalized_status`,
   `test_generated_brand_kit_attaches_to_document_and_reports_governance`,
   `test_agent_turns_async_persists_result_and_terminal_event`, and
   `test_generate_asset_image_model_forwards_aspect_size_and_references` — a different
   set each run, including the exact test that failed on this branch. The image-provider
   subset (`-k "image or generate_asset"`) is green on this branch.

## Deliberately NOT done

- **No engine change.** In particular, one bad icon still discards an otherwise-valid
  page. Options for a separate decision, in rough order of preference: (a) downgrade
  LUMW0114 to a warning that drops the offending `<i>` node and keeps the page, the way
  LUMW0124 already warns-and-defaults a bad component prop; (b) auto-substitute the
  nearest valid icon with a warning; (c) leave strict. (a) matches an existing precedent
  in the same file and is the cheapest, but it changes an error to a warning in the
  ingest contract, which is a founder call and needs the AGENTS.md §3 engine gate
  (`cargo test --workspace` → helper rebuild → wasm rebuild → handshake).
- **Nothing under `lumen_ingestion/`** — a concurrent implementer owns asset extraction
  breadth/resolution. No file overlap occurred.
- **No server restarted, no live design generation run**, per the founder's hard rule.
  Which means: the four fixes are proven by tests and by a direct provider call, **not**
  by an end-to-end page. The first real generation on a relaunched fleet worker is the
  remaining acceptance step.
- **The stub fallback still ignores `aspect_ratio`.** The Rust stub provider has no
  aspect handling at all (`lumen-assets` never reads the field), so a placeholder in a
  16:9 hero band is square. Only reachable when the model is down. Left alone.
- **`.deepagent-workspace/knowledge_docs/skills/**` copies were not touched** — that tree
  is gitignored and materialized from `apps/agent_runtime/knowledge_docs/skills/`, which
  is what was edited.
