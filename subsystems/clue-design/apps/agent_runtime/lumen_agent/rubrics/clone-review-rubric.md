<!--
version: 1
DRAFT — founder review pending (standing rule for prompt/rubric wording).

This file is THE clone-review rubric (founder ruling D-F7). It is read at prompt-composition
time by BOTH the web reviewer subagent and — behind the web lane's fast-loop flag — the
orchestrator self-reviewing in its place. There is no second copy: edit this file and both
readers change. Do not paste any of it into a prompt builder.

Everything below the marker line is what those readers receive, verbatim.
-->
--- rubric ---
CLONE-REVIEW RUBRIC (v1) — how a cloned or repaired page is judged.

This rubric is the same for every reviewer of this page, whoever that is. It is not a
style opinion; it is where the line sits between "different" and "broken".

SOFT — note it, do not block on it, do not spend a repair round on it:
- animation timing, easing, and anything that only moves;
- hover, focus and transition polish;
- sub-pixel spacing differences, a font rendering a hair wider, a shadow a shade softer;
- a band that is measurably different from the source capture but reads correctly.
  A measured difference is not a defect. The clone is a reconstruction, not a copy.

STRICT — this is BROKEN and it is work, not taste:
- blank space: a band that renders nothing, or a screenful of nothing between bands;
- missing content: something the original said that the page no longer says;
- broken controls: a button, link or disclosure that does nothing, or throws;
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

WHAT TO DO ABOUT A BROKEN BAND — D-F6's ladder, in order, and say which rung you reached:
  1. reproduce the original experience with supported primitives;
  2. build an equivalent interaction serving the same storytelling purpose;
  3. a deliberate, compact static fallback, with the artificial height removed ENTIRELY.
Rung 1 is often unreachable — our interaction vocabulary is deliberately bounded — so
rungs 2 and 3 are the normal answer and a well-made rung-3 band is a good outcome.
Whatever the rung, the repair preserves content hierarchy and order, typography and
colors, image treatment, proportions and density, spacing, section rhythm, the
interaction's storytelling purpose, and the brand's character.

CLASSIFY HONESTLY. Blocking means the page cannot ship as it is — that is the STRICT list
above. Everything on the SOFT list is advisory: it belongs in the final summary, not in
another author round. Never report an issue you cannot point at in a capture or a
measurement.
