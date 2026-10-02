# ARV2 sandbox sample — results (2026-08-25)

Pipeline: Exa discovery -> 7 parallel Exa deep calls (schema-bounded) -> claim conversion.
Account: Digestive Healthcare of Georgia (dossier answer key). Total provider cost: **$0.101**.
19 claims produced (step5_claims.json), every one carrying value + verbatim quote + source URL,
stamped per the ARV2 matrix (exa_research / tier 4 / llm_synthesis / unverified / tenant_private).

## Headline finding — the pipeline beat the dossier on freshness
- **Gaye Pennington RETIRED June 2026** ("celebrate the remarkable 26-year career of our CEO
  Gaye Pennington, who is embarking on a well-deserved retirement" — practice Facebook video).
- **Erika Noll is the new CEO** ("I currently serve as Chief Executive Officer of Digestive
  Healthcare of Georgia, a physician-owned independent GI practice with 23 board-certified
  physicians, 8 clinic locations, and 4 endoscopy centers" — her LinkedIn).
- The static dossier still names Pennington as CEO — a founders letter from it would have been
  addressed to a retiree. A new-in-seat CEO is also a classic buying-timing signal.

## Answer-key comparison
Matched: Epic EHR + Piedmont MyChart (with honest hosting uncertainty); independent physician-
owned P.C. (plus a NEW corroboration via EIN registry); 23 physicians / 8 named locations /
4 endoscopy centers; precertification department (better quote than the dossier, from the
new-patient-packet PDF); Kennesaw State BS Psychology + Central Michigan MS HCA (exact match);
25-year celebration (via Instagram). New: Tracy Lynn Smith, Privacy Officer (privacy-notice PDF).
Missed in this pass: the per-office fax lines (found the referring-physician form only); physician
officers (Yanda/Stewart) not in the leadership call; NPIs (registry tool's job). One defect: one
career_history row pairs a Facebook quote with a LinkedIn URL — exactly what the verify_links
audit skill exists to catch.

## Wire-contract lessons (now proven live)
- Exa outputSchema budget: **max 10 properties total, depth 2**, allowed keys only
  {type,enum,description,title} + per-type ({properties,required,additionalProperties:false} /
  {items,maxItems} / {maxLength} / {minimum,maximum}) — this is WHY the platform compiler bundles
  8 flat aliases. Violations 400 with no useful body.
- Body: {query, type: deep|deep-reasoning, numResults, systemPrompt, outputSchema, contents:
  {text:{maxCharacters<=10000}, highlights:{query,maxCharacters}}, stream:false}.
- Response: output.content is a DICT (not a JSON string); costDollars.total per call;
  account rate limit 10 req/s (429 with plain-text error).
- Deep calls returned in 3-12s at $0.012-0.021 each.
