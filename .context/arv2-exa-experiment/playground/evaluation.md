# Exa deep-reasoning: report mode (R2 run) vs the founder's Playground runs — evaluation (2026-09-08)

## What was actually compared

The Playground runs did **not** use the claims-mode schema. Both responses came back as `output.content` =
a dict of prose sections named by the model (Probook 12 keys, Zafran 14 keys), and `results[]` carry
`highlights` but no `text` — so the Playground request used highlights, not `contents.text` at 10,000 chars.
This is a third mode: "free JSON sections, section-level grounding". The designed claims-mode run (one row per
assertion with `source_url` + verbatim `quote`) is still unrun; the bodies are in the parent folder.

Both modes cost $0.025 and retrieved 20 results.

## Measured

| | Probook report | Probook Playground | Zafran report | Zafran Playground |
| --- | ---: | ---: | ---: | ---: |
| output chars | 16,035 | 7,841 | 18,072 | 10,901 |
| quoted spans (≥3 words) | 58 | 38 | 56 | 35 |
| quotes verbatim on the cited page (live fetch, elision-aware) | 36 (62%) | 18 (47%) | 31 (55%) | 30 (86%) |
| inline URLs (per assertion) | 26 | **0** | 22 | **0** |
| grounding citations (per section, url+title, no snippet) | — | 17 urls / 12 sections | — | 25 urls / 13 sections |
| explicit NOT FOUND markers | 35 | 2 | 29 | 10 |
| section-6 tools individually marked NOT FOUND | 14/14 | 4 (rest in one list sentence) | — | 0 |
| answer-key leaf values present in the text | 11/22 | 9/22 | 18/64 | 20/64 |

Verbatim rates are lower bounds for both modes: LinkedIn and GlobeNewswire pages do not serve to a plain fetch,
and the Zafran report's people list ("Sanaz Yashar — Co-Founder & CEO") is name+title joined by an em-dash the
About page does not carry contiguously (formatting, not fabrication). Same handicap on both sides.

## Findings

1. **Section-level grounding is too coarse for the claim store.** The Playground output has no URL on any
   assertion; a claim would inherit 2–3 candidate URLs from its section's grounding and the link audit would
   have to guess which one. Report mode carries the URL inline on every assertion — that is what the audit
   and the display layer key on.
2. **The NOT FOUND discipline collapsed.** Report mode wrote 35/29 explicit NOT FOUND markers, one per tool in
   section 6. The Playground wrote 2/10, folded the tool list into one sentence (Probook) or dropped per-tool
   statements entirely (Zafran). Our section-6 and section-11 claims ("absent" lists, negatives born
   outreach_safe=false) come from exactly those markers.
3. **Prompt framing leaked back as evidence, without a URL to tell it apart.** Zafran Playground: "The supplied
   Ashby review found roughly 27 open requisitions", "AI Ark/Exa surfaced an automated workforce figure of 141",
   "Vari Kaur … identified in the supplied evidence as Head of Growth Marketing" — all from the query's
   ALREADY ESTABLISHED block, restated as findings. Probook Playground cites "Fortune reports" with no URL
   anywhere in the response. Report mode does this too in places, but every restatement carries a URL, so the
   audit catches it (that is the `second_hand_from_report` reason).
4. **Research quality per section is comparable, sometimes better.** Zafran Playground's acquisition item is the
   best-written section in either mode: DENIED by the company with quotes from both sides (CTech, Globes,
   Cisco's VP), correctly separating the confirmed strategic investment from the denied sale. Its Snir Havdala →
   NVIDIA departure with the quoted announcement, and the CTech ARR/burn claims marked UNRESOLVED, are exactly
   what the charter asks for. Probook Playground muddles "Cardinal/Redwood-related customer material" (two
   different customers) and treats the prompt's given facts as "supplied by the requester" — honest, but it
   means the deep call spent budget re-litigating what it was told instead of finding what it was not.
5. **Half the length, same coverage.** Answer-key coverage is within two keys either way, so the Playground
   text is denser per character but the report finds no fewer facts. What the report has extra is the explicit
   negative space (NOT FOUND, UNRESOLVED per item), which is our product, not filler.

## Verdict

On these two runs, a structured JSON output from the deep call is **worse for our pipeline** on the two
properties we depend on (a URL per assertion; explicit NOT FOUND per requested item), and equal on facts found.
The remaining open question is the designed claims-mode schema, which forces a `source_url` and `quote` per row
— that could restore both properties, or thin out the way the proof-of-concept saw with multi-property schemas.
Four API calls (~$0.10) with the bodies in the parent folder answer it.
