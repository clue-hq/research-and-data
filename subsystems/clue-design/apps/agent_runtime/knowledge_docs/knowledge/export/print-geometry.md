# Print geometry — bleed, trim, safe area (print W3 teaching)

When a document is destined for PHYSICAL PRINT (A4/Letter/physical-unit
pages, or the user says brochure/flyer/poster/print), the design must
survive CUTTING. Sheets are printed oversized and cut down to the trim
size; the blade lands within ±1mm of the trim line. Three rectangles
govern this:

- **Trim** = the page rect (0,0,w,h). The cut line — the finished size.
- **Bleed** = a rect EXTENDING the page (negative origin), typically 3mm
  (8.5pt) per side. Ink that must reach the cut edge has to be painted out
  to this line, or cutting tolerance exposes white paper slivers.
- **Safe area** = an inset rect, typically 5mm (14pt). Text and critical
  content stay inside it so the blade can never clip them.

## Authoring the geometry (DSL)

The page HEADER accepts only `preset(...)`/`size(...)` (anything else is
LUMD0204). Print geometry rides a **`#page:` modify line** — same block,
right after the page's children:

```text
page page_hero size(595,842,pt)
  wash rect p(-8.5,-8.5) s(612,859) fill($surface.inverse) bleed(true)
  headline text "…" p(40,60) s(515,120) style($type.display)
#page:page_hero bg(#0f172a) bleed(-8.5,-8.5,612,859) safe_area(14,14,567,814)
```

- `bleed(x,y,w,h)`: 4-arg page rect in page units — for 3mm on a W×H page:
  `bleed(-8.5,-8.5,W+17,H+17)`.
- `safe_area(x,y,w,h)`: the 5mm inset is `safe_area(14,14,W-28,H-28)`.
- `bg(paint)` sets the page background — it paints ACROSS the whole bleed
  box on print exports automatically (full-bleed correct).

## The rules that gate a print run (print-ready-v1)

Print-intent PDF exports return a `print_ready` report; a **fail** blocks
bulk runs. Author to pass it:

1. **Edge art extends to the bleed line.** Any fill that touches a trim
   edge and stops short of the bleed line = FAIL. Author edge-touching
   washes/bands at the bleed extent (e.g. `p(-8.5,…) s(W+17,…)`) and mark
   them `bleed(true)` (downgrades the LUMV0801 overflow error — declared
   intent, and on print exports this content IS required and exported).
2. **Bleed present** when the export includes bleed = FAIL if missing.
3. **Text inside the safe area** = warn. Keep copy inside `safe_area`.
4. Font fallbacks, sub-300-PPI images, dropped features, license
   violations fold in from export diagnostics (LUMS010x, LUME0220,
   LUMX0002, LUME0212).

## Semantics that changed with the print workstream

- OLD: "content outside the page is not exported." NOW: on a print export
  with bleed, content inside the BLEED BOX is exported (and for
  edge-touching fills, required). Content beyond the bleed box is still
  clipped.
- The server PDF is vector (LUME0427): live text, embedded fonts; crop
  marks and TrimBox/BleedBox are added by the export pipeline — never
  author marks as scene content on a page using THIS metadata route.
  ONE exception exists: when the user explicitly asks for bleed/crop
  marks baked into the design itself (a normal export should already be
  the press sheet), use `skills/print-bleed-marks` — that route bakes
  the sheet into scene content and keeps this page metadata UNSET. The
  two routes are mutually exclusive per page.
- Digital-only surfaces (social ads, LinkedIn) need NONE of this: no
  bleed, no safe area beyond taste margins. Do not add print geometry to
  digital documents.

## Multi-page print artifacts (brochures, booklets)

**Always author READER-ORDER single pages** (page 1, 2, 3, 4 …), each a
normal page at the finished trim size. Never author printer spreads,
2-up sheets, or fold arrangements — imposition (arranging pages onto
press sheets, e.g. a 4-pager onto one duplex 8×12 sheet folded to 4
pages) is a downstream EXPORT transform (`imposition: "booklet"` on the
export profile), never an authoring concern. A brochure request means N
reader pages; the export pipeline handles the folding math (front [N|1],
back [2|3], blanks padded to a multiple of 4, declared LUME0428).
Booklet imposition requires one uniform trim size across pages.

## CMYK for offset press (print W5 stage B)

Print-intent PDF profiles may add `"color": "cmyk"`: the export pipeline
separates the file to DeviceCMYK through a press ICC profile
(Ghostscript post-process; declared LUME0432, OutputIntent names the
target condition). Rules:

- **Print intent only.** `color: "cmyk"` on a preview-intent (digital
  distribution) PDF is a hard export error
  (`export.cmyk_requires_print_intent`) — electronic PDFs stay sRGB.
  Never set it unless the user's brief is an offset/press-critical run;
  digital presses handle the default sRGB PDF/X-4 fine.
- **Black stays crisp automatically.** Achromatic paints (pure #000
  text, hairline rules, neutral grays) separate to the K plate only —
  never author 4-color "black" text workarounds.
- **Rich black panels**: author a near-black fill (e.g. `#0a0a0f`) when
  a large dark panel should print as a deep rich black; the ICC builds
  the CMYK mix. Pure #000 fills stay K-only by design.
