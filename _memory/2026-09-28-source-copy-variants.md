# Source-preserving website copy variants — 2026-09-28

- Continued priority two of the cross-run optimization audit under the active
  website goal. The user restriction against another generation remains active.
  No live app/model/provider run, ingestion, DB write, service restart, page
  mutation, push or publication. No standalone substitute page.
- Native `inspect_cloned_section` now offers bounded text-only inventory (16
  entries/page), exact stored coordinates, editability reasons and pagination.
  It omits HTML/CSS payloads; rendered visibility is explicitly unverified.
- Native `repair_cloned_section(text_edits_json=...)` edits 1-8 immediate plain
  text leaves from the held source through existing fragment custody and checked
  engine pin swap. It preserves source markup/CSS/assets/slots and the existing
  section/layout/bindings; it creates no new slots. Old source stays immutable.
  Canonical and campaign text derivatives have distinct identities, avoiding
  first-writer lineage convergence across those intents.
- Refuses stale/split/unsupported targets, noncanonical paths, bound text,
  separate accessible names, duplicate edits, human overrides and mixed raw
  inputs. Whole batch validation precedes minting. Existing release/swap honesty
  is preserved; CSS preservation does not prove longer copy fits.
- Updated the canonical repair/product-story skills, faithful-repair reference
  and native author prompt to use bindings or exact edits before reconstructing
  a component. No new skill family, provider, flag or schema migration.
- Regression progression: missing runtime schema/arguments and large-source
  response tests failed before wiring (11 red cases); path alias tests failed
  before narrowing the new edit grammar. A supervised read-only review found
  editable inventory text incorrectly included decorative SVG/aria-hidden text;
  two red roundtrip tests reproduced it, then the inventory was fixed to return
  the actual eligible leaf. Reviewer rechecked that fix and exercised the skill
  contract: a human override must remain protected; copy edits do not repair
  inert controls or prove source JavaScript recovery. Clarified a remaining
  reference sentence that could imply full CSS reads for copy-only edits.
- Final focused non-browser regression: 162 tests passed in 117.86s across
  fragment text/href/path tests and native text/cloned-section tests. Skill
  materialization/reference checks: 12 passed. Offline Chromium/real engine
  fixture: 1 passed at 1440/768/375, checking retained typography, responsive
  padding/radius, bound headline, no horizontal overflow and actual disclosure
  activation. Browser networking was blocked. These are mechanism checks,
  not live design-agent/aesthetic acceptance. Scoped Ruff/diff checks passed.
- Replayed the held source-parity feature artifact that has 12,440 HTML chars
  and 201,438 CSS chars. Inventory: 17 targets, six eligible; two JSON pages
  of 4,300/362 chars. All six independent in-memory derivatives preserved CSS
  except namespace plus assets/slot manifest. Source file unchanged, no custody
  write. Summary at `/tmp/clue-text-held-replay-20260928.json`; rendered source
  fidelity not assessed by this replay. No raw source or research in this note.
- An initial test-file creation command used design-root cwd with a repo-root
  relative path and failed before writing; reran from correct cwd. No collateral
  file was created. Preserve the unrelated earlier acceptance/import memory,
  research tests and old audit edit. Engine sources unchanged; no wasm rebuild.
- Still owed: measured source typography/font origin for authored siblings,
  image-composite classification and double-frame repair, responsive height/
  missing product checks on the real examples, stronger evidence-to-copy/CTA
  decisions, retrieval/continuity, and eventual native visual acceptance when
  a new run is authorized. The wider goal remains active and incomplete.
- Closing state: scoped offline checkpoint prepared for local commit on
  `codex/design-agent-v1`; no remote publication or live page changes.
