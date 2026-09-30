This identity guide separates original company files, observed website presentation and provider candidates. It gives a designer usable source assets while keeping incomplete parts of the logo family visible.

## Logo family and background fit

| Placement | Available asset | Status and use |
| --- | --- | --- |
| Wordmark on light | Dark, transparent website SVG | Official original. Preserve aspect ratio and original lettering. |
| Wordmark on dark | Same website SVG with the footer’s white display treatment | Observed website usage. This is a rendering treatment, not a separately downloaded white master. |
| Icon on dark | Pale, transparent 512px website PNG | Official original; prefer this over the smaller provider version. |
| Icon on light | Dark icon in a 100px provider JPEG tile | Incomplete for transparent high-resolution placement. Request an official dark master. |

The website’s Apple touch icon and site icon are opaque square tiles. They are useful app identity references, but they must not replace the transparent assets in an ad lockup. The Brandfetch pale PNG uses palette transparency; the earlier analysis incorrectly described the viewer background as part of the image. File inspection corrected that error. [Website](https://www.conduit.ai/)

## Color and typography

The live website uses white as the main canvas, #29251E for body text, and #28241E for its dark primary buttons. Brandfetch also supplied #F3F1EC and #77D4FF; retain those as provider palette candidates rather than inventing a complete set of semantic UI tokens. A color being present does not establish its correct use for errors, focus rings or every campaign background.

The website CSS identifies Neue Montreal for body typography and Season Mix for the display face. It also declares fallbacks and other fonts. A fallback declaration is not evidence that Arial is Conduit’s primary brand font. Font files and licensing need to be handled by the existing platform ingestion pipeline before export. [Official stylesheet](https://www.conduit.ai/_next/static/chunks/171m6_plm0ner.css?dpl=dpl_5zNSTYuHzmG9DtT6CUng5Pms8gTY)

## How an agent should use this pack

Choose a slot by background contrast and use the original asset identity. For one-to-one ads, compose the seller and target-company marks as separate image layers; do not ask an image model to draw either logo. Preserve proportions, align optical height and allow deliberate space around the separator. The exact clear-space rule is not published in these captured sources and needs brand confirmation.

Website treatments may be reproduced only as explicitly recorded presentation instructions. Do not silently produce new logo files or declare missing variants approved. The standalone preview shows the observed reverse-wordmark treatment so a human can inspect it; the original SVG remains unchanged.

## Remaining gaps and next action

The four intended slots are now visible, but the pack is not four approved transparent masters. The light-background icon still needs an official transparent dark file. If server export cannot preserve the footer treatment, request a reverse wordmark master as well. Confirm spacing, palette roles and font permissions before campaign approval. Brand ingestion should keep these availability states separate from a successful provider HTTP response.
