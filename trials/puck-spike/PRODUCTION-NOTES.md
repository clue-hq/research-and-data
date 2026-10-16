# Production notes from the Puck spike

Things the spike showed must be handled before Puck pages go live. Each line says what was seen
and what to do.

## Page weight (founder: note for production, 2026-10-07)

1. **Duplicate clone CSS.**
   - **Seen:** each clone carries most of its site's stylesheet (90–220 KB), so a page's HTML is
     0.9–1.25 MB.
   - **Do:** at publish, de-duplicate rules shared across the page's clones into one stylesheet,
     keep per-clone rules scoped, and drop rules that match nothing in the published markup.
2. **Unused font faces.**
   - **Seen:** Garner's export carries 88 faces.
   - **Do:** at publish, ship only the faces the page's computed styles actually use, as WOFF2.
3. **React runtime on static pages.**
   - **Seen:** published pages load about 0.5 MB of Next/React runtime even though nothing on the
     page is interactive.
   - **Do:** publish as static HTML with no hydration; add small scripts only where a section
     needs behaviour (forms, tabs, video controls).
4. **Hero video.**
   - **Seen:** Garner's is 4.2 MB.
   - **Do:** serve it with a poster image, `preload="metadata"`, and a compressed rendition.

## Brand fidelity

5. **Kit gaps.**
   - **Seen:** kits leave some brand facts "unmapped" (Conduit's primary button colour, Garner's
     heading ink).
   - **Do:** brand ingestion measures them from the rendered clones and stores them in the kit
     with their source (see the measured-components plan in chat, 2026-10-07).
6. **Captured images have no descriptions.**
   - **Seen:** they carry none, so the wrong one was picked once.
   - **Do:** describe captured clone images at ingestion, as kit assets already are.

## Robustness

7. **Section props are not validated.**
   - **Do:** define every section's props once (Zod / Pydantic), derive Puck's fields and a JSON
     Schema from that, and validate every agent write.
8. **Wrapping each section.**
   - **Do:** wrap each section in an error boundary, because Puck renders nothing for an unknown
     type.
9. **Tailwind-built clones.**
   - **Seen:** Conduit is built with Tailwind, so its class names overlap ours. No collision was
     seen.
   - **Do:** keep the leak test in CI for every new brand.
10. **Puck is pre-1.0.**
    - **Do:** pin the version, and keep our own contract tests on editor behaviour (resolveData on
      load, undo history, pointer events).
