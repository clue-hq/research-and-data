# ABM Design Engine

This repository contains the Design Engine subsystem for the ABM orchestration platform.

The current implementation starts with the contract foundation:

- scene model
- page/artboard model
- node model
- slot model
- operation model
- renderer/export adapter contracts
- validation scaffolding
- Blueprint-inspired DSL compiler

Reference material lives in `reference_docs/`.

Workstream docs live in `docs/`, including `docs/dsl-compiler.md` for the current DSL grammar and lowering contract.

## Local Setup

For a one-command local setup on macOS, open Terminal in the repo root and run:

```bash
./scripts/setup_local_dev.sh
```

The setup script:

- creates a Python virtual environment at `.venv`
- installs the FastAPI and agent-runtime Python packages
- installs the editor Node packages
- installs missing macOS prerequisites with Homebrew where possible
- installs Rust with Homebrew if `cargo`/`rustc` are missing
- builds the Rust `lumen-api-helper` used by the FastAPI app
- creates `.env` from `.env.example` if `.env` does not already exist
- runs a quick verification pass

If you want setup to also start both local servers, run:

```bash
./scripts/setup_local_dev.sh --start
```

Then open:

```text
http://127.0.0.1:3000
```

### API Keys

The deep-agent routes every LLM call through **OpenRouter** — there is no
native-provider path. The setup script will not overwrite an existing `.env`. If
`.env` is created from `.env.example`, add your OpenRouter key before using
DeepAgent calls:

```bash
LUMEN_AGENT_API_KEY=your_openrouter_key_here
```

`LUMEN_AGENT_BASE_URL` is prefilled to the OpenRouter API. The editor and backend
still run without the key, but live agent calls fail loudly until it is present.

### Choosing a model / provider

The deep-agent is model-agnostic *through a single fixed gateway*: **OpenRouter is
the only gateway for every LLM call, and you vary only the model.** There is no
native Anthropic/OpenAI path — the model is selected from config, never hardcoded
at a call site.

`LUMEN_AGENT_MODEL` must be an `openai:<openrouter-model-id>` value so LangChain
selects the OpenAI-compatible client. Switching models means changing only this id:

```bash
LUMEN_AGENT_MODEL=openai:anthropic/claude-opus-4.8   # or
LUMEN_AGENT_MODEL=openai:google/gemini-3-pro         # any OpenRouter model id
LUMEN_AGENT_BASE_URL=https://openrouter.ai/api/v1    # prefilled
LUMEN_AGENT_API_KEY=your_openrouter_key
```

A model without the `openai:` prefix, or a missing key, is rejected at startup
with a clear error rather than failing later as an opaque 404 — `init_model`
enforces the contract. The editor's model chip (Auto / Opus / Sonnet / Gemini)
sends the same `openai:` ids per turn; **Auto** falls back to the env default.

Ingestion helpers (asset description, role-assist, PDF vision) and image
generation route through OpenRouter the same way, each via its own override —
`LUMEN_INGESTION_DESCRIBE_MODEL`, `LUMEN_INGESTION_ASSIST_MODEL`,
`LUMEN_INGESTION_VISION_MODEL` (default `anthropic/claude-sonnet-4.5`) and the
`IMAGE_MODEL_*` vars in `.env.example`.

### Manual Run Commands

If you ran setup without `--start`, start the backend API with:

```bash
set -a; source .env; set +a
PYTHONPATH=apps/api:apps/agent_runtime .venv/bin/python -m uvicorn lumen_api.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, start the frontend editor with:

```bash
NEXT_PUBLIC_LUMEN_API_BASE_URL=http://127.0.0.1:8000 npm --prefix apps/editor run dev -- --hostname 127.0.0.1 --port 3000
```

Backend URL:

```text
http://127.0.0.1:8000
```

Frontend URL:

```text
http://127.0.0.1:3000
```

The core rule is that `crates/lumen-core` remains platform-independent. It must not depend on React, Konva, FastAPI, databases, S3, filesystem I/O, browser APIs, or WebGPU.

Detailed workstream docs:

- `docs/contract-foundation.md`
- `docs/core-scene-ops.md`
- `docs/qa-conformance.md`
- `docs/dsl-compiler.md`
- `docs/slots-layout.md`
- `docs/preflight-pipeline.md`
- `docs/api-persistence.md`
- `docs/observability-structured-logging.md`
- `docs/phase-f-editor-export-productization.md`
