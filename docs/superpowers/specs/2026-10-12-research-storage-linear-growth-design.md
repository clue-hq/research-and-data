# Research storage: linear growth, same erasure guarantee

Status: proposal for founder review (2026-10-12). Nothing here is implemented.

## 1. The problem, measured

The dushanbe lane database is 3.9 GB. 94% of it (3.66 GB) is one table, `artifact_derivation`
(5.77 million rows). One account research run (run 5, Dialpad, stopped after 19 minutes) wrote:

| Store | Run 5, 19 min | Growth | Read by |
|---|---|---|---|
| `artifact_derivation` rows | 492,000 rows, ≈ 310 MB with indexes | quadratic (steps × sources) | one erasure trigger |
| Model-request snapshots (`agent-model-input` blobs) | 183 files, 93 MB | quadratic (each call saves the whole conversation) | nothing in product code |
| Agent checkpoints (`checkpoint_blobs.messages`) | 362 versions, 191 MB raw / ≈ 97 MB on disk | quadratic (full message list per step) | resume / continuation |
| Actual research evidence (pages, search results, transcripts) | ≈ 18 MB | linear | everything |

So roughly 20 MB of research costs about 500 MB to store. 91% of the current link rows belong to runs
the lane cleanup already deleted (the reset scripts never removed artifacts or links); in production
nothing is deleted, so every run would add its ≈ 300 MB of links permanently.

## 2. Why each store grows quadratically

### 2.1 Lineage links
`ResearchArtifacts.persist_body` (`platform/api/clue_api/quality_research_artifacts.py`) runs for every
artifact an agent step saves: model request, model reply, tool result, plan proposal, validated plan,
tool parameters, dossier. For each one it selects every evidence source of the run for that account
(person agents: the account's and their own), every context document, the context pin and every claim
support in the context, takes `FOR SHARE` locks on all those rows, and inserts one
`artifact_derivation` row per source. A step at minute 20 links ~1,000 sources; the next step links the
same ~1,000 plus anything new. Rows = steps × sources.

The only reader is the trigger `erase_derived_artifacts` (migration `aaae5d2e1fa4`): when an artifact is
marked `privacy_erased`, it marks every child erased, and those updates fire the same trigger, so
erasure already cascades through any chain.

Erasure is started in three places: a contact's privacy objection (erases that person's provider
results, all or only email/phone), discarding unselected committee results, and retention expiry.

### 2.2 Model-request snapshots
`agent_runtime_wiring.on_chat_model_start` serialises the full request (every message) and saves it
before each model call. Call 100 re-saves calls 1–99's messages. The reference is recorded in
`agent_artifact_ref` (role `model_input`); the turn projection lists the key and hash, but nothing reads
the bytes. Langfuse and the checkpoints hold the same conversation.

### 2.3 Checkpoints
deepagents declares `messages` as a `DeltaChannel` (full snapshot every 50 updates, deltas between), the
documented fix for O(N²) checkpoint growth. In our graph the checkpoint metadata tracks the delta counter
only for `files` (`counters_since_delta_snapshot: {"files": …}`), and every `messages` blob is a full
list (account agent: 91 blobs growing from 10 KB to 1.16 MB). Some layer in our stack re-declares
`messages` with an ordinary reducer and silently turns the delta channel off.

## 3. First principles

* Erasure is rare (an objection, an expiry); agent steps are constant (hundreds per run). Pay at erase
  time, not at write time.
* A step's lineage today is not "what this step read". It is "everything in this account's evidence up
  to now" (the account agent is linked to person sources it never opened). That set is a prefix of an
  append-only, already-numbered log: `arv2_evidence_source.revision` per `(run, account)`. A prefix is
  one number, not a thousand rows.
* Content-addressed storage already deduplicates identical bytes (`artifact_key = workspace/sha256`). A
  conversation is append-only; storing it message by message makes repeated prefixes free.
* Over-erasing is safe; under-erasing is the failure. Any replacement must erase at least what today's
  links erase.

## 4. Proposal

### 4.1 Lineage watermarks replace manifest-wide links
New table, one row per artifact `persist_body` saves:

```
artifact_lineage_scope(
  workspace_id, child_key  -- PK, FK artifact
  run_id, account_id,      -- the evidence log it was derived from
  subject_id NULL,         -- NULL = account-level step (sees every subject); else the person
  evidence_revision,       -- highest evidence revision visible when it was saved
  context_id               -- for context documents, the context pin and claim supports
)
index (workspace_id, run_id, account_id, evidence_revision)
index (workspace_id, context_id)
```

* **Write:** one row per step instead of ~1,000. `persist_body` reads the manifest's current revision
  and takes one `FOR SHARE` lock on the `arv2_evidence_manifest` row (and the context row) instead of
  locking every source. The "refuse if any parent is erased" check becomes one indexed `EXISTS` over
  erased sources at or below that revision.
* **Erase:** the trigger gains one branch. When an evidence source's artifact is erased (revision r,
  subject s, account a), mark erased every scope row with the same run and account,
  `evidence_revision >= r`, and `subject_id IS NULL OR s IN (subject_id, a)`; when a context document,
  pin or claim support is erased, every scope row with that `context_id`. The erasure path takes
  `FOR UPDATE` on the manifest row first, which closes the write/erase race the per-source locks close
  today. The existing per-edge cascade stays for the precise writers (claims, pages, reconciliation,
  evidence, dossier report): they link only what they cite and grow linearly.
* **Same guarantee, proven on real data:** every source a step links today has a revision at or below
  that step's highest linked revision, so the range rule erases a superset of today's set. Checked on run
  4's full data: 836 agent steps, 306,646 links, 0 links the rule would miss. The rule over-erases about
  116,000 step/source pairs (sources that were saved but not yet visible to the step, from parallel
  agents); over-erasing audit snapshots on an objection is acceptable.
* **Why not chain links (step → previous step + new sources):** also linear, but erasure would then walk
  hundreds of trigger levels per agent (Postgres trigger recursion depth, at the worst possible moment),
  and each step would still need a "what's new since last step" diff. One number per step is simpler and
  erases with a single indexed update.

### 4.2 Model requests stored message by message
Save each message once as its own content-addressed artifact (canonical JSON, so identical messages hash
the same); the per-call snapshot becomes a small manifest (message hashes in order, model parameters,
sha256 of the reconstructed request). The same approach is used by Laminar (5–10× on long agents, ~50× on
50-turn agents) and by Shelley's prefix-deduplicated request table. Each new message gets a watermark row
(4.1), so erasure covers it. Bytes per run drop from the sum of all prefixes to the conversation once plus
the cleared/compacted variants.

### 4.3 Turn the checkpoint delta channel back on
Find the state declaration that overrides deepagents' `DeltaChannel` on `messages` (our state schema or a
middleware's `state_schema`), restore the delta reducer, and add a test that a 60-step agent saves
≈ 2 full message snapshots, not 60. Resume and continuation are unaffected (they read the graph state,
which `DeltaChannel` reconstructs).

### 4.4 Cleanup and retention
* Migration (reversible): backfill `artifact_lineage_scope` from today's links (revision = highest linked
  source revision; subject and context from the job), then delete the manifest-wide links. Downgrade
  regenerates them from the watermark. Lane space comes back after `VACUUM FULL artifact_derivation`
  (an operator step, not part of the migration).
* Lane reset script: also remove a deleted run's artifacts, links and checkpoints.
* Founder decision: should step audit artifacts (requests, replies, tool results, plans) expire, for
  example after 90 days, through the existing `expires_at` purge? Research evidence and claims would not.

## 5. Expected effect per run (estimates from run 4 / run 5)

| Store | Today | After |
|---|---|---|
| Lineage rows | ≈ 460,000 rows / ≈ 300 MB | ≈ 1,000–2,500 rows / < 1 MB |
| Model-request snapshots | ≈ 90–100 MB | ≈ 10–15 MB (measure after 4.2) |
| Checkpoints | ≈ 100 MB on disk | ≈ 10 MB (measure after 4.3) |
| Per-step write work | select + share-lock up to ~1,000 rows | one manifest lock + one `EXISTS` |

## 6. Considered and not proposed now

* **Crypto-shredding** (per-subject encryption keys, delete the key to erase): the standard answer for
  immutable logs and backups. Our stores are deletable, so it does not address cost, and our derived
  artifacts mix many subjects in one blob, which per-subject keys cannot express without re-encrypting.
  Worth revisiting for backups.
* **A transitive-closure table:** makes "find every descendant" one lookup but grows faster than what
  we have (AiiDA dropped theirs for this reason).
* **Dropping request snapshots entirely:** nothing reads them, but they are the only durable record of
  exactly what personal data was sent to a model provider after middleware edits; storing them
  deduplicated keeps that record at a fraction of the cost.

## 7. Order of work

1. 4.3 checkpoints (smallest change, independent).
2. 4.1 watermarks + migration + erasure tests (an erasure on run-4-shaped data must mark a superset of
   what today's links mark).
3. 4.2 message-level request storage.
4. 4.4 lane reset script; retention decision.

Sources: Laminar trace compression (laminar.sh/blog/laminar-20x-agent-trace-compression); Shelley
prefix deduplication (git.secluded.site/shelley commit 507852af); AiiDA provenance (arxiv 2003.12476);
SPARK provenance queries (arxiv 1808.08424); crypto-shredding (kurrent.io, conduktor.io).
