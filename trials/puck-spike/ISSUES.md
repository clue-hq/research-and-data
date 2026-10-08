# Issues captured by the Puck spike (phase 1 and phase 2, to 2026-10-08)

Running the agent and the design system is how these were found. Each issue names where it
lives, the evidence, and its state. "Platform" means our product's data or ingestion; "agent"
means the page agent's behaviour against its skills; "harness" means this spike's own code.

## Platform: capture, ingestion and data

1. **Scroll-driven pages are captured blank (Alt Carbon).** All five Alt Carbon fragments come from
   the home page. The hero fragment holds most of the page, with about 1,500 px of empty space where
   a scroll-animated part of altcarbon.com should be. "How we work" was captured as a heading over
   blank space. The purple announcement bar ("How India Eradicated Polio…") was captured as its own
   section. Evidence: `shots/altcarbon-v0-1440.png` (all three usable clones on one page).
   *Open. Platform capture (the known JS-driven-page limit).*
2. **Alt Carbon's captured sections have no solid button.** The only filled control is in the nav,
   which is not captured as a usable section, so the button could not be measured from the clones.
   *Open (platform); the spike theme now falls back to the kit's button tokens, not yet run.*
3. **Garner's kit is stored as "Doctor Quality Analytics".** `kit.json` → `name`. Any surface that
   shows the kit name shows the wrong brand. *Open. Platform ingestion.*
4. **Captured images carry no descriptions.** In phase 1 a background glow was picked as if it
   were a product shot. Captured images get only alt text or a generic "from the section X".
   *Open. Platform capture (image descriptions).*
5. **Brand kits hold usage rules that generic sections can break.** Each kit's `brief.constraints`
   (8–10 rules) and `grammar_audit` say things like "surface.brand… never a section band", "do not
   alternate section backgrounds", "buttons are pills". Our brand sections offer a `brand` surface
   and `brandSubtle` bands, so on Alt Carbon they would break the brand's own rules unless the rules
   reach the agent. Until now `brand.md` did not include them. *Open; `brand.md` now lists them,
   not yet run.*
6. **Thin research for most accounts.** Atrium: the insights page is not written
   (`refused:insights_not_written`) and the overview holds one fact (838 employees). Volvo (Alt
   Carbon) has 4 claims. Only Syracuse, Dana.AI and Mitsubishi Heavy Industries have full research.
   *Open. Research coverage.*
7. **A customer logo row can imply a relationship.** Alt Carbon's "Trusted by the best" row shows
   Mitsubishi Corporation, a different company from Mitsubishi Heavy Industries. On an MHI page that
   reads as "you are already a customer". *Open. A judgement the agent must make; worth a test.*

## Agent: behaviour against its skills (runs a1, b1, c1)

8. **a1 and a2 (Garner × Syracuse): proof chosen without checking its conditions.** It used Nightingale
   ("kept PPO and HDHP options") and left out that Nightingale's results came with deductible and
   HRA changes, next to a card saying no plan-design change is required. It never ran `web_search`
   on Garner's site, so it did not find the Aon study. a2 (a second run on the current harness)
   made the same choice with the same caveat, so this is consistent behaviour, not chance.
   *Open. A failing case for the copy skill's proof rule (founder to decide the change).*
9. **a1: brand sections over clones without a recorded reason** (proof and offer), against the
   skill's "record why". b1 and c1 recorded their reasons. *Watch.*
10. **a1: unbounded reading.** It opened 18 of 21 clone cards and fetched the privacy and terms pages
    (up to 12k characters each) only to check footer links. b1 and c1 used one search for links.
    *Watch.*
11. **b1 (Conduit × Dana.AI): a known flaw shipped because of the one-re-render cap.** The review
    found "Dana.AI." alone on a line; the fix did not hold, and the cap stopped a second try. The
    agent reported it honestly. *Open (founder decision on the cap).*
12. **b1: the button says "Start a conversation" but goes to the demo-booking page.** The copy
    skill says a button says what happens. *Watch.*
13. **c1 (Conduit × Atrium): seller-proof search not limited to the seller's domain**
    (`include_domains` unset). *Watch.*
14. **c1: review missed an empty gap before the closing section and the closing band touching the
    footer.** *Watch.*
15. **a1: final report said "did not re-render" although it did.** *Watch (report accuracy).*

What went right in all three runs: zero Puck mistakes (every page valid at its first validation),
small edits rather than rewrites, plan before page, honest left-out lists, and c1 kept to the
name-only brief over the research.

## Harness: this spike's code

16. **Mobile screenshots reached the model about 132 px wide** (long side capped at 2000 px).
    *Fixed after a1: pieces that keep their width.*
17. **Lost prompt cache mid-run.** a1's last call lost the whole cache right after context clearing
    first cleared ($0.16 of $0.82), so clearing was turned off. **Correction:** a2 lost the cache at
    call 9 with clearing off ($0.13 for that call), so the misses look provider-side (xAI through
    OpenRouter), not caused by clearing. *Open: measure misses across runs; clearing stays off.*
18. **read_file showed 100 lines by default** and cut a skill. *Fixed: whole files.*
19. **The validator held judgement checks** (numbers in evidence, named people, notes wording).
    *Removed by founder ruling 2026-10-08; one destination stays blocking for now.*
20. **No check that an internal `/route` link goes to a real page; no nav links in the shell; the
    workspace holds one page.** *Open; needed before multi-page edits.*
21. **The one-re-render cap trades a known flaw for cost** (see 11). *Open.*
22. **A clone's own links pointed at pages of our site.** Captured links are mostly relative to the
    seller's site (Garner 24 of 28, Conduit 51 of 53, e.g. `/book-a-demo`); any the agent did not
    replace became broken links on our pages (a1, b1, c1 likely have some), and with several pages
    they could collide with our page names. *Fixed: the clone renderer makes untouched captured
    links absolute against the clone's source page; links the page writes stay ours.*
23. **Multi-page support for the agent.** *Built: `pages/<name>.json` beside `page.json`, nav links in
    the shell (and in the human shell editor), every page validated, links the page writes to
    `/<name>` must go to a page that exists, one destination checked across the whole site,
    `render_page(route)`, versions and restore cover every page. Skill and prompt text pending
    founder review.*

## Changes made for an Alt Carbon run, not yet run (uncommitted)

- `export/export_brand.py`: Alt Carbon added (kit `brand_kit_ing_28663a…`, version 1).
- `scripts/build-catalog.ts`: `brand.md` gains a kit-name column for surfaces and the kit's own
  rules (issue 5). This changes the input for every brand, so later runs of A–C are not directly
  comparable to a1, b1 and c1.
- `lib/theme.ts`: the kit's button when none was measured (issue 2).
- `agent/run_agent.py` and `agent/cases.json`: a case from a workspace with no design run (case D,
  Alt Carbon × Mitsubishi Heavy Industries, which has full research). No brief written.
