<!--
version: 5
DRAFT — founder review pending (standing rule for prompt/rubric wording).

v2 (clone-fidelity F4.2, ruling R24-4) adds the ABM / seller-dominance section at the end. It is
in THIS artifact rather than in the ABM recipe because D-F7's rule is about where review
knowledge lives: both readers — the reviewer subagent and the orchestrator self-reviewing behind
the fast-loop flag — must judge an account page by the same words.

This file is THE clone-review rubric (founder ruling D-F7). It is read at prompt-composition
time by BOTH the web reviewer subagent and — behind the web lane's fast-loop flag — the
orchestrator self-reviewing in its place. There is no second copy: edit this file and both
readers change. Do not paste any of it into a prompt builder.

Everything below the marker line is what those readers receive, verbatim.
-->
--- rubric ---
CLONE-REVIEW RUBRIC (v5) — how a cloned or repaired page is judged.

This rubric is the same for every reviewer of this page, whoever that is. It is not a
style opinion; it is where the line sits between "different" and "broken".

SOFT — note it, do not block on it, do not spend a repair round on it:
- minor animation timing/easing or transition polish that does not affect the requested
  behavior, comprehension, accessibility or visual identity;
- sub-pixel spacing differences, a font rendering a hair wider, a shadow a shade softer;
- small measured differences that preserve source hierarchy and the requested fidelity.
  Large geometry/type/media differences or missing requested motion are not excused
  by compilation. A fallback may be usable while exact reproduction remains unmet.

STRICT — this is BROKEN and it is work, not taste:
- blank space: a band that renders nothing, or a screenful of nothing between bands;
- missing content: required or preserved content absent from the rendered result.
  For exact reproduction, compare with the visible original. For an authorized
  campaign adaptation, compare with the agreed argument and preservation scope;
  deliberately omitted or rewritten source content is not itself a defect;
- broken controls: a button, link or disclosure that does nothing, or throws.
  Captured JavaScript being absent explains the defect; it does not make a visible
  control an acceptable static fallback. Test the resulting state, not just whether
  a click can be dispatched. A linked panel must actually change its content. A
  deliberate static alternative removes the false controls and preserves the useful
  content; it does not satisfy an explicitly requested interaction.
  Check source-relative links against the generated site's actual routes. A captured
  booking/resource link that now points to a nonexistent local route is broken even
  if a different CTA on the page works;
- unusable height: a band far taller than anything visible in it — the reader drags
  through emptiness. This is the commonest clone defect and it is never acceptable at
  any repair rung;
- invisible elements: present in the markup, not visible to a reader;
- failed mobile behaviour: a band that collapses, disappears, or runs off the side of
  the screen at phone width;
- console errors ATTRIBUTED TO THE PAGE. A cloned band carries no scripts — the mint
  strips them — so the page's own console errors are real resource failures: an
  image, a font or a stylesheet that did not load. The preview shell we render
  through does run scripts of its own, and its errors are reported separately and
  are not the page's fault. Judge the page's; ignore the shell's.

STRICT — reader-facing content. Review the actual rendered words independently of
the plan's checklist. A clean layout does not excuse an unusable argument:
- Internal production instructions, import mechanics and research-audit commentary
  are not visitor copy. Keep those in the internal report. Convert an unknown into a
  useful fit question, without turning it into a fact: "Which reservation systems
  should the demo cover?" rather than "PMS is not evidenced; do not assume a vendor."
  Preserve material product limits, attribution and proof conditions the reader needs.
- The page must explain the product action and its relevance to the supplied reader,
  with useful evidence or evaluation material. A target name plus generic feature
  labels is not an account argument. Point to the visible explanation; do not accept
  a plan that merely says these needs are covered. Narrow unsupported propositions
  instead of filling the gaps with invented pains, outcomes or repeated disclaimers.

STRICT — brand coherence AFTER a repair. A repaired band is judged against the band it
replaced, on measurements, not on impressions:
- spacing and section rhythm — the same vertical breathing as its neighbours;
- density — the same amount of content in the same amount of room;
- typography — the same ramp, weights and case as the rest of the page;
- colors — the brand's own palette in the same allocation, never a near-miss;
- image treatment, proportion and content ORDER preserved from the original.
A repair that is tidier than the page it lives in is a failure of this rubric, not a win.

HOW TO READ THE GATE'S MEASUREMENTS:
- The behavioural walk MEASURED the page: it did not judge it. Numbers are evidence.
- Anything the walk could not observe is reported as not observed. That is not a pass.
  Say so in your critique rather than reporting the page as clean.
- A band the gate marked broken is broken. Do not argue with it from a screenshot; the
  measurement is of the rendered DOM and the screenshot is one moment of it.
- A band the gate did NOT mark is not thereby fine. The gate sees the six things it can
  measure; missing content, a dead control and a wrong-feeling band are yours to catch.
- The height and mobile measurements cover PINNED CLONED bands only — a draft repair or a
  composed section carries no fragment wrapper, so the gate cannot probe it and its
  coverage line in the review says how many bands went unmeasured. Those bands are
  entirely yours to judge from the captures.
- A DORMANT section's absence is CORRECT, never "missing content": the source site hides
  it, a human has not activated it, and a page without it matches the site a visitor
  actually sees. Flag its absence only if a human activated it and it still is not there.

WHAT TO DO ABOUT A BROKEN BAND — D-F6's ladder, in order, and say which rung you reached:
  1. reproduce the original experience with supported primitives;
  2. build an equivalent interaction serving the same storytelling purpose;
  3. a deliberate, compact static fallback, with the artificial height removed ENTIRELY.
Rung 1 is often unreachable — our interaction vocabulary is deliberately bounded — so
rungs 2 and 3 are the normal answer and a well-made rung-3 band is a good outcome.
Whatever the rung, the repair preserves content hierarchy and order, typography and
colors, image treatment, proportions and density, spacing, section rhythm, the
interaction's storytelling purpose, and the brand's character.

ON AN ABM (ACCOUNT) PAGE — the seller's page, addressed to one company. Everything above
still applies; these are the extra questions, and the first is the acceptance test:

  Would it still look like the seller's site without the target logo?

If the answer is no, the page has adopted the target's brand and that is BLOCKING. The page
renders in the SELLER's theme: their type, their palette, their spacing, their chrome. Judge:
- SELLER BRAND DOMINATES. The page reads as the seller's site addressed to this
  account. That does not require a navigation bar or a full homepage footer. A
  focused page may establish identity with genuine marks above the hero, preserving
  the seller's typography, palette, imagery and spacing throughout. Follow the
  requested placement and page intent; a library component is not a requirement.
- THE EXACT TARGET LOGO is the only target-brand element on the page, and it is the target's
  real published mark. A redrawn, recoloured, re-lettered or approximated logo is BLOCKING —
  it is the never-synthesize rule, and it is not a matter of taste. AN EMPTY LOGO SLOT IS
  CORRECT: we do not always hold a mark, and a header with the seller's mark alone is a clean
  header. Flag a placeholder, a grey box or the words "logo here". Do not invent
  a mark; when the brief explicitly requires the real target logo, its absence
  remains an unmet requirement rather than a fidelity pass.
- ONE RESTRAINED ACCENT at most from the target's palette. Two is a restyle. Zero is fine.
- CHROME AND LINKS MATCH THE CHOSEN INTENT. A focused single-conversion template
  uses campaign shells and a real primary destination. An approved native-site or
  resource journey can retain source navigation and useful secondary links. Judge
  deviation from that plan, dead controls or misleading destinations; do not fail
  a page merely because a real relevant resource link exists.
- NO RELATIONSHIP THAT DOES NOT EXIST. The framing is "Prepared for <account>". "Partner",
  "partnership", "customer", "trusted by <account>", a target logo in a logo wall, or a
  testimonial attributed to the target without evidence are BLOCKING: a target
  name alone supports none of those claims.
  The target's name belongs in the prepared-for line and in the copy written for them.
- NEW SECTIONS carry `abm_` section ids and obey the Brand Grammar Audit exactly as any other
  new section does. An unnamed new band is a review finding, not a defect in the page.

CLASSIFY HONESTLY. Blocking means the page cannot ship as it is — that is the STRICT list
above. Everything on the SOFT list is advisory: it belongs in the final summary, not in
another author round. Visual defects require a capture or measurement. Missing
source, claim, destination or playback evidence is a separately reported unverified
requirement. A named material gap prevents acceptance for that requested scope.
