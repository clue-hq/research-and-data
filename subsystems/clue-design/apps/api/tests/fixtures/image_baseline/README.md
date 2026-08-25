# Image-pipeline baseline — Step 1b

A deterministic, re-runnable capture of the **image-generation pipeline as it stands
on this branch** (Slice 0, through Step 1b: the OpenRouter chat-completions adapter is
wired). It exists so that every later step (2–10) can be measured against a fixed
reference instead of "looks better to me."

## What it captures (server side, end-to-end)

```
recorded model response                     ← held constant (see "Why recorded")
  → image_provider.generate()               request contract + decode + result shaping
  → CoreClient.ingest_asset(generated)       content-addressed ingest, provenance/license
  → compile_dsl_into_scene()                 DSL → scene
  → apply_operations(upsert_asset)           embed the asset record into the scene
  → preflight_scene(platform_default kit)    resolve $surface/$type/$space + layout geometry
  → inject asset_placement {fit,focal,alt}   (not yet expressible in DSL — Step 7 adds it)
  → export_preview(png)                      real Skia render
```

| File | What it is |
|------|------------|
| `capture_baseline.py` | the harness that produces everything here (re-runnable) |
| `manifest.json` | the contract: request endpoint+modalities, result meta, ingest provenance, preflight diagnostics, placement, render dims + **sha256s** |
| `request.json` | the exact OpenRouter request body our adapter emits (Authorization redacted) |
| `result.meta.json` | normalized `ImageGenerationResult` (mime, model, license, provenance) + bytes sha |
| `asset_record.json` | the ingested asset record — note `source.kind == "generated"`, raster dims, license |
| `design.lumen` | the poster DSL that places the generated image (image hero + brand band) |
| `reference_source.png` | the deterministic stand-in for the model's output (held constant) |
| `generated_source.png` | the bytes that came back out of `generate()` (== reference in recorded mode; the real photo in `--live`) |
| `render.png` | the rendered poster — the visual baseline (byte-stable across runs) |

## Why "recorded" and not a real photo

A live smoke test on `2026-06-19` reached OpenRouter and validated the whole adapter
(key authenticates, model id valid, `modalities` accepted, errors typed correctly) but
returned **HTTP 402 "Insufficient credits"** — the account has never purchased credits.
So a real generated image is currently blocked on a credit purchase, not on our code.

More importantly, the model's *photographic content* is **not** what Steps 2–10 improve.
They improve decode, ingest provenance, placement (fit/focal), scrim, render fidelity,
and (later) the agent's authoring choices. So we hold the image constant — a procedurally
generated reference with a clear off-center focal subject — to isolate **our** engineering
from model noise. The reference is byte-deterministic, so `render.png` is byte-stable.

## Re-running

```bash
# credit-free (default) — uses the recorded reference image
/tmp/lumen-smoke-venv/bin/python capture_baseline.py    # any interpreter with httpx + the built helper

# live — swaps in the real OpenRouter model (needs IMAGE_MODEL_* in .env + credits)
… capture_baseline.py --live
```

Prereqs: the built `target/debug/lumen-api-helper` (the harness points `LUMEN_CORE_HELPER`
at it), `.env` with `IMAGE_MODEL_*` (only `--live` actually needs the key/credits), and
`httpx`. When `.env` names no `IMAGE_MODEL_ID`, the harness defaults it to
`google/gemini-2.5-flash-image` (a real OpenRouter image-output model) — but `.env`
wins when it does name one.

**W1.4 trap:** the id must be served on OpenRouter's *chat-completions* image modality,
which is a narrower list than "OpenRouter image models". `openai/gpt-image-2` is real but
Image-API-only, so on this path it 404s with *"No endpoints found that support the
requested output modalities: image, text"*. Verified working: `openai/gpt-5.4-image-2`,
`google/gemini-2.5-flash-image`.

## How to compare across steps

When a step lands, re-snapshot into a sibling dir (`../image_baseline_step4/`, …) and diff:

1. **Render** (`render.png`) — the headline artifact. Does imagery read better? Is text
   legible over/under it? Is vertical distribution intentional?
2. **`manifest.json` diagnostics** — `render.diagnostics` / `preflight.diagnostics` should
   shrink. Today's known gaps (the "before" we're improving):
   - `LUME0205` band hug/fill geometry warning at export.
   - No scrim → text sits in a plain white band, not over the image (scrim grammar is Step 10).
   - Loose vertical distribution in the band (Step 4/9 critic + recompose).
3. **Placement** — Step 7 makes `fit`/`focal`/`alt` expressible in DSL, so `design.lumen`
   should carry them instead of the harness injecting them post-compile.
4. **Agent authorship** — once Step 3 wires `generate_image`/`place_asset` agent tools (and
   credits exist), replace this hand-authored DSL with a real `.lumen-runs/<id>/` agent run
   on the same brief, and compare the agent's choices to this hand-authored "ideal-ish" floor.

## The brief

> Editorial photograph of a focused neurosurgeon reviewing a glowing 3D brain scan on a
> translucent display in a modern hospital, cinematic teal-and-deep-navy lighting, shallow
> depth of field, premium healthcare brand aesthetic, no text

4:5 social poster (1080×1350): generated image hero (cover-fit, focal 0.5/0.4) over a brand
band with kicker / headline / body. Mirrors the existing `square_linkedin_neurosurgery`
evaluation fixture so it slots into the same comparison family.
