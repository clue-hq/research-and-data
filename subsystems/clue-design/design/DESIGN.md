# DESIGN.md — Clue visual system, drawn from Cursor's design language

> **What this file is.** The single source of visual truth for our frontend, written from a
> first-hand extraction of cursor.com (5 marketing pages, rendered-browser capture,
> 2026-07-06 — see `design/research/RUN-REPORT.md`). Every hex, curve, and stack in the
> token tables below is **verbatim from Cursor's shipped CSS** unless marked *inferred* or
> *derived*. The token-first frontend brief (`packages/ui/src/tokens.css`,
> `tailwind-preset.ts`) seeds from §3–§7 of this file; the mapping to Clue semantic names is
> §10. Composition guidance is §8–§9.
>
> **What this file is not.** A license to copy hex into components. App code consumes
> semantic tokens only — this file feeds the token layer and nothing else.

---

## 1. The philosophy (what actually makes Cursor look like Cursor)

Ten load-bearing decisions, extracted from the shipped CSS and verified against the
captured screenshots. Understand these before touching a component; they are the taste,
the tables below are just the numbers.

1. **One ink, mixed — not a gray ramp.** There is no gray palette. Every neutral on the
   site is a single ink `#26251E` passed through `color-mix(in oklab, ink N%, transparent)`
   over paper: borders are ink at 2.5–20%, secondary text is ink at 60%, tertiary at 40%,
   hover washes are ink at 5–10%. This is why the UI feels *of one substance* — every line
   and label is literally diluted ink on the same paper. Consequence for us: define
   ink + paper + an **opacity ladder**, and forbid ad-hoc grays.
2. **Paper, not white.** The canvas is warm cream `#F7F7F4`; pure `#FFFFFF` appears only
   inside product mock chrome and focus offsets. Elevated surfaces get *slightly darker*
   (`#F2F1ED`), not lighter-with-shadow — depth points *into* the paper.
3. **No shadows. Hairlines and tone carry depth.** Zero box-shadows anywhere on the
   marketing surface. Separation = a hairline (ink @ 10%) or a one-step surface change.
   Hovers deepen tone (`#EBEAE5`) or raise the hairline to ink @ 20% — nothing floats.
4. **Ink is the primary action color, not the accent.** CTAs are **ink-filled pills**
   (`bg #26251E`, text `#F7F7F4`, hover `#3B3A33`); secondary actions are transparent
   pills with an ink @ 60% hairline. The orange is *never* the button fill.
5. **Accent scarcity is enforced structurally: accent == warning.** Cursor's orange
   `#F54E00` is literally the same variable as `--color-warning`. It appears as small
   marks — links-on-hover, highlights, focus, the occasional wordmark glyph — at full
   strength, or as 10%/25% mixes for tinted backgrounds. If orange starts feeling like a
   theme color rather than a signal, we've broken the system.
6. **Quiet, small, dense type — with one loud moment per page.** Marketing body sits at
   12–16px with generous line-height; section headings are a restrained 22–26px. Then once
   or twice per page: a 52–72px bold display line in sentence case **ending with a
   period** ("Try Cursor now.", "Get started with Cursor."). The period is the brand's
   confidence tick — keep it.
7. **Two typefaces, strict duties.** A gothic sans (CursorGothic) for *everything* prose
   and UI; a workhorse monospace (Berkeley Mono) for *everything* data — code, paths,
   numbers-in-tables, IDs, terminal chrome. The mono is a first-class citizen, not a
   code-block afterthought.
8. **Pastels are for the agent's work, never for chrome.** A dedicated 4-hue pastel set
   marks categories of agent activity (read `#9FBBE0`, search `#9FC9A2`, edit `#C0A8DD`,
   thinking `#DFA88F`) in timeline rows and annotations. They are muted, equal-luminance,
   and never used for buttons, links, or text.
9. **Painterly warmth against utilitarian precision.** Hero and section backdrops are
   classical landscape paintings (Hudson-River-School energy); floating on top are
   pixel-crisp product mocks with hairline chrome. The tension — romantic imagery,
   spartan UI — is the brand. For Clue: editorial/warm imagery is welcome as *backdrop*,
   never inside functional surfaces.
10. **Motion is fast, eased-out, and unremarkable.** 140–150ms default, 250ms "slow",
    `cubic-bezier(0, 0, .2, 1)` out, a spring-ish `cubic-bezier(.25, 1, .5, 1)` for the
    rare expressive move. Nothing bounces for attention.

---

## 2. Provenance & fidelity map

| Section | Fidelity |
|---|---|
| §3 surfaces/ink/borders/status/agent colors | **verbatim** from captured CSS custom props |
| §4 buttons, cards, product-mock colors | **verbatim** |
| §5 typography families/stacks/weights/real sizes | **verbatim** (evidence: 86 computed samples) |
| §6 spacing/radius | **inferred** from screenshots + 4-pt convention (no numeric evidence captured) |
| §7 motion | **verbatim** |
| dark colorway values | **partial evidence + derived** — flagged inline |

Raw material: `design/tokens/cursor-design-tokens.yaml` (294 custom props, 20 color
clusters, full type samples), `design/tokens/cursor-brand-kit.json` (engine-validated kit),
`design/assets/` (fonts, logos, 57 images, 5 full-page screenshots).

---

## 3. Core color tokens

### 3.1 Substance: paper + ink

| Token | Value | Cursor's var | Notes |
|---|---|---|---|
| `paper` (canvas) | `#F7F7F4` | `--color-bg` / `--color-theme-bg` | the app background; never pure white |
| `paper.elevated` | `#F2F1ED` | `--color-bg-elevated` / `--color-theme-card-hex` | cards, chrome, code blocks |
| `paper.hover` | `#EBEAE5` | `--color-bg-hover` / card-02 | hover/pressed wash for surfaces |
| `ink` | `#26251E` | `--color-theme-fg` / `--color-text-primary` | text, icons, primary buttons |
| `ink.soft` | `#3B3A33` | `--color-theme-fg-02` | button hover fill, strong secondary |
| `white` | `#FFFFFF` | `--color-white` | product-mock chrome + focus ring offset ONLY |

### 3.2 The ink opacity ladder (the system's engine)

All of these are `color-mix(in oklab, #26251E N%, transparent)` in Cursor's CSS. Implement
as rgb+alpha or color-mix — but implement as a *ladder*, one ink:

| Token | N | Duty |
|---|---|---|
| `ink.02` | 2.5% | faintest tint — table stripe, hairline on tinted cards |
| `ink.05` | 5% | subtle wash, card-03 overlay |
| `ink.10` | 10% | **`hairline`** — the default border everywhere (`--color-border`) |
| `ink.20` | 20% | `hairline.strong` — hover border, emphasized divider (`--color-border-bright`) |
| `ink.40` | 40% | `text.tertiary` — timestamps, placets, de-emphasized meta |
| `ink.50` | 50% | `text.mid` |
| `ink.60` | 60% | `text.secondary` / secondary-button border / `--color-info` |
| `ink.92` | 92% | product-surface body text |

**Rule:** need a new gray? You don't. Pick a rung. If a rung is genuinely missing, add it
to the ladder in `tokens.css` — never a one-off hex.

### 3.3 Accent + status (small, hot, meaningful)

| Token | Value | Cursor's var | Duty |
|---|---|---|---|
| `accent` | `#F54E00` | `--color-accent` == `--color-warning` | signals, highlights, focus ring, active marks. **Never button fill, never body text.** |
| `accent.wash` | accent @ 10% | `--color-accent-bg` | tinted background behind an accent signal |
| `accent.wash.strong` | accent @ 25% | `--color-accent-bg-strong` | selection tint |
| `accent.pressed` | `#D04200` | *(inferred: darkened accent; matches 05-design-system)* | the only accent fill allowed (pressed/AA-safe with white text) |
| `success` | `#1F8A65` | `--color-success` / ansi-green | positive status, inserted-diff tint @ 8% |
| `success.wash` | success @ 15% | `--color-success-bg` | |
| `error` | `#CF2D56` | `--color-error` / ansi-red | destructive, removed-diff tint @ 6% |
| `error.wash` | error @ 15% | `--color-error-bg` | |

### 3.4 Agent-work pastels (timeline set — verbatim)

Equal-weight, muted, only on agent motifs (tool rows, node dots, batch headers, chart
series). Never CTAs, never text, never chrome.

| Token | Value | Cursor's var | Category |
|---|---|---|---|
| `timeline.read` | `#9FBBE0` | `--color-timeline-read` | reading / retrieval |
| `timeline.grep` | `#9FC9A2` | `--color-timeline-grep` | search / research |
| `timeline.edit` | `#C0A8DD` | `--color-timeline-edit` | generation / editing |
| `timeline.thinking` | `#DFA88F` | `--color-timeline-thinking` | reasoning / planning |
| `timeline.done` | *(inferred)* muted gold in family, suggest `#D9C58B` | — | completion (Cursor's set has four; Clue needs `done` — keep it pastel-flat, label in ink) |

### 3.5 Card tone ladder (surfaces stack down, not up)

| Token | Value | Cursor's var |
|---|---|---|
| `card` | `#F2F1ED` | `--color-theme-card-hex` |
| `card.01` | `#F0EFEB` | card-01 |
| `card.02` | `#EBEAE5` | card-02 / hover |
| `card.03` | `#E6E5E0` | card-03 |
| `card.04` | `#E1E0DB` | card-04 |
| `card.warm` | `#F3EDE6` | card-warm (editorial/marketing moments) |

### 3.6 Product-surface colors (for editor-like/terminal-like UI in Clue)

`editor bg #F7F7F4 · chrome #F2F1ED · text ink@92% · text.sec ink@60% · text.tertiary
ink@40% · inserted-line success@8% · removed-line error@6% · ansi green #1F8A65 · ansi red
#CF2D56`. Our canvas/inspector/console surfaces should use exactly this recipe.

### 3.7 Dark colorway (flagged: partial evidence + derived)

Cursor ships a theme toggle; only fragments of its dark values were捕 captured (`#828282`
link-gray, `#EDECEC` light text). Until we re-capture with a dark-mode render, seed dark
from our pipeline's derived colorway (`cursor-brand-kit.json → tokens.colors.*.modes
["theme.dark"]`): near-black warm paper `#121210`-class surfaces, paper-toned text,
same accent/status hues brightened one step. **Mark every dark value `derived` in
tokens.css comments; replace with captured values when we do a dark-render pass.**

---

## 4. Buttons & interactive fills (verbatim)

| Role | Fill | Text | Border | Hover |
|---|---|---|---|---|
| **Primary (ink pill)** | `#26251E` | `#F7F7F4` | none | fill `#3B3A33`, text `#F7F7F4` |
| **Secondary (ghost pill)** | transparent | `#26251E` | ink @ 60% | fill picks up `paper.hover`, border to ink @ 100% |
| **Tertiary / link-button** | none | ink @ 60% | none | text to ink @ 100% |
| **Destructive** | use secondary + `error` text | — | error @ 60% | error.wash fill |

Shape: **full pill** (`border-radius: 9999px`) for standalone CTAs and nav actions;
small-radius rectangles for in-card/table buttons. One primary pill per surface — the
accent-scarcity rule applies to ink pills too.

---

## 5. Typography

### 5.1 Families (stacks verbatim from Cursor's CSS)

| Duty | Family | Stack | Files |
|---|---|---|---|
| Prose + UI | **CursorGothic** *(licensed to Cursor — for Clue substitute: Inter, or another neo-grotesque with similar tight apertures; keep the stack shape)* | `"CursorGothic", system-ui, "Helvetica Neue", Helvetica, Arial, sans-serif` | `design/assets/fonts/CursorGothic_*.woff2` (reference only) |
| Data + code | **Berkeley Mono** *(licensed — substitute: JetBrains Mono)* | `"berkeleyMono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace` | `design/assets/fonts/BerkeleyMono_*.woff2` (reference only) |
| Editorial prose (blog-class surfaces only) | EB Garamond + Lato | Google-hosted | optional for Clue |

⚠ CursorGothic and Berkeley Mono are commercial faces captured for *study*; do not ship
them. Inter + JetBrains Mono (per the frontend brief) reproduce the duties faithfully.

### 5.2 Weights in use
Sans: **400 and 700 only** (+ italics). No 500/600 in Cursor's marketing sans — emphasis
comes from size and ink strength, not medium weights. Mono: 400 (+ oblique).
*(Clue pragmatics: allow 500/600 for small UI labels where 700 is too loud at 11–12px —
that's our concession, mark it as such.)*

### 5.3 The real scale (captured computed sizes, px)

Marketing scale: `12 · 14 · 16 · 22 · 26 · 36 · 52 · 72`. Line-heights: display ≈ 1.05,
headings ≈ 1.2–1.3, body ≈ 1.5. Letter-spacing: slightly negative on display (−0.01 to
−0.02em), neutral elsewhere; small uppercase labels get +0.06–0.08em.

Named steps for tokens.css:

| Token | px | weight | lh | duty |
|---|---|---|---|---|
| `display-xl` | 72 | 700 | 1.02 | the one loud line; sentence case + terminal period |
| `display` | 52 | 700 | 1.05 | page hero |
| `headline` | 36 | 700 | 1.15 | section head |
| `title` | 26 | 400/700 | 1.25 | card/feature title |
| `subtitle` | 22 | 400 | 1.3 | supporting head |
| `body-lg` | 16 | 400 | 1.5 | primary reading |
| `body` | 14 | 400 | 1.5 | default UI text |
| `body-sm` | 12 | 400 | 1.45 | dense UI, tables |
| `caption` | 11 | 500 | 1.35 | meta, timestamps (ink @ 40–60%) |
| `label-uppercase` | 11 | 600 | 1.2 | eyebrows, chips; +0.07em tracking |
| `mono-body` | 13 | 400 | 1.5 | data, paths, numbers |

### 5.4 Voice rules
Sentence case everywhere (nav, buttons, headings). Display lines end with a period.
Numbers, metrics, IDs, filenames, and shortcuts render in mono. No title case, no all-caps
except `label-uppercase`.

---

## 6. Spacing, radius, hairlines *(inferred — no numeric capture; validated visually)*

- **Base unit 4px.** Scale: `4 · 8 · 12 · 16 · 20 · 24 · 32 · 40 · 48 · 64 · 96`.
  Section rhythm on marketing pages is generous (96–160px between bands); in-app surfaces
  run dense (8–16px paddings).
- **Radii:** `xs 4 · sm 6 · md 8 · lg 12 · pill 9999`. Cards read at 8–12px; chips at
  6–8px; CTAs are pills. Product-mock window chrome ≈ 10–12px. **Never invent a radius.**
- **Hairline = 1px** at `ink.10`. There is no 2px border anywhere; emphasis = darker rung
  (`ink.20`/`ink.60`), not thicker line.
- **Focus:** 2px ring in `accent`, offset 2px on `white`/`paper` — the one shadow-class
  exception allowed.

---

## 7. Motion (verbatim)

| Token | Value |
|---|---|
| `duration` | `140ms` (`--duration`) — hovers, fades, most transitions |
| `duration.default` | `150ms` (`--default-transition-duration`) |
| `duration.slow` | `250ms` — panel/accordion expansion |
| `ease.out` | `cubic-bezier(0, 0, .2, 1)` — the default |
| `ease.in-out` | `cubic-bezier(.4, 0, .2, 1)` — cross-fades |
| `ease.spring` | `cubic-bezier(.25, 1, .5, 1)` — rare expressive move (menu pop, toast) |

Respect `prefers-reduced-motion` globally. Nothing auto-animates in a loop on functional
surfaces.

---

## 8. Component motifs (observed on the captured pages — recipes, not code)

1. **Top nav:** paper bg, hairline bottom only on scroll; ink wordmark left; tiny 14px
   links (ink @ 60%, hover → ink); right side: ghost pill ("Contact sales") + ink pill
   ("Download"). Height ≈ 56px.
2. **Ink-pill CTA pair:** primary ink pill + ghost pill side by side, 8–12px gap — the
   canonical hero action group. Never two ink pills.
3. **Segmented control:** pill container in `card` tone; selected segment = `card.04`/
   deeper chip with ink text; unselected = ink @ 60%. No accent.
4. **Plan/feature cards:** flat `card` panels, radius ~10px, **no border, no shadow** —
   tone difference against paper IS the card. Title 22–26px, price with mono-ish figures,
   ✓-prefixed 14px feature list (checks in ink @ 60%). Hover: `card.02` + hairline.
5. **Chips/tags:** small (11–12px, 500–600), `card.02` fill, radius 6–8px; selected chip
   deepens two rungs; uppercase variant uses `label-uppercase` type.
6. **Accordion/FAQ rows:** no cards — hairline-separated rows on paper, 16px question,
   chevron in ink @ 40%; open state doesn't recolor, just expands (250ms ease-out).
7. **Logo wall:** partner logos as flat `card`-tone cells (or bare), logos rendered in
   ink/monochrome, never full color. Communicates "many, quietly".
8. **Stat blocks:** huge 700-weight figures (36–52px) in ink, 12px ink@60% captions —
   numbers speak, labels whisper. Figures in mono when tabular.
9. **Testimonial cards:** flat tone panels, 14px quote, avatar + name + role in
   caption/ink@60%. No quote marks styling, no italics.
10. **Changelog/blog rows:** date in mono ink@40% left, title 16px ink, hairline between
    rows. Editorial lists, not cards.
11. **Product-mock framing:** app screenshots live inside a drawn window — `card` chrome
    bar, 3 dots or traffic lights omitted/neutralized, hairline frame, radius 10–12px —
    floating over paper or painterly backdrop with **no drop shadow** (at most a 1px
    hairline + tone shift).
12. **Agent timeline rows** (the motif Clue cares most about): leading dot or bar in the
    category pastel (§3.4), tool name in mono 13px ink, description 14px ink@60%,
    timestamp mono ink@40%. Pastel appears ONLY in the dot/bar/line — the row itself
    stays paper/ink.
13. **Diff/console surfaces:** §3.6 recipe — inserted lines success@8% full-row wash,
    removed error@6%, line numbers ink@40% mono.
14. **Footer:** hairline top, 5 columns of 12–13px links (ink @ 60%, hover ink), legal
    line 11px ink@40%, theme + language switchers bottom-right as tiny ghost controls.

---

## 9. Imagery & iconography

- **Backdrops:** classical/painterly artwork (warm landscapes) for hero and section
  bands — `design/assets/images/0b0e25bcdae8_cursor-wallpaper.png` is the canonical
  reference. Treatment: full-bleed, slightly desaturated warmth; UI floats above it.
  For Clue, warm editorial imagery may back marketing/empty states — never functional
  panels.
- **Icons:** thin-stroke, geometric, ink-colored, 16px grid (Cursor ships a 16px icon
  font). Icons inherit text color (usually ink @ 60%); status icons may take status hues.
  No filled/duotone icon styles.
- **Partner/press logos:** always monochrome ink.
- **Illustrations of product:** real UI screenshots in window chrome, not abstract 3D.

---

## 10. Consumption contract — mapping to Clue semantic tokens

`packages/ui/src/tokens.css` seeds from this table (raw names here → Clue semantics from
the frontend brief / 05-design-system). App code uses ONLY the right-hand names.

| DESIGN.md (this file) | Clue semantic var |
|---|---|
| `paper` | `--bg-app` |
| `paper.elevated` / `card` | `--bg-card` |
| `card.02` | `--bg-chip` |
| `paper.hover` | `--bg-inset` |
| `ink` | `--text-primary` |
| `ink.92` → | `--text-body` |
| `ink.60` | `--text-muted` *(AA caveat: not below 14px)* |
| `ink.40` | `--text-disabled` |
| `paper` on ink | `--text-on-accent` (for ink-pill buttons) |
| `ink.10` | `--border-default` |
| `ink.02`/`ink.05` | `--border-soft` |
| `ink.20` | `--border-strong` |
| `accent #F54E00` | `--accent` |
| `accent.pressed #D04200` | `--accent-pressed` |
| `timeline.thinking #DFA88F` | `--agent-thinking` |
| `timeline.read #9FBBE0` | `--agent-read` |
| `timeline.grep #9FC9A2` | `--agent-research` |
| `timeline.edit #C0A8DD` | `--agent-generate` |
| `timeline.done (inferred)` | `--agent-done` |
| `error #CF2D56` | `--status-error` |
| `success #1F8A65` | `--status-success` |
| radii §6 | `--radius-xs…--radius-pill` |
| spacing §6 | `--space-xxs…--space-section` |
| §7 motion | duration/easing tokens |

Non-negotiables carried from the brief, restated with this file as authority:
- Hex lives in `tokens.css` only; components use semantic Tailwind classes / CSS vars.
- **No `shadow-*`** (focus ring exempt). Depth = tone + hairline (§1.3, §6).
- No arbitrary Tailwind values; missing step → add to the ladder first.
- Ink pill = the primary action; accent never fills buttons (§4); one primary per surface.
- Agent pastels only on agent motifs (§3.4, §8.12).
- Type tokens by name (§5.3); mono for data; sentence case; display lines end with ".".
- Charts/canvas import `@clue/ui/tokens.ts` — the pastels + status hues above are the
  chart palette; no other series colors.

---

## 11. Accessibility constraints (measured against these exact values)

- `accent #F54E00` on `paper`: ~3.2:1 — **fails AA for body text.** Accent is for ≥18px
  bold, icons, and non-text signals; accent-filled anything with white text must use
  `accent.pressed #D04200`.
- `ink.60` on paper ≈ 4.5:1 at best — treat as the floor; don't use below 14px
  (use `--text-body` for small readable text).
- `ink.40` is decorative/meta only — never for required-to-read content.
- Ink pill (`#F7F7F4` on `#26251E`): ~13:1 — always safe.
- Status text on wash backgrounds (e.g. error on error@15%): re-check per pairing; when in
  doubt put ink text next to a status *mark* instead of coloring the text.
- Timeline pastels are near-equal luminance by design — **never encode meaning by pastel
  alone**; pair with icon/label (also for the color-blind).

---

## 12. File map

```
design/
  DESIGN.md                        ← this file (source of visual truth)
  tokens/cursor-design-tokens.yaml ← full extraction: 294 custom props, clusters, type samples
  tokens/cursor-brand-kit.json     ← engine-validated kit (incl. derived dark colorway)
  research/RUN-REPORT.md           ← capture provenance + anomalies
  research/evidence.json           ← raw BrandEvidence (1,543 colors, 86 type samples)
  research/snapshots/*.json        ← replayable page captures (re-run without network)
  assets/screenshots/              ← 5 full-page references (landing/pricing/enterprise/students/blog)
  assets/fonts/                    ← CursorGothic + BerkeleyMono woff2 (study reference only)
  assets/images/ · assets/logos/   ← 57 images, 16 logo/icon files
```

*Regenerate:* `cd apps/api && LUMEN_CORE_HELPER=../../target/debug/lumen-api-helper
../../.venv/bin/python ../../design/research/run_cursor_ingest.py` (edit `PAGES` to add a
dark-mode render pass when we close the §3.7 gap).
