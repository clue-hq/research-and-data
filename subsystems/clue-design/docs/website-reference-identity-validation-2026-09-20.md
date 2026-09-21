# Captured resource identity validation — 2026-09-20

## Defect and repair

Capture can hold `/sprite.svg` while a section names `/sprite.svg#mark`. Exact-key harvesting previously refused that section even though the bytes existed. Separately, HTML/CSS rewriting discarded the suffix even with a correct explicit rehost map, losing an SVG symbol selector or a video's `#t=...` start time.

A shared immutable index now groups only fragment-equivalent HTTP(S)/relative spellings. Query text/order, percent encoding and every other URL spelling remain exact. If any alias of that resource names different held content, lookup refuses even when an exact key exists. Non-web schemes still require an exact explicit custody entry. Held payloads are compared once per group and cached; large video bytes are not repeatedly hashed.

Section harvesting uses this index and retains the raw source token as its rehost-map key. HTML attributes/srcset and CSS URL/image-set rewriting preserve the authored suffix on the content-addressed asset URL. CSS string escaping and raw-style-element defusing remain active, including hostile quotes, backslashes, newlines and markup in suffixes. Same-document references stay local; unmapped bytes still refuse.

## Verification

The implementer first reproduced three failing harvest cases (base-only capture, another fragment alias, and conflicting exact/base bytes) and a browser-visible SVG failure. Parent reviewed the shared implementation, applied the minimal harvest integration and independently ran 290 tests across reference identity, artifact sanitation, section minting and source document context; all passed in 5.17 seconds.

The offline browser check serves a symbol-only SVG from an intercepted asset-store route. Its sanitized external `<use>` renders the expected 30 × 20 geometry; the old suffix-dropping sanitizer produces an empty symbol. Query differences, ambiguity, scheme/custody boundaries, source-ref idempotence and CSS breakout attempts are covered.

Evidence: `.local-setup/website-capture/fragment-identity-parent.xml`. New helper/test and changed refs/sanitizer files are Ruff-clean. Existing unrelated full-file lint debt in cssscope.py remains. No real sources were fetched, no model calls or live DB writes were made, and the video byte cap was unchanged.

This fix does not manufacture missing bytes: uncaptured custom-property images need a subsequent ingestion run, and videos refused by the current byte budget remain unavailable. Full website reproduction and all-brand visual acceptance are separate work.
