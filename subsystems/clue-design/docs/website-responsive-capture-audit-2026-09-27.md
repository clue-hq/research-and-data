# Responsive capture and native page quality audit

Status: diagnosis and recommended boundary, not an implemented capture feature or
an accepted landing page. Audited on `codex/design-agent-v1` at `466c32b1`.

## What the current failure establishes

The native page test successfully received the complete imported account overview,
read the website skills and bound genuine account branding. Its output still failed
the requested quality bar. Separate failures have separate owners:

| Failure | Observed evidence | Owner / current status |
| --- | --- | --- |
| Thin account argument and internal caveats in visitor copy | Fresh run read all six overview sections; saved revision still contains analyst caveats | Native composition/review adherence; not solved by adding more research context |
| Inert source feature controls | Captured markup retains four visuals but not the original state controller | Native tabs reconstruction exists in the latest revision; exact source layout, autoplay and progress remain unqualified |
| Product interface absent on phone | Original site's mobile product shell contains JavaScript-mounted UI; captured fragment's corresponding mobile branch contains only its gradient image | Missing viewport-specific source DOM; not an image-resolution defect |
| Reviewer misses visible defects | A saved 379×7464 phone capture normalizes to 102×2000 | Bounded saved-preview tiles implemented and locally verified; native agent adoption still pending |

The latest revision removes the unwanted navbar and places genuine marks above the
hero. That is partial progress, not evidence that the page is ready. All four product
states, links, exact phone width and the visitor-facing argument still need native
verification. Imported research retains its original verification status.

## Capture path and constraints

1. `apps/api/lumen_ingestion/capture/rendered.py::_harvest_page` settles lazy content,
   clears stage overlays, then harvests one DOM/CSS/probe/screenshot/geometry set.
   Plain Chromium uses 1440×2000. The default stealth backend preserves its own
   coherent viewport and browser fingerprint; it does not use that forced viewport.
2. `capture/snapshot.py::SiteSnapshot` holds one HTML document and its source assets.
3. `site_snapshot.py::_persist_one` stores content-addressed bytes, then upserts one
   row. `site_snapshot_id` and the database's uniqueness constraint both key on
   `(job_id, page_url)`. Appending a mobile capture as another flat page entry would
   replace the desktop row's pointers, not retain a responsive pair.
4. `pipeline.py::_mint_page_fragments` segments each captured DOM and mints sanitized,
   scoped fragments under shared capture/mint budgets. `sections/mint.py::_provenance`
   retains snapshot ID, viewport width, section index, DOM path, element ID and
   geometry.
5. `lumen_api/agent_cloned_sections.py` lists approved fragments and resolves repair
   lineages. A WebDoc cloned-section node pins one artifact. There is no responsive
   variant-selection contract in this path today.

Fragment IDs hash their content, assets, slots and preview digest. They identify an
immutable artifact, not the same logical section across different browser states.
DOM paths are reliable only within the captured document. JavaScript may change the
tree at another width, so matching solely by path or section index is unsafe.

The agent's `fetch_page` tool fetches bounded text and links. It cannot replace a
missing responsive browser capture. Downloading arbitrary JavaScript bundles also
does not recover original React source, executable dependencies or observed behavior.

## Alternatives

**Recommended first boundary: retain a bounded capture-variant manifest.** Keep the
existing logical page row and default capture compatible. Add explicit, versioned
variant evidence containing separately captured HTML, CSS, screenshot, geometry and
asset references. Store all bytes through the existing scoped custody seam and pin
the immutable manifest digest in fragment provenance. A failed secondary capture
must leave the default usable and declare its coverage gap.

This avoids a database migration, but it still requires coordinated snapshot-loader,
mint-adapter and native inspection changes. Existing page/byte/time/section budgets
must be shared across variants, not multiplied silently. Stored variants alone do
not make an existing page responsive.

**Alternative: first-class capture variant rows.** Add capture identity and a logical
page group to the database contract. This supports clearer querying/lifecycle but
requires a reversible migration and every single-snapshot consumer to select its
variant explicitly. It is a larger first change for the observed defect.

For either approach, viewport siblings must not use `derived_from`: that field means
repair lineage, whose selection can collapse siblings into one representative.
Keep distinct immutable artifact IDs. A separately evidenced logical family may
pair unambiguous source sections; uncertain matches remain unpaired.

## Consumption and acceptance

The first implementation should expose the additional evidence to the existing native
agent, which can repair a responsive fragment through the existing sanitized route.
It should not concatenate whole HTML trees or run third-party scripts in delivery.
Automatic viewport switching between sibling artifacts would be a further contract:
it needs explicit ranges, synchronized content slots, unique DOM IDs and valid ARIA
references. It is not implied by capture storage.

Required proof before calling responsive recovery complete:

- Old capture fixtures, existing pinned fragments and default readers remain valid.
- Desktop and phone capture bytes survive together and retain distinct hashes;
  retrying a job cannot silently retarget evidence pinned by an existing fragment.
- Workspace isolation, cancellation and existing shared budgets remain enforced.
- A fixture that mounts different DOM at different widths retains both real branches;
  a failed secondary capture reports missing evidence without claiming fidelity.
- Native section inspection exposes the source variant and actual measured width.
- A page created through Clue displays the actual product interface at 375, 768 and
  1440px, with no horizontal overflow. Every reconstructed feature state is observed,
  including keyboard operation. Saved static crops do not count as interaction proof.
- A second unrelated source verifies the fix is not a Conduit-specific exception.

Account-copy acceptance remains separate: the page must connect an actual account
insight to a supported seller capability and a useful proposed evaluation. Internal
verification notes stay in the working brief. Company biography, swapped names and
unsupported promises do not satisfy personalization. Do not add unverifiable metrics
or personal assumptions to make the page feel richer.

## Current delivery boundary

Readable saved-preview tiles are implemented in `466c32b1`. The responsive manifest
above is a recommendation only. No source recapture, migration, arbitrary-script
replay or direct generated-document edit was performed in this audit. Native revision
and live acceptance await completion of the existing Google passkey handoff. The
solo design runtime and selected model are unchanged.
