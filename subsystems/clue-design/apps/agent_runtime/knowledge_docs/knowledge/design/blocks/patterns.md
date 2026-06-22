# Lumen DSL Vetted Block Catalog — Full-Artifact Compositions

These are complete, pre-proportioned **page** blocks. ASSEMBLE one of these for the
requested surface, then swap copy via the `#slot:` fixture lines — do not re-invent
proportions from primitives (that is what overcrowds designs and fails preflight on
`LUMV0810`/`LUMV0903`/`LUMV0904`). Every example below was personally run through
`.context/p02-validate.py` and returned `{"ok": true}` (the only warnings are
`LUMB0613`/`LUMB0614`, the platform-font-embedding warnings, which never fail a block).

Shared rules these blocks bake in (from the P0.2 spec §0–§5):

- **One clipped root `artboard` per page**, `s(fill,fill)`, background on its `fill(...)`. Never hardcode the root size.
- **Every personalizable text node is slotted** with a FIXED `s(W,…)` WIDTH sized for its worst_case, plus `wrap_text(true)` + a realistic `max_lines(N)`, and a `#slot:<key> sample(...) worst_case(...)` line under the page (the ONLY way fixtures attach). Use a **hug HEIGHT** (`s(W,hug)` / `s(fill,hug)`) so the box sizes to the actual lines and leaves no empty band — `max_lines(N)` still caps the line count. `text_fit` now uses the node's own line height, so hug heights validate for slotted nodes too (eyebrow/logo/name single-liners and headlines all hug). Non-personalized labels omit `slot(...)` and may use `hug`.
- **Centered labels use align(center) + hug height.** A label centered on BOTH axes by its parent (`al(…, x(c), y(c))` — a numeral in a circle chip, a stat numeral, a CTA button label) gets a standalone `align(center)` on the TEXT node so the glyph is centered (text-anchor=middle) INDEPENDENTLY of `style($type.x)`, plus a **hug height** so the parent's `y(c)` centers the actual glyph-tall box. Keep the label fill-width (`s(fill,hug) align(center)` for chip numerals/stat values AND CTA button labels) — `align(center)` centers the glyph inside that fill-width box; hug heights now validate for slotted nodes too (`text_fit` uses the node's own line height). NEVER use a hug WIDTH on a label (`s(hug,…)` is rejected by `LUMV0902`).
- **Width floors are large** (platform type is big). Calibrated facts used below: `$type.body` overflows a 499pt A4 column even for a 13-word sentence — **use `$type.body.small` for body copy at A4/postcard widths**. `$type.display` is too large for a 4-word headline even at 888pt wide / `max_lines(4)` — **use `$type.headline` for hero headlines**. A single over-wide word can blow `LUMV0810` at any height: at A4 width, "Recover **every** missed patient call." never fit; dropping a word to "Recover missed patient calls." (4 words) fits at `s(499,140) max_lines(2)`.
- **Content discipline = uncrowded.** One focal region; one CTA per artifact; headline 4-8 words `max_lines(2)`; subtitle 6-13 words `max_lines(3)`; benefit title ≤2 words `max_lines(1)` + description ≤12 words `max_lines(2)`; stat = one numeral + ≤2-word label. **Never 3 benefits across a portrait page — stack them vertically.** Smaller surfaces drop content rather than shrink it.

---

## Social square ad — header + hero + 3-up stat row + CTA + footer (1080×1080)

**When to use:** a square social/display ad (Instagram, LinkedIn square). The single
focal message with three proof stats and one CTA.

**When to use / Content budget:** `size(1080,1080,px)` → 1080×1080pt; `pad(96)` ⇒ 888pt
content column (~65% whitespace). Logo label + eyebrow in the header; hero headline 4-8
words `max_lines(2)` via `$type.headline` **stepped up to `font_size($type.size.7xl)` (80pt)**
at `s(888,hug)` — a 1080² canvas is far larger than A4, so the role's default 56 does NOT
dominate; the 7xl step makes the headline the clear focal point (80 vs the 48pt stats) while
the role still supplies weight/color (height hugs to the actual lines, `lh(1.04)` for the big
size). Subtitle ≤8 words `$type.body` `s(820,hug)` `max_lines(3)` (height hugs); three stats
each a `$type.stat` numeral `s(fill,hug)` + a ≤2-word `$type.body.small` label `s(270,hug)`;
one inverse-fill CTA `s(340,72)` whose fill-width label centers its glyph with `align(center)`
+ a hug height (`s(fill,hug)`). The URL caption hugs its height (`s(360,hug)`). **Distribution
(no dead bands):** the root is top-anchored (`y(s)`) with three children — a hug `header`, a
**`fill`-height `main` (`s(888,fill) y(c)`)** holding hero + stats, and a hug `footer`. `main`
absorbs all the vertical slack and centers hero + stats, so the header pins top, the footer is
pushed to the bottom, and the content sits centered in generous margin — NOT `y(sb)` with three
sparse bands (which strands each as a thin strip). Stat columns are fixed `s(270,…)` (270×3 + 2
gaps < 888), well above the ~160pt 2-word floor. Centered labels use align(center) + hug height;
text heights hug.

```text
page social_square size(1080,1080,px)
  artboard al(v, x(s), y(s), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.brand) clip(true)
    header al(h, x(sb), y(c), g($space.md), pad(0)) p(0,0) s(888,hug)
      brand al(h, x(s), y(c), g(12), pad(0)) p(0,0) s(360,hug)
        mark r p(0,0) s(40,40) fill($surface.inverse) rd($radius.badge)
        logo text "Insight Health" p(0,0) s(300,40) style($type.label) wrap_text(true) max_lines(1) slot(account.name)
      eyebrow text "FOR SPECIALTY CLINICS" p(0,0) s(420,36) style($type.eyebrow) wrap_text(true) max_lines(1) slot(campaign.eyebrow)
    main al(v, x(s), y(c), g($space.section), pad(0)) p(0,0) s(888,fill)
      hero al(v, x(s), g($space.stack.default), pad(0)) p(0,0) s(888,hug)
        headline text "Answer every patient call." p(0,0) s(888,hug) style($type.headline) font_size($type.size.7xl) lh(1.04) wrap_text(true) max_lines(2) slot(campaign.headline)
        subtitle text "Insight Health answers, qualifies, and books visits." p(0,0) s(820,hug) style($type.body) lh(1.4) wrap_text(true) max_lines(3) slot(offer.primary_message)
      stats al(h, x(sb), y(s), g($space.lg), pad(0)) p(0,0) s(888,hug)
        s1 al(v, x(s), g(4), pad(0)) p(0,0) s(270,hug)
          s1v text "92%" p(0,0) s(fill,hug) style($type.stat) max_lines(1)
          s1l text "calls answered" p(0,0) s(270,hug) style($type.body.small) lh(1.3) wrap_text(true) max_lines(2) slot(stat.1.label)
        s2 al(v, x(s), g(4), pad(0)) p(0,0) s(270,hug)
          s2v text "3x" p(0,0) s(fill,hug) style($type.stat) max_lines(1)
          s2l text "faster booking" p(0,0) s(270,hug) style($type.body.small) lh(1.3) wrap_text(true) max_lines(2) slot(stat.2.label)
        s3 al(v, x(s), g(4), pad(0)) p(0,0) s(270,hug)
          s3v text "24/7" p(0,0) s(fill,hug) style($type.stat) max_lines(1)
          s3l text "live coverage" p(0,0) s(270,hug) style($type.body.small) lh(1.3) wrap_text(true) max_lines(2) slot(stat.3.label)
    footer al(h, x(sb), y(c), g($space.md), pad(0)) p(0,0) s(888,hug)
      cta al(h, x(c), y(c), pad(18,36)) p(0,0) s(340,72) fill($surface.inverse) rd($radius.button)
        cta_text text "Book a Demo" p(0,0) s(fill,hug) style($type.cta) align(center) max_lines(1) slot(campaign.cta)
      url text "insighthealth.ai" p(0,0) s(360,hug) style($type.caption) wrap_text(true) max_lines(1) slot(account.url)
  #slot:account.name sample("Insight Health") worst_case("Insight Health Systems")
  #slot:campaign.eyebrow sample("FOR SPECIALTY CLINICS") worst_case("FOR SPECIALTY CLINICS")
  #slot:campaign.headline sample("Answer every patient call.") worst_case("Give your team their hours back.")
  #slot:offer.primary_message sample("Insight Health answers, qualifies, and books visits.") worst_case("Insight Health answers, qualifies, books the visit, and routes the rest.")
  #slot:stat.1.label sample("calls answered") worst_case("calls answered")
  #slot:stat.2.label sample("faster booking") worst_case("faster booking")
  #slot:stat.3.label sample("live coverage") worst_case("live coverage")
  #slot:campaign.cta sample("Book a Demo") worst_case("Book a Demo")
  #slot:account.url sample("insighthealth.ai") worst_case("insighthealth.ai")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Full-canvas poster — sparse big-canvas ad, distributed (1080×1080)

**When to use:** a LIGHT-content big-canvas ad — one focal message + CTA, no proof
stats. This is the template to reach for whenever content is sparse on a tall/large
canvas, so it does NOT end up as three stranded strips with dead bands. It is the
"poster idiom" from `knowledge/design/foundations` made concrete.

**Distribution (the whole point):** the root is **top-anchored** (`y(s)`), NOT `y(sb)`,
with three children — a hug `header` (brand lockup), a **`fill`-height `main`
(`s(888,fill) y(c)`)** carrying the focal block (kicker + big headline + subtitle), and
a hug `footer` (CTA + url). `main` absorbs ALL the vertical slack and centers its
content, so the header pins to the top, the footer is pushed to the bottom, and the
message sits centered in generous margin — no mid-page voids. Hero headline stepped to
`font_size($type.size.7xl)` (80) so it dominates the 1080 canvas (the role default 56
would not). `$type.body` subtitle at `s(820,hug)` (wide square hero column). Add a proof
row inside `main` only if you genuinely have stats — otherwise keep it sparse.

```text
page poster_square size(1080,1080,px)
  artboard al(v, x(s), y(s), g($space.section), pad(96)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    header al(h, x(s), y(c), g(12), pad(0)) p(0,0) s(888,hug)
      mark al(h, x(c), y(c), pad(0)) p(0,0) s(44,44) fill($surface.brand) rd($radius.badge)
        markt text "IH" p(0,0) s(fill,hug) align(center) style($type.eyebrow) max_lines(1)
      logo text "Insight Health AI" p(0,0) s(400,hug) style($type.label) wrap_text(true) max_lines(1) slot(account.name)
    main al(v, x(s), y(c), g($space.stack.default), pad(0)) p(0,0) s(888,fill)
      kicker text "PRODUCT LAUNCH" p(0,0) s(888,hug) style($type.eyebrow) wrap_text(true) max_lines(1) slot(campaign.eyebrow)
      headline text "Meet Magic-Doc." p(0,0) s(888,hug) style($type.headline) font_size($type.size.7xl) lh(1.04) wrap_text(true) max_lines(2) slot(campaign.headline)
      subtitle text "Automate healthcare document processing at one-tenth the cost." p(0,0) s(820,hug) style($type.body) lh(1.4) wrap_text(true) max_lines(3) slot(offer.primary_message)
    footer al(h, x(sb), y(c), g($space.md), pad(0)) p(0,0) s(888,hug)
      cta al(h, x(c), y(c), pad(18,36)) p(0,0) s(300,72) fill($surface.brand) rd($radius.button)
        cta_text text "Book a Demo" p(0,0) s(fill,hug) align(center) style($type.cta) max_lines(1) slot(campaign.cta)
      url text "insighthealth.ai" p(0,0) s(320,hug) style($type.caption) align(right) wrap_text(true) max_lines(1) slot(account.url)
  #slot:account.name sample("Insight Health AI") worst_case("Insight Health Systems")
  #slot:campaign.eyebrow sample("PRODUCT LAUNCH") worst_case("PRODUCT LAUNCH")
  #slot:campaign.headline sample("Meet Magic-Doc.") worst_case("Introducing Magic-Doc.")
  #slot:offer.primary_message sample("Automate healthcare document processing at one-tenth the cost.") worst_case("Automate healthcare document processing for clinics and hospitals at one-tenth the cost.")
  #slot:campaign.cta sample("Book a Demo") worst_case("Book a Demo")
  #slot:account.url sample("insighthealth.ai") worst_case("insighthealth.ai")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Image hero — full-bleed photo + scrim + headline, brand top / message bottom (1080×1350)

**When to use:** an **editorial hero/poster** where a real **photo** carries the message —
a case study, a brand story, a product-in-context shot. Reach for this **only when a photo
does real work** (see `knowledge/images/decide`); a clean typographic layout beats a
gratuitous stock image. The canonical "text over a hero photo" idiom.

**The scrim rule (non-negotiable):** a full-bleed `image` fills the clipped artboard, a
**dark scrim rect** (`fill($surface.inverse) o($opacity.scrim)` = 0.56) sits over it, and
**inverse-fill text** (`fill($text.inverse)`) sits over the scrim — so the headline stays
legible on a busy photo. **Declaration order is z-order:** image → scrim → content. Without
the scrim, text on a photo is illegible the moment the image is busy, and the imagery critic
gates it (legibility-over-image is a hard axis). When the copy can instead sit on its own
solid band, the split layout needs no scrim — see `knowledge/images/placement` Idiom B.

**The artboard declares `fill($surface.inverse)` — and that is load-bearing, not
decoration.** Brand tokens resolve **relative to their container's surface**: on a dark
artboard `$text.inverse` / `$type.*` ink resolves to **light** (white) so it reads over the
scrim; on a light `$surface.page` artboard the *same* tokens resolve **dark** and the
headline goes invisible against the dark photo. The dark fill is also the correct fallback
colour if the image ever fails to load. So a full-bleed-photo surface is a **dark surface** —
keep the artboard `$surface.inverse`.

**Placement is on the node, not the DSL line.** The `image` line carries only
`asset(hero_photo)` — its **`fit:cover` + focal point + alt** are set on the node's
AssetPlacement by the agent's `place_asset_in_node` tool (or the editor inspector), the same
op a human edit issues. **Aspect comes from the 1080×1350 frame**, so the photo is cropped to
fill, never stretched. Swap `hero_photo` for the generated/uploaded asset id.

**Distribution:** the `content` autolayout fills the frame at `y(sb)` (space-between) with
two children — a hug **brand** lockup and a hug **copy** block — so the brand pins to the
top, the message pins to the bottom, and the photo + scrim fill the band behind. Hero
headline ≤5 words `max_lines(2)` stepped to `font_size($type.size.6xl)` (64) so it dominates
the 1080 canvas; kicker ≤2 words; subtitle ≤8 words `max_lines(2)`; one inverse CTA whose
fill-width label centers its glyph with `align(center)` + a hug height. Centered labels use
align(center) + hug height; text heights hug.

```text
page hero_image size(1080,1350,px)
  artboard fr p(0,0) s(fill,fill) clip(true) fill($surface.inverse)
    photo image asset(hero_photo) p(0,0) s(1080,1350)
    scrim r p(0,0) s(1080,1350) fill($surface.inverse) o($opacity.scrim)
    content al(v, x(s), y(sb), g($space.section), pad(80)) p(0,0) s(1080,1350)
      brand al(h, x(s), y(c), g(12), pad(0)) p(0,0) s(920,hug)
        mark r p(0,0) s(40,40) fill($surface.accent) rd($radius.badge)
        logo text "Insight Health" p(0,0) s(360,hug) style($type.label) fill($text.inverse) wrap_text(true) max_lines(1) slot(account.name)
      copy al(v, x(s), g($space.stack.default), pad(0)) p(0,0) s(920,hug)
        kicker text "CASE STUDY" p(0,0) s(920,hug) style($type.eyebrow) fill($text.inverse) wrap_text(true) max_lines(1) slot(campaign.eyebrow)
        headline text "Faster triage, calmer clinics." p(0,0) s(920,hug) style($type.headline) font_size($type.size.6xl) lh(1.06) fill($text.inverse) wrap_text(true) max_lines(2) slot(campaign.headline)
        subtitle text "How Northside cut missed calls to near zero." p(0,0) s(820,hug) style($type.body) lh(1.4) fill($text.inverse) wrap_text(true) max_lines(2) slot(offer.primary_message)
        cta al(h, x(c), y(c), pad(18,36)) p(0,0) s(320,72) fill($surface.inverse) rd($radius.button)
          cta_text text "Read the story" p(0,0) s(fill,hug) style($type.cta) align(center) max_lines(1) slot(campaign.cta)
  #slot:account.name sample("Insight Health") worst_case("Insight Health Systems")
  #slot:campaign.eyebrow sample("CASE STUDY") worst_case("CASE STUDY")
  #slot:campaign.headline sample("Faster triage, calmer clinics.") worst_case("Faster triage, calmer clinics.")
  #slot:offer.primary_message sample("How Northside cut missed calls to near zero.") worst_case("How Northside cut missed calls to near zero.")
  #slot:campaign.cta sample("Read the story") worst_case("Read the story")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## A4 one-pager — header + hero + vertical 3-up benefit list + CTA footer (A4 portrait)

**When to use:** a printed/PDF one-pager (sell sheet, leave-behind). Header brand row,
a hero statement, three benefits, and a CTA footer.

**When to use / Content budget:** `preset(a4,portrait)` → 595×842pt; `pad(48)` ⇒ 499pt
content width and ~746pt of vertical room. **Stack the three benefits as full-width
rows — never 3 across on A4** (3×220pt of descriptions > 595pt page width ⇒ guaranteed
`LUMV0810`). Each benefit row = number chip `s(56,56)` + `g(20)` + a `s(423,hug)` text
column (56+20+423 = 499); the chip's numeral centers its glyph with `align(center)` + a hug
height (`s(fill,hug)`) so the chip's `x(c),y(c)` centers the actual glyph instead of a tall
box, and the title/description heights hug (`s(423,hug)`) so short copy reserves no empty
band. Hero headline ≤4 words at A4 width — `$type.headline` `s(499,hug) max_lines(2)`
("Recover missed patient calls."; note "Recover **every**…" does NOT fit at 499 — drop the
over-wide word; the headline height hugs to the actual lines). Lead uses
**`$type.body.small`** at `s(499,hug) max_lines(3)` (height hugs) because `$type.body`
overflows a 499pt column. Tight single-line labels hug their height too (eyebrow
`s(499,hug)`, logo `s(230,hug)`); the tag/contact captions hug (`s(209,hug)`/`s(219,hug)`).
**Distribution (no truncated bottom):** hero + benefit list are wrapped in a
**`fill`-height `main` (`s(499,fill) y(s)`)** between a hug `header` and a hug `footer`.
`main` absorbs the vertical slack and flows its content from the top, so the **footer
is pinned to the page bottom** (verified: footer bottom = 794 = page − pad) — the page
reads as a complete framed layout, NOT content stopping at 60% with an empty lower half.
Use `y(s)` (top-flow) for a multi-section sell-sheet like this; for a SPARSE single-block
portrait card, center the block instead (`main … y(c)`). The whole page is gapped with
`$space.stack.loose` between regions. (`LUMV0801` may appear as a non-fatal *warning* —
it does not fail the block; content fits within bounds.) Centered labels use align(center)
+ hug height; text heights hug.

```text
page onepager_a4 preset(a4,portrait)
  artboard al(v, x(s), g($space.stack.loose), pad(48)) p(0,0) s(fill,fill) fill($surface.page) clip(true)
    header al(h, x(sb), y(c), g($space.md), pad(0)) p(0,0) s(499,hug)
      brand al(h, x(s), y(c), g(10), pad(0)) p(0,0) s(280,hug)
        mark r p(0,0) s(32,32) fill($surface.brand) rd($radius.badge)
        logo text "Insight Health" p(0,0) s(230,hug) style($type.label) wrap_text(true) max_lines(1) slot(account.name)
      tag text "Intake, automated" p(0,0) s(209,hug) style($type.caption) wrap_text(true) max_lines(1) slot(account.tagline)
    main al(v, x(s), y(s), g($space.stack.loose), pad(0)) p(0,0) s(499,fill)
      hero al(v, x(s), g($space.stack.tight), pad(0)) p(0,0) s(499,hug)
        eyebrow text "FOR SPECIALTY CLINICS" p(0,0) s(499,hug) style($type.eyebrow) wrap_text(true) max_lines(1) slot(campaign.eyebrow)
        headline text "Recover missed patient calls." p(0,0) s(499,hug) style($type.headline) lh(1.12) wrap_text(true) max_lines(2) slot(campaign.headline)
        subtitle text "Insight Health answers, qualifies, and books visits for your front desk." p(0,0) s(499,hug) style($type.body.small) lh(1.4) wrap_text(true) max_lines(3) slot(offer.primary_message)
      list al(v, x(s), g($space.stack.default), pad(0)) p(0,0) s(499,hug)
        r1 al(h, x(s), y(s), g(20), pad(0)) p(0,0) s(499,hug)
          n1 al(h, x(c), y(c), pad(0)) p(0,0) s(56,56) fill($surface.brand.subtle) rd($radius.full)
            n1t text "1" p(0,0) s(fill,hug) style($type.subtitle) align(center) max_lines(1)
          t1 al(v, x(s), g(6), pad(0)) p(0,0) s(423,hug)
            t1t text "Faster intake" p(0,0) s(423,hug) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.1.title)
            t1d text "Answer and route every patient call in seconds, day or night." p(0,0) s(423,hug) style($type.body.small) lh(1.4) wrap_text(true) max_lines(2) slot(benefit.1.desc)
        r2 al(h, x(s), y(s), g(20), pad(0)) p(0,0) s(499,hug)
          n2 al(h, x(c), y(c), pad(0)) p(0,0) s(56,56) fill($surface.brand.subtle) rd($radius.full)
            n2t text "2" p(0,0) s(fill,hug) style($type.subtitle) align(center) max_lines(1)
          t2 al(v, x(s), g(6), pad(0)) p(0,0) s(423,hug)
            t2t text "Less busywork" p(0,0) s(423,hug) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.2.title)
            t2d text "Scheduling and follow-up reminders happen automatically." p(0,0) s(423,hug) style($type.body.small) lh(1.4) wrap_text(true) max_lines(2) slot(benefit.2.desc)
        r3 al(h, x(s), y(s), g(20), pad(0)) p(0,0) s(499,hug)
          n3 al(h, x(c), y(c), pad(0)) p(0,0) s(56,56) fill($surface.brand.subtle) rd($radius.full)
            n3t text "3" p(0,0) s(fill,hug) style($type.subtitle) align(center) max_lines(1)
          t3 al(v, x(s), g(6), pad(0)) p(0,0) s(423,hug)
            t3t text "Happier patients" p(0,0) s(423,hug) style($type.subtitle) lh(1.15) wrap_text(true) max_lines(1) slot(benefit.3.title)
            t3d text "Shorter waits and a clear next step on every call." p(0,0) s(423,hug) style($type.body.small) lh(1.4) wrap_text(true) max_lines(2) slot(benefit.3.desc)
    footer al(h, x(sb), y(c), g($space.md), pad(0)) p(0,0) s(499,hug)
      cta al(h, x(c), y(c), pad(16,32)) p(0,0) s(260,64) fill($surface.inverse) rd($radius.button)
        cta_text text "Book a Demo" p(0,0) s(fill,hug) style($type.cta) align(center) max_lines(1) slot(campaign.cta)
      contact text "hello@insighthealth.ai" p(0,0) s(219,hug) style($type.caption) wrap_text(true) max_lines(1) slot(account.contact)
  #slot:account.name sample("Insight Health") worst_case("Insight Health Systems")
  #slot:account.tagline sample("Intake, automated") worst_case("Intake, automated")
  #slot:campaign.eyebrow sample("FOR SPECIALTY CLINICS") worst_case("FOR SPECIALTY CLINICS")
  #slot:campaign.headline sample("Recover missed patient calls.") worst_case("Recover missed patient calls.")
  #slot:offer.primary_message sample("Insight Health answers, qualifies, and books visits for your front desk.") worst_case("Insight Health answers, qualifies, and books visits for your front desk.")
  #slot:benefit.1.title sample("Faster intake") worst_case("Faster intake")
  #slot:benefit.1.desc sample("Answer and route every patient call in seconds, day or night.") worst_case("Answer and route every patient call in seconds, day or night.")
  #slot:benefit.2.title sample("Less busywork") worst_case("Less busywork")
  #slot:benefit.2.desc sample("Scheduling and follow-up reminders happen automatically.") worst_case("Scheduling and follow-up reminders happen automatically.")
  #slot:benefit.3.title sample("Happier patients") worst_case("Happier patients")
  #slot:benefit.3.desc sample("Shorter waits and a clear next step on every call.") worst_case("Shorter waits and a clear next step on every call.")
  #slot:campaign.cta sample("Book a Demo") worst_case("Book a Demo")
  #slot:account.contact sample("hello@insighthealth.ai") worst_case("hello@insighthealth.ai")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614", "LUMV0801"] }
```

---

## Landscape flyer — left message + CTA, right stat panel (1200×628)

**When to use:** a wide digital flyer / banner (LinkedIn/Facebook landscape, email hero).
A horizontal split: the message and CTA on the left, a proof-stat card on the right.

**When to use / Content budget:** `size(1200,628,px)` → 1200×628pt; `pad(64,72)` (top/bottom
64, left/right 72). The root is a **row** (`al(h, x(sb), y(c))`) that vertically centers
two regions and pushes them to the ends. Left `message` column is `s(620,hug)`: eyebrow
(single-line `s(620,hug)`, height hugs) + headline (`$type.headline` **stepped to
`font_size($type.size.6xl)` (64pt)** `s(620,hug) max_lines(2)`, so it dominates the 48pt
panel stats; the wide-but-short 628 canvas wants a display-scale hero, height hugs to the
actual lines) + lead (`$type.body.small` `s(620,hug) max_lines(3)`, height
hugs — `$type.body` would overflow even this width at print scale) + CTA (fill-width label that
centers its glyph with `align(center)` + a hug height `s(fill,hug)`). Right `panel` is
a fixed `s(372,500)` `$surface.card` holding three stacked stats (`$type.stat` numeral
`s(292,hug)` + ≤2-word `$type.body.small` label `s(292,hug)` — both heights hug). The format
is short (628pt tall) so there is no room for a benefit list — keep it to message + stats +
one CTA. Centered labels use align(center) + hug height; text heights hug.

```text
page flyer_wide size(1200,628,px)
  artboard al(h, x(sb), y(c), g($space.section), pad(64,72)) p(0,0) s(fill,fill) fill($surface.brand) clip(true)
    message al(v, x(s), g($space.stack.default), pad(0)) p(0,0) s(620,hug)
      eyebrow text "FOR SPECIALTY CLINICS" p(0,0) s(620,hug) style($type.eyebrow) wrap_text(true) max_lines(1) slot(campaign.eyebrow)
      headline text "Answer every patient call." p(0,0) s(620,hug) style($type.headline) font_size($type.size.6xl) lh(1.06) wrap_text(true) max_lines(2) slot(campaign.headline)
      subtitle text "Insight Health answers, qualifies, and books visits for your front desk." p(0,0) s(620,hug) style($type.body.small) lh(1.4) wrap_text(true) max_lines(3) slot(offer.primary_message)
      cta al(h, x(c), y(c), pad(16,32)) p(0,0) s(300,68) fill($surface.inverse) rd($radius.button)
        cta_text text "Book a Demo" p(0,0) s(fill,hug) style($type.cta) align(center) max_lines(1) slot(campaign.cta)
    panel al(v, x(s), y(c), g($space.stack.loose), pad(40)) p(0,0) s(372,500) fill($surface.card) rd($radius.card)
      p1 al(v, x(s), g(2), pad(0)) p(0,0) s(292,hug)
        p1v text "92%" p(0,0) s(292,hug) style($type.stat) max_lines(1)
        p1l text "calls answered" p(0,0) s(292,hug) style($type.body.small) lh(1.3) wrap_text(true) max_lines(1) slot(stat.1.label)
      p2 al(v, x(s), g(2), pad(0)) p(0,0) s(292,hug)
        p2v text "3x" p(0,0) s(292,hug) style($type.stat) max_lines(1)
        p2l text "faster booking" p(0,0) s(292,hug) style($type.body.small) lh(1.3) wrap_text(true) max_lines(1) slot(stat.2.label)
      p3 al(v, x(s), g(2), pad(0)) p(0,0) s(292,hug)
        p3v text "24/7" p(0,0) s(292,hug) style($type.stat) max_lines(1)
        p3l text "live coverage" p(0,0) s(292,hug) style($type.body.small) lh(1.3) wrap_text(true) max_lines(1) slot(stat.3.label)
  #slot:campaign.eyebrow sample("FOR SPECIALTY CLINICS") worst_case("FOR SPECIALTY CLINICS")
  #slot:campaign.headline sample("Answer every patient call.") worst_case("Give your team their hours back.")
  #slot:offer.primary_message sample("Insight Health answers, qualifies, and books visits for your front desk.") worst_case("Insight Health answers, qualifies, and books visits for your front desk.")
  #slot:campaign.cta sample("Book a Demo") worst_case("Book a Demo")
  #slot:stat.1.label sample("calls answered") worst_case("calls answered")
  #slot:stat.2.label sample("faster booking") worst_case("faster booking")
  #slot:stat.3.label sample("live coverage") worst_case("live coverage")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Postcard — brand + recipient, headline, one line, CTA (6×4 in)

**When to use:** a print direct-mail postcard. The smallest surface — ruthless content
discipline: one short headline, one supporting sentence, one CTA, plus brand + recipient.

**When to use / Content budget:** `size(6,4,in)` → 432×288pt; `pad(32)` ⇒ 368pt content
width and only ~224pt of vertical room — so **drop content, do not shrink it**: no
benefit list, no stat row, no eyebrow. The root is `al(v, …, y(sb))` so the three bands
(brand row, message, CTA) spread top→bottom. Brand row pairs a logo (mark + `$type.label`,
name `s(180,hug)` — height hugs) with a personalized recipient (`$type.caption`, `s(140,hug)`
— width fits "Dr. Alexandra Carter", height hugs). Headline ≤3 words `$type.headline`
`s(368,hug) max_lines(2)` (height hugs to the actual lines); supporting line ≤10 words
`$type.body.small` `s(368,hug) max_lines(2)` (height hugs; `$type.body` overflows this narrow
column); CTA `s(240,52)` whose fill-width label centers its glyph with `align(center)` + a hug
height (`s(fill,hug)`) so the button fits the tight height. The widths are the calibrated
minimums for this surface; centered labels use align(center) + hug height; text heights hug.

```text
page postcard_6x4 size(6,4,in)
  artboard al(v, x(s), y(sb), g($space.stack.tight), pad(32)) p(0,0) s(fill,fill) fill($surface.brand) clip(true)
    brand al(h, x(sb), y(c), g($space.sm), pad(0)) p(0,0) s(368,hug)
      logo al(h, x(s), y(c), g(8), pad(0)) p(0,0) s(220,hug)
        mark r p(0,0) s(28,28) fill($surface.inverse) rd($radius.badge)
        name text "Insight Health" p(0,0) s(180,hug) style($type.label) wrap_text(true) max_lines(1) slot(account.name)
      recipient text "Dr. Alex Carter" p(0,0) s(140,hug) style($type.caption) wrap_text(true) max_lines(1) slot(contact.full_name)
    message al(v, x(s), g(8), pad(0)) p(0,0) s(368,hug)
      headline text "Recover missed calls." p(0,0) s(368,hug) style($type.headline) lh(1.1) wrap_text(true) max_lines(2) slot(campaign.headline)
      subtitle text "Insight Health books your patient visits, day or night." p(0,0) s(368,hug) style($type.body.small) lh(1.35) wrap_text(true) max_lines(2) slot(offer.primary_message)
    cta al(h, x(c), y(c), pad(12,28)) p(0,0) s(240,52) fill($surface.inverse) rd($radius.button)
      cta_text text "Book a Demo" p(0,0) s(fill,hug) style($type.cta) align(center) max_lines(1) slot(campaign.cta)
  #slot:account.name sample("Insight Health") worst_case("Insight Health")
  #slot:contact.full_name sample("Dr. Alex Carter") worst_case("Dr. Alexandra Carter")
  #slot:campaign.headline sample("Recover missed calls.") worst_case("Recover missed calls.")
  #slot:offer.primary_message sample("Insight Health books your patient visits, day or night.") worst_case("Insight Health books your patient visits, day or night.")
  #slot:campaign.cta sample("Book a Demo") worst_case("Book a Demo")
```

Validator proof:
```json
{ "ok": true, "stage": "preflight", "errors": [], "warnings": ["LUMB0613", "LUMB0614"] }
```

---

## Adapting these blocks (keep them valid)

- **Re-skin via slots only.** Edit the `#slot:` `sample`/`worst_case` lines; keep each
  slotted node's fixed `s(W,…)` WIDTH unless the worst_case grows — if it does, re-validate.
- **Centered labels use align(center) + hug height; text heights hug.** A label centered on
  both axes by its parent (`x(c),y(c)`) gets a standalone `align(center)` on the TEXT node so
  the glyph is centered, plus a hug height (`s(fill,hug) align(center)` for chip numerals/stat
  values AND CTA labels) so `y(c)` centers the glyph-tall box, not a dead zone. Slotted body
  text uses a hug height (`s(W,hug)`/`s(fill,hug)`) so short copy reserves no empty band — and
  `text_fit` now uses the node's own line height, so hug heights validate for slotted nodes too
  (eyebrow, logo/name, headlines all hug). Never use a `hug` WIDTH on a label (`LUMV0902`); keep
  it fill-width or fixed-width and let `align(center)` center the glyph.
- **Headline width trap.** At the narrower surfaces (A4 499pt, flyer 620pt, postcard
  368pt) a single over-wide word can overflow `LUMV0810` at any height. Shorten the
  headline (fewer/shorter words), do not just add height or `max_lines`.
- **Body copy at print widths uses `$type.body.small`, not `$type.body`.** `$type.body`
  overflows columns ≤ ~620pt. Reserve `$type.body` for the wide square hero (`s(820,…)`).
- **Hero headlines use `$type.headline`; step the SIZE per surface.** The role's default
  size (56) is tuned for A4 — keep it on A4/postcard. On a large canvas it does not
  dominate, so step the size with a token: `font_size($type.size.6xl)` (64) for a landscape
  flyer, `font_size($type.size.7xl)` (80) for a 1080² square. The role still gives
  weight/color; only the size changes, and it stays a fixed value (editor-safe). Do NOT
  switch to `$type.display` for this — it carries display *styling* and still can't fit a
  4-word line at 888 wide. The rule: **one element dominates; the hero reads visibly larger
  than any stat/secondary value** (see `knowledge/design/foundations`).
- **Do not add a third tier of content to the postcard or flyer.** They are short
  surfaces; the validator's `LUMV0801` bounds check will reject an extra band. Stay with
  one focal message + one secondary region + one CTA.
```
