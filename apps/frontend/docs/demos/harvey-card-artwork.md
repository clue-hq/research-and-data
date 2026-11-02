# Harvey card artwork

Created with the built-in image-generation tool from the user's physical card photos. These are visual recording assets, not photographs of produced or delivered cards. The message sides reproduce the supplied handwriting visually; they are not an extracted font or exact glyph clone.

- Front: Harvey office photograph from https://www.harvey.ai/company, adapted into the supplied card layout.
- Original photo: https://cdn.sanity.io/images/07s0r5r6/production/480454f35fa5a4753563e59999f34adaa80a1dc1-5000x3333.jpg
- Logo: existing original Harvey wordmark; small mark: https://www.harvey.ai/icons/brand-favicon.png
- Footer approved by user: Harvey logo / AI for legal work.
- QR: generated deterministically using Segno, high error correction, 4-module quiet zone; destination https://www.harvey.ai/. It is a brand homepage QR, not a recipient microsite or tracked send.
- Message artworks are bound to exact note, signature and style values. An edit switches to the text preview so stale handwriting cannot be mistaken for approved content. New text needs new generated artwork.
- The V2 migration updates only the two local recording fixtures' card representation, including their simulated approval previews. It preserves message edits, financial state and fulfillment progress. Real approval history is not modified.

## Final generation prompts

### Front

Create a flat, print-ready front face of a premium 6 by 4 inch landscape gift card, 3:2 aspect ratio. Use the first reference photograph only as the physical card layout/material reference: warm natural cream paper, a large rectangular inset picture, clean generous border and a wider quiet footer. The source photo is rotated; output must be landscape and upright. REMOVE all Clue logos, Harvey logos, branding, all lettering, slogans and QR codes. No text anywhere on this front. Replace its orange abstract landscape with the second reference, the actual photograph of Harvey's wood-arch office. Preserve the recognizable exact office photograph and architecture, furniture and colors, do not invent a new office. Photo should occupy about 90% of card width, from 6% to 80% of its height, with straight corners. Underneath is a blank cream footer. Very subtle fine warm paper grain, soft warm ivory approximately #f5f0e4. Output only the card artwork filling the image edge to edge. Completely orthographic flat rectangle: no perspective, no table, no surrounding surface, no outer cast shadow, no rounded corners, no crop marks, no raised mockup. It will be used directly as an image on a card in a product UI.

### Jason message

Create the BACK face of a 6 x 4 inch landscape correspondence card, 3:2. The supplied photo shows a REAL PERSON'S HANDWRITING. It is sideways: rotate the lettering mentally to read it. Replicate THIS VERY SAME HAND precisely: loose, widely spaced, round single-stroke black ballpoint print letters, single-storey a, very thin irregular pressure, imperfect letter shapes and alignment, open round loops, irregular word spacing. It must feel like the exact writer from the supplied photograph wrote this new note by hand. NOT a typeset font, NOT Patrick Hand, NOT Caveat, NOT brush script, NOT cursive, NOT condensed thick letters. Match the actual pen strokes and spacing in the reference, especially 'I', 'the', 'and', 'Clue', and the lowercase shapes. Warm ivory matte uncoated stock approximately #faf7ed, subtle fine grain. Flat orthographic card artwork fills frame edge to edge, no table, no shadows, no perspective, no border. IMPORTANT remove all Clue branding and QR from reference. Leave blank space in upper-left 5%-12% x 4%-14% for a small logo that software will place later. Leave lower-right rectangle x82%-95%, y75%-96% COMPLETELY EMPTY for a real QR code to be overlaid. Do not draw a placeholder box or QR, do not write extra text. Start greeting at x7% y19%, main paragraphs below it. Lettering should be comfortably readable, about 23px if card were 600px wide; body fills area to y72%. Signature at bottom left x7%, y82%-91%. Preserve the exact words and punctuation below, set in the real person's loose handwriting, with natural line wrapping. No other text. TEXT:
Hi Jason,

A small addition to your workshop. I saw that you enjoy woodworking and thought this might earn a place on the bench.

Congrats on building Benesch’s innovation team. I’d love to compare notes on one legal workflow where Harvey could help, with your lawyers in control.

The Harvey team

### Hayley message

Create the BACK face of a 6 x 4 inch landscape correspondence card, 3:2. The supplied photo shows a REAL PERSON'S HANDWRITING. It is sideways: rotate the lettering mentally to read it. Replicate THIS VERY SAME HAND precisely: loose, widely spaced, round single-stroke black ballpoint print letters, single-storey a, very thin irregular pressure, imperfect letter shapes and alignment, open round loops, irregular word spacing. It must feel like the exact writer from the supplied photograph wrote this new note by hand. NOT a typeset font, NOT Patrick Hand, NOT Caveat, NOT brush script, NOT cursive, NOT condensed thick letters. Match the actual pen strokes and spacing in the reference, especially 'I', 'the', 'and', 'Clue', and the lowercase shapes. Warm ivory matte uncoated stock approximately #faf7ed, subtle fine grain. Flat orthographic card artwork fills frame edge to edge, no table, no shadows, no perspective, no border. IMPORTANT remove all Clue branding and QR from reference. Leave blank space in upper-left 5%-12% x 4%-14% for a small logo that software will place later. Leave lower-right rectangle x82%-95%, y75%-96% COMPLETELY EMPTY for a real QR code to be overlaid. Do not draw a placeholder box or QR, do not write extra text. Start greeting at x7% y19%, main paragraphs below it. Lettering should be comfortably readable, about 23px if card were 600px wide; body fills area to y72%. Signature at bottom left x7%, y82%-91%. Preserve the exact words and punctuation below, set in the real person's loose handwriting, with natural line wrapping. No other text. TEXT:
Hi Hayley,

A small desk companion for the ideas ahead. Congratulations on your knowledge and AI remit at Pinsent Masons.

I’d welcome a working session on one firm-knowledge workflow, with your lawyers reviewing every answer.

Shank Keshri
The Harvey team

