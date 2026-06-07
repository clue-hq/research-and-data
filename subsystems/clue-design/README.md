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

Reference material lives in `reference_docs/`.

The core rule is that `crates/lumen-core` remains platform-independent. It must not depend on React, Konva, FastAPI, databases, S3, filesystem I/O, browser APIs, or WebGPU.

Detailed workstream docs:

- `docs/contract-foundation.md`
- `docs/core-scene-ops.md`
- `docs/qa-conformance.md`
- `docs/slots-layout.md`
