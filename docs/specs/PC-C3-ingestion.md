# Phase C3 — Raw-Material Ingestion to Claims

**Status:** implemented and integrated on `platform/workspace-restructure` (2026-07-24)

**Parent:** [`PC-phase-c-agentic-layer.md`](./PC-phase-c-agentic-layer.md)

**Shared contracts:** [`PC-C0-step4-contract-freeze.md`](./PC-C0-step4-contract-freeze.md)

**Requirement:** harness REQ-06

---

## 1. Outcome

C3 turns uploaded or referenced client material into durable, segment-addressable evidence and
typed claims through the same storage, adapter, extraction, claim, and governance seams as every
other source.

An upload is not a free-trust blob:

- claims about the client/product may receive client-about-self authority;
- assertions about target accounts cap at tier 3 and corroborate normally;
- raw bytes remain in artifact storage;
- claims point to stable evidence segments;
- unsupported/corrupt inputs fail loudly and durably.

---

## 2. First supported set

- `.txt` and `.md`;
- `.pdf`;
- `.docx`;
- `.pptx`;
- common raster images through OCR.

Web pages already route through scrape adapters. YouTube/video remains a later adapter unless the
existing transcription seam can support it without weakening this slice's exit gate.

---

## 3. Durable model

### 3.1 `ingestion_job`

```text
id
workspace_id
brand_id
product_id nullable
project_id nullable
artifact_key
content_sha256
declared_context_json
media_type
adapter_key
status
failure_code/detail
segment_count
claim_refs_json
retry_count
created_by_actor
created_at/updated_at/completed_at/erased_at
```

Idempotency:

```text
(workspace_id, content_sha256, canonical_declared_context_hash)
```

Identical bytes with different declared entity/scope context are distinct jobs but share the
content-addressed artifact.

### 3.2 `ingestion_segment`

```text
id
ingestion_job_id
ordinal
locator_json
text_sha256
canonical_artifact_key
created_at
```

`locator_json` is adapter-specific but stable, for example:

- text/markdown: byte or character offsets;
- PDF: page + normalized-text offsets;
- DOCX: paragraph/table-cell path;
- PPTX: slide + shape path;
- image: bounding box + OCR text offsets.

Segment bodies are not duplicated in the row. They resolve into the artifact or a canonical
extracted representation stored as another artifact.

---

## 4. Pipeline

```text
captured artifact
  → durable ingestion job
  → media adapter
  → canonical extracted representation
  → stable segments
  → ClaimExtractor
  → field/source validation
  → claim governance + verification
  → claim refs on completed job
```

Rules:

1. Snapshot/artifact existence precedes extraction.
2. A claim insert cannot precede durable segment coordinates.
3. Extractors return drafts; the claim store remains the only claim write authority.
4. Unregistered facts route to C2 proposal refs when that service is injected; they are not
   silently discarded and are not promoted as claims.
5. Retry resumes the failed stage and reuses completed artifacts/segments.
6. Replays do not re-OCR/re-extract or duplicate claims.
7. Paid OCR/model extraction records a pre-spend decision before the external call; an upload is
   authoritative input, not an exemption from cost/policy gates.

---

## 5. Trust and governance

The declared material context must distinguish:

```text
client_about_self
client_about_product
client_about_target
client_preference
project_instruction
unknown
```

Routing:

- self/product facts → claims, tenant-private, eligible for client-stated authority;
- target assertions → source tier no better than 3, normal corroboration;
- preferences/learnings → C4/Doc-M memory writer by injected protocol, not claims;
- project instructions → C4 project-state writer, not claims;
- unknown/unmapped → preserved extraction/proposal reference, not silently dropped.

Contact claims use the production binding/use tagger before immutable insert.
When `product_id` is declared, product facts are born with C4's frozen `Claim.product_id` scope;
C3 never attaches product context after insert. The lane may test this through a temporary
claim-construction protocol until the C4-owned additive claim contract integrates.

---

## 6. Tool and projection

Implement:

- `submit_ingestion`;
- `retry_ingestion`;
- `ingestion_status`.

The external HTTP upload surface:

1. accepts bytes under configured limits;
2. records/puts the artifact;
3. invokes `submit_ingestion` through the toolbelt;
4. returns tool references.

It does not call the ingestion engine directly.

Progress events are derived from durable job transitions and outbox/SSE conventions. No synthetic
“processing” ticks are emitted.

---

## 7. DSAR and retention

- artifact erasure follows the existing refcount/DSAR lifecycle;
- segment/projection reads exclude erased jobs/artifacts;
- derived personal claim/text paths are covered by existing claim DSAR plus C3-specific segment
  cleanup;
- retries cannot resurrect an erased artifact without a new authorized upload;
- failure details must not embed raw personal document content.

Evidence-serving/presign remains blocked until C8's scoped presign policy is closed.

---

## 8. Owned and forbidden surfaces

### Owns

- `subsystems/research/clue_research/ingestion/**`;
- C3 migrations;
- new adapter modules for DOCX/PPTX/OCR;
- `platform/api/clue_api/ingestion_tools.py`;
- `platform/projections/clue_projections/ingestion.py`;
- ingestion tests/fixtures.

### Must not edit/finalize

- proposal stores/policy;
- coverage controller;
- Stage-0 interview/readiness;
- central tool/projection aggregation;
- alternate artifact or claim stores.

---

## 9. Verification

Required tests:

1. all supported formats produce stable segments and resolvable spans;
2. identical upload/context dedupes job, extraction spend, segments, and claims;
3. identical bytes under different context share artifact but not job semantics;
4. target assertions cap at tier 3;
5. self assertions do not leak across workspaces;
6. contact extraction is born governed;
7. corrupt/unsupported input records a durable failure;
8. retry resumes without repeating completed work;
9. cross-workspace job/projection access fails closed;
10. DSAR removes serving/projection reach and personal derived text;
11. preferences/project instructions do not enter claims;
12. unmapped facts preserve a proposal/extraction ref;
13. size/type abuse limits reject before expensive work;
14. crash between artifact, segment, and claim stages resumes consistently.
15. a paid OCR/extractor fake observes its durable gate decision before its call.

Run standing Phase-C, migration, and DB replay gates.

---

## 10. Exit gate

C3 is complete when every supported fixture can be uploaded twice without duplication, every
claim resolves to stable stored evidence, trust depends on what the material asserts rather than
who uploaded it, and erasure removes all serving/projection reach.
