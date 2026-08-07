# Print proofing checklist (print W7)

The proof-export mode and the process around it. The one rule that cannot
be automated: **screens lie; paper doesn't.** Approve one physical proof,
then run the rest.

## The proof export

In the editor: enable **Print & bleed**, open the export panel, pick a PDF
print profile, and check **Proof export**. The PDF gains a margin with:

- **Crop marks** at the trim corners (where the blade lands),
- a **slug line** — `document · profile · page n/N · PROOF — not for
  production` (no date by design: exports stay byte-deterministic; write
  the date on the physical sheet when you sign it),
- an **sRGB control strip** — black, 75/50/25% grays, CMY and RGB
  primaries. On the printed proof, the gray patches must read neutral and
  the primaries distinct; a cast on the grays means the device or driver
  is color-managing incorrectly.

The export also carries the `print_ready` report (LUME0431 marks it a
proof). A proof with a failing report is a proof of the wrong thing — fix
the report first.

## The process (before a bulk run)

1. **Soft proof** on a color-calibrated monitor, at 100% zoom, using the
   printer's ICC profile if the shop provides one.
2. **Print-ready report is green** — bleed present, edge art reaching the
   bleed line, text inside the safe area, no font fallbacks, no dropped
   features, images ≥ 300 PPI.
3. **One physical proof** — ideally a contract proof from the shop, at
   minimum one sample off the actual press **on the actual stock**. Check:
   grays neutral on the control strip; cut line landing inside ink on all
   four edges (no white slivers); text clear of the trim; fold position
   (for booklets).
4. **Sign and date the physical proof.** Only then release the reader-order
   production PDF (never the proof file — the slug and marks are in it) for
   the full run.

## What the pipeline guarantees vs. what it can't

Guaranteed by machine: geometry (trim/bleed/safe boxes), the no-color-cutoff
chain, embedded fonts, PDF/X-4 declarations, deterministic output.
Not guaranteed: how ink behaves on a given stock, press color drift, fold
tolerance. That's what the physical proof is for.

## CMYK for offset runs (print W5 stage B)

For an offset shop that demands CMYK delivery, export with **print intent
+ CMYK (offset press)** — the pipeline separates the vector PDF through a
press ICC profile via Ghostscript and the OutputIntent names the exact
condition. Set `LUMEN_CMYK_ICC` on the API host to the shop's profile
(e.g. ISO Coated v2 / FOGRA39 from eci.org); without it the conversion
uses Ghostscript's default CMYK profile, which is fine for proofs but a
characterized shop profile is the right choice for brand-critical color.
Black text and rules separate to pure K automatically (no fuzzy 4-color
black); a large panel meant to print as *rich* black should be authored
near-black (e.g. `#0a0a0f`), since pure `#000` deliberately stays K-only.
Electronic-distribution (digital-intent) PDFs never convert — they stay
sRGB by design.
