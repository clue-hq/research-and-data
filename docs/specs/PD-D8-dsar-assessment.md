# PD-D8 — DSAR reach over design rows: assessment

**Status: ASSESSMENT ONLY — RATIFIED SCOPE.** Founder instruction 2026-08-10: this slice
*assesses* DSAR reach over the design plane and records the approach; it makes **zero wiring
changes**. That is also the literal D8 gate wording in `PD-part2-design-substrate.md` §1
("DSAR reach over design rows **assessed**"). The wiring is a tracked post-Part-II follow-up
whose natural home is decided in §6.

**Parent:** `docs/specs/PD-part2-design-substrate.md` (Part II contract; §8 scopes what D8 may
revisit: DSAR/erasure reach under the platform's tombstone discipline and operational storage
concerns — **never** silent compaction that destroys design history).
**Inputs:** full read of `clue_research/compliance/` (dsar.py, workspace_erasure.py),
`clue_storage/artifacts.py`, every `design_*` migration, the design DAL
(`subsystems/design/clue_design/`), and the D6 tool-journaling path, taken 2026-08-10 at HEAD
`a2963f0e`.

---

## 1. Verdict in one paragraph

The design plane holds personal data on **31 distinct surfaces** (inventoried in §3), and **none
of them is reached by any existing DSAR or erasure path**. This is not an accident of omission
but a structural consequence of three facts: (1) DSAR reach is defined over the `claim` table
(`identity/reuse.py::dsar_private_claims`) and no design row is a claim; (2) the storage purge
refcount counts *claim* citers only, and the D4 `{ws}/design/{sha}` namespace deliberately keeps
design blobs out of that machinery (confirmed working — §4.1); (3) the design plane has **no
data-subject key at all** — zero contact references anywhere, and an account join that is
nullable, domain-derived, and merge-blind. Erasure needs a selector before it needs a primitive;
today design has neither. The platform's own precedents (claim tombstones, the
`entity_research_*` redact-in-place stamps, the faithfulness-rationale redaction) map onto
*some* design surfaces and genuinely do not map onto others (§5).

## 2. What exists on the platform side (the machinery any design wiring would join)

- **Claim tombstones** (`compliance/dsar.py`): erasure is supersession-by-tombstone — a new
  REJECTED claim row carrying `{"__erased__": true}`, audit-first insert into `dsar_tombstone`
  (UNIQUE on `erased_claim_id` = idempotency), dependent-derivation expansion, then two-phase
  blob erase (`mark_erased` → post-commit `purge_erased_artifacts`, which un-erases a re-cited
  key: "live evidence beats a stale intent").
- **Redact-in-place stamps** for JSONB bodies with no supersession chain:
  `entity_research_agent_event.payload_json := {'erased': true}` + `payload_erased_at`, and
  siblings (turn context, tool-batch results, legacy handoff payloads). This — not the claim
  tombstone — is the precedent shape for most design surfaces.
- **Workspace erasure** (`workspace_erasure.py`): the C8 Client-KB closure + a durable
  no-resurrection marker. Names zero design tables.
- **The selector**: `dsar_private_claims(entity_id, workspace_id)` — reach is enumerable only
  over claims. Every non-claim surface dsar.py touches was hand-wired table-by-table; there is
  no erasure-participant registry.

## 3. Design personal-data inventory (condensed; per-table classification)

**HIGH-density surfaces** (routinely hold/render identifiable personal data):

| Surface | Where the personal data rides |
|---|---|
| `design_document` | `current_scene_json` (all rendered copy), `title`, `agent_instructions`, undo/redo stacks |
| `design_edit_envelope` / `design_operation_log` | `operations_json` **and** `inverse_operations_json` (the pre-edit value — a second copy); append-only by founder ruling |
| `design_snapshot` / `design_template_revision` | frozen full `scene_json` copies |
| `design_asset` + `design_asset_description` | `filename` (e.g. a person's name), `record_json`; AI-generated *descriptions of image content* — the surface most likely to describe a person |
| `design_binding_set` / `design_instance` | `binding_json` (the substitution values — names, titles, quotes) and `derived_scene_json` (values already substituted, one row per template×binding fan-out) |
| `design_account` | `name`, `domain`, `data_json` (the flat `account.*` namespace — nothing stops `champion_email` living here), `notes` |
| `design_web_publish_revision` / `design_web_publish` | fully rendered personalized `html`; revision DELETE is **trigger-rejected**; unpublish flips status, never removes html |
| `design_agent_run` | D5 frozen turn envelope `payload` (brand kit, **account card copied by value**, assets) + `result_json`; plus the LangGraph `checkpoints*` rows behind `checkpoint_thread_id` |
| `design_ingestion_job` | `request_json` (URLs, staged-upload keys), `evidence_json` (scraped third-party pages — names, emails, team photos) |
| `run_event` rows with `subject_kind='design_run'` | operations arrays and result envelopes in payloads |
| `tool_invocation` + parameter artifacts | `response_json`; every governed design mutation's **full input body** journaled as an artifact |
| Design blobs `{ws}/design/{sha}` | uploaded images (faces), publish assets, component first-frame renders |
| Off-substrate | engine materialization cache (wipeable mirror) and `.lumen-runs/` trace dirs (full operations ledgers on local disk) |

MED surfaces (free-text/JSONB that can quote a person): brand kits + compat reports, batch
manifests, repair-request reasons, diagnostics, compilation output, `design_generation_result.record_json`
(the prompt itself is **not** stored — only its sha256 rides in `generation_key`).

**Reach today: 0 of 31.** The only deletion primitives in the entire design DAL are
`delete_asset_record`, `delete_web_account`, and `delete_binding_set` (plus the byte-GC
`delete_design_bytes` behind the asset tool). There is no delete for documents, snapshots,
template revisions, publishes, runs, or ingestion jobs — by design (append-only posture).

## 4. Findings that stand on their own (record now, regardless of when wiring lands)

### 4.1 The D4 namespace disjointness works — confirmed
No claim ever cites a `{ws}/design/{sha}` key; `live_claim_count` counts claim citers only; the
zero-refcount purge therefore cannot reach a design blob (tests
`test_design_storage_key_is_namespaced_and_validated`,
`test_the_public_read_cannot_reach_the_claim_evidence_namespace`). The design byte-GC's
deletability test consults only `design_asset` rows + `design_document.current_scene_json` — it
does **not** consult snapshots, template revisions, instances, publish html, or the op log, so a
digest still named by history is deletable (dangling ref; the accepted-safe direction) and those
surfaces are not protected reference-holders. Any future erasure wiring must own the full
reference decision.

### 4.2 HAZARD — design tool-parameter artifacts live in the bare claim-evidence namespace
`clue_execution/parameters.py` keys parameter bodies as `{workspace_id}/{sha256}` — the claim
namespace, not `{ws}/design/{sha}` — and the design toolbelt deliberately reuses it
(`lumen_api/toolbelt/wiring.py`: "indistinguishable from one written by the platform, including
to DSAR erasure"). Consequence: every design tool's full input body (image prompts, binding
values, account `data_json`) sits where `erase_if_unreferenced` **would** purge it
(`live_claim_count` = 0 forever), yet nothing ever enumerates those keys (no claim cites them,
no `discovery_artifact_subject` row exists). Reachable-in-principle, enumerated-by-nothing —
and equally true of *platform* tool parameters. Wiring must either give parameter artifacts a
citers story or accept and document scheduled purge-by-enumeration.

### 4.3 GAP — design LangGraph checkpoints are invisible to the existing checkpoint deleter
dsar.py's checkpoint cleanup selects thread ids **from `entity_research_agent_turn` only**;
design `checkpoint_thread_id`s (= design run ids) are never enumerated, so a design turn's graph
state (which embeds the frozen envelope, account card included) is unreachable even by the flow
that already knows how to delete checkpoint rows.

### 4.4 GAP — the design→platform account join is merge-blind
`design_account.account_entity_id` is born-nullable, FK `NO ACTION`, domain-derived, and **no
design read resolves `merged_into`** (zero hits; the platform has ~15 resolving call sites). A
merged-away entity stays stamped on `design_account` forever. Contact erasure, by contrast, has
no design-side effect *by construction* — the design plane holds zero contact references.

### 4.5 No data-subject selector exists for the personalization plane
`design_binding_set`/`design_instance` carry no entity reference of any kind; their personal
values are unjoinable to a data subject by any query. Until a subject key exists (§6 step 1),
per-subject erasure over personalization is *undefined*, not merely unimplemented — only
workspace-level erasure can honestly claim it.

## 5. Where the platform precedents map — and where they don't

**Map cleanly:** live mutable JSONB rows (account `data_json`, asset descriptions, run
payloads/results, ingestion evidence) → the `entity_research_*` redact-in-place +
`erased_at`-stamp shape. Brand kits (version-per-row) and publishes (live row vs immutable
revision) have native "publish a redacted successor, re-point the live row" schema support. The
edit-envelope plane already has the append-a-forward-corrector primitive
(`reverts_batch_id`/`reapplies_batch_id`).

**Do not map:**
1. The op log has **no supersession chain and no eligibility predicate** — it is read
   positionally; a "redaction op" appended to it would redact nothing unless every replayer is
   taught to honour it. Value-level redaction-in-place (structure preserved, value replaced,
   one-way stamp) is the only shape compatible with both the founder's append-only ruling and
   Art.-17 intent — and it must hit `operations_json` and `inverse_operations_json` together
   (the inverse array carries the pre-edit personal value).
2. The read path is not the log: `current_scene_json` is truth; redacting history changes
   nothing served, and redacting the scene leaves history intact. Erasure must treat
   scene + snapshots + revisions + instances + publish html + log as **one closure**, the way
   dsar.py expands derived claims.
3. `design_web_publish_revision.publish_id` is content-addressed (`webpub_` + package digest)
   and DELETE-rejected — redacting html in place would break the content address. The honest
   move is a new redacted revision + re-point, with the original's bytes handled at the blob
   layer.
4. `dsar_tombstone` is claim-shaped (`erased_claim_id uuid` → `claim`); a design redaction has
   nowhere to record itself. Wiring needs either a polymorphic subject address on that table or
   a design-side audit sibling.
5. Blobs have no tombstone concept anywhere — `mark_erased` + physical delete is the only
   discipline for bytes, and that is fine: the artifact *row* survives as audit.

## 6. The approach (what the wiring will look like, when it is built)

Ordered; each step is independently shippable. **None of this is built in D8.**

1. **Subject resolvability first.** (a) Harden the account join: merge-aware resolution
   (`merged_into` following) and a backfill story for domain-less accounts. (b) Rule on
   personalization: either binding values gain an optional subject reference at write time
   (contact/account entity id per binding set), or binding sets are ruled *operator-supplied
   workspace data* — erasable only via workspace erasure — and that ruling is written down.
   This step should be designed **with Part III**, not before it: Part III replaces the interim
   account join and introduces the delegation bundle (account/contact context flowing into
   design turns), which is exactly where subject keys naturally enter.
2. **Erasure primitives per surface class** (per §5): redact-in-place + stamp for live JSONB
   and for append-only history values (both operation arrays together); redacted-successor +
   re-point for publishes and brand kits; closure semantics across
   scene/snapshot/revision/instance/publish; design-side byte erasure that owns the full
   reference decision (§4.1); design checkpoint-thread enumeration added to the existing
   deleter (§4.3); `run_event` design-subject payload redaction (or rely on retention once the
   D8 pruner's window passes — but a DSAR cannot *wait* on a retention window, so redaction is
   still needed for young rows).
3. **Audit + registry.** Polymorphic (or sibling) tombstone audit addressing; and fold design
   surfaces into an erasure-participant registry rather than extending dsar.py's hand-wired
   table list a 15th time — the hand-wiring is the platform's own recorded growth pain.
4. **Parameter-artifact hazard (§4.2)** is upstream of design: fix it once at the
   `clue_execution` layer (citers row or scheduled enumeration), and design inherits it.

**Recommended owner/timing:** step 1 lands with Part III (it needs Part III's context-flow
decisions); steps 2–3 follow as a dedicated post-Part-III compliance slice; step 4 can land any
time as a small platform-side slice. Until step 1 exists, the only honest DSAR answer for
design data is **workspace-level erasure** — and even that names zero design tables today, so
it must be the first consumer of step 2's primitives.

## 7. Explicitly not done in D8 (per founder instruction)

No schema changes, no redaction primitives, no selector, no dsar.py/workspace_erasure.py
edits, no parameter-artifact re-keying, no checkpoint-deleter extension, no merge-aware join
resolution. The D8 pruner (Round 2) is a *retention* mechanism scoped to design progress
events on terminal runs — it is not, and must not be presented as, an erasure mechanism.
Revisit triggers: Part III start (step 1 must be in its design inputs); any real-tenant
onboarding under GDPR-grade posture (the §4 hazards stop being latent); any presign/serving
work over design blobs (interacts with §4.1's reference decision).
