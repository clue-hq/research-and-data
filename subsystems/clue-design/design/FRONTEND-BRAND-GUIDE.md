# Clue frontend brand guide — for the Phase 3 (imaging) worktree

> **Who this is for.** Agents and humans building frontend surfaces on the main track
> (Phase 3: image-edit modal, Before/After compare gate, generation status, agent-chat
> polish) who need to ship UI in the locked Clue look — Cursor-derived, extracted live from
> cursor.com — WITHOUT waiting for the full editor restyle.
>
> **Standing relationship to other docs.** `design/DESIGN.md` is the design-system source
> of truth (philosophy, verbatim extraction, fidelity map). This guide is the
> *implementation contract*: the copyable token layer, the component vocabulary, and the
> adoption rules inside the existing editor shell. Where they disagree, DESIGN.md wins and
> this guide has a bug. The reference implementation is shipped and browser-verified at
> `apps/editor/src/app/brand/` (tokens.css · brand.css · the /brand pages).
>
> **How to get these files into the phase-3 worktree:**
> `git fetch origin agents/editing-roundtrip-v1 && git checkout FETCH_HEAD -- design/ apps/editor/src/app/brand/tokens.css apps/editor/src/app/brand/brand.css`

---

## 1. The system in one paragraph

Warm paper (`#F7F7F4`), one ink (`#26251E`), and **no gray palette at all** — every neutral
is ink at a percentage (borders at 2.5–20%, secondary text at 60%, meta at 40%). Depth is
tone + 1px hairline, **never a box-shadow** (focus ring is the sole exception). The primary
action is an **ink-filled pill**; the orange accent (`#F54E00`) is a *signal* (focus,
highlights, warnings — it literally shares a variable with `warning` upstream) and never a
button fill — accent fills use `#D04200` (AA with white). Type is quiet and small (12–16px
body) with one loud 700-weight display moment per page, sentence case, terminal period.
Mono is a first-class citizen for data. Agent-work pastels mark agent activity and nothing
else. Motion is 140/250ms ease-out.

## 2. Adoption model in the editor shell (the phase-3 question)

The editor's global `styles.css` (dark chrome + light panels, `--chrome-*`/`--panel-*`
vars) stays untouched until the frontend-revamp phase. The Cursor skin ships **scoped**:

1. **New, self-contained surfaces** (modals, overlays, full-page routes, the Before/After
   gate) mount inside a `className="brand-app"` wrapper and import the two CSS files. The
   wrapper carries the token scope, base typography, and focus ring — everything inside
   composes the §5 vocabulary. This is exactly how `/brand` shipped; copy that pattern.
2. **Retrofits inside existing panels** (e.g. a new row in AgentChatPanel): do NOT wrap
   panel fragments in `.brand-app` (you'd fork the panel's typography mid-surface). Instead
   use only the *values* that travel safely — the agent pastels (§4.5), spacing steps, and
   motion — via the panel's existing conventions, and leave the full conversion to the
   revamp. If you need more than that, the surface probably wants to be a self-contained
   overlay (case 1).
3. **Never** copy hex into components. If a value is missing, add a token to `tokens.css`
   first, then consume it. `tokens.css` is the only file in the brand layer allowed to
   contain literal colors. A rebrand must stay a one-file edit.

## 3. The token layer (copy verbatim)

`apps/editor/src/app/brand/tokens.css` — scoped under `.brand-app`. Reproduced here so this
guide is self-contained; if you copy from the file instead, prefer the file.

```css
@font-face {
  font-family: "InterVariable";
  src: url("/fonts/InterVariable.ttf") format("truetype-variations");
  font-weight: 100 900;
  font-display: swap;
}

.brand-app {
  /* -- substance: paper + ink -------------------------------------------- */
  --bg-app: #f7f7f4;            /* paper — the canvas; never pure white */
  --bg-card: #f2f1ed;           /* cards, chrome, code blocks */
  --bg-card-01: #f0efeb;
  --bg-chip: #ebeae5;           /* chips; also hover wash */
  --bg-inset: #ebeae5;
  --bg-card-03: #e6e5e0;
  --bg-card-04: #e1e0db;        /* selected-chip tone */
  --bg-card-warm: #f3ede6;      /* editorial moments only */
  --bg-white: #ffffff;          /* product-mock chrome + focus offset ONLY */

  /* -- the ink opacity ladder — the ONLY neutral system ------------------- */
  --ink: #26251e;
  --ink-soft: #3b3a33;          /* primary-button hover fill */
  --ink-02: rgba(38, 37, 30, 0.025);
  --ink-05: rgba(38, 37, 30, 0.05);
  --ink-10: rgba(38, 37, 30, 0.1);   /* THE hairline */
  --ink-20: rgba(38, 37, 30, 0.2);   /* strong hairline / hover border */
  --ink-40: rgba(38, 37, 30, 0.4);   /* disabled / decorative meta */
  --ink-50: rgba(38, 37, 30, 0.5);
  --ink-60: rgba(38, 37, 30, 0.6);   /* secondary text floor (≥14px) */
  --ink-92: rgba(38, 37, 30, 0.92);  /* body text on product surfaces */

  /* -- semantic text ------------------------------------------------------ */
  --text-primary: var(--ink);
  --text-body: var(--ink-92);
  --text-muted: var(--ink-60);   /* AA caveat: not below 14px */
  --text-mid: var(--ink-50);
  --text-disabled: var(--ink-40);
  --text-on-ink: #f7f7f4;

  /* -- borders: 1px hairlines, never 2px ---------------------------------- */
  --border-soft: var(--ink-05);
  --border-default: var(--ink-10);
  --border-strong: var(--ink-20);

  /* -- accent + status ----------------------------------------------------- */
  --accent: #f54e00;             /* signal only — never a button fill */
  --accent-pressed: #d04200;     /* the only accent FILL allowed (AA w/ white) */
  --accent-wash: rgba(245, 78, 0, 0.1);
  --accent-wash-strong: rgba(245, 78, 0, 0.25);
  --status-success: #1f8a65;
  --status-success-wash: rgba(31, 138, 101, 0.15);
  --status-error: #cf2d56;
  --status-error-wash: rgba(207, 45, 86, 0.15);

  /* -- agent-work pastels — agent motifs ONLY ------------------------------ */
  --agent-read: #9fbbe0;
  --agent-research: #9fc9a2;
  --agent-generate: #c0a8dd;
  --agent-thinking: #dfa88f;
  --agent-done: #d9c58b;

  /* -- buttons -------------------------------------------------------------- */
  --btn-primary-bg: var(--ink);
  --btn-primary-bg-hover: var(--ink-soft);
  --btn-primary-text: var(--text-on-ink);
  --btn-ghost-border: var(--ink-60);

  /* -- radius ----------------------------------------------------------------- */
  --radius-xs: 4px;  --radius-sm: 6px;  --radius-md: 8px;
  --radius-lg: 12px; --radius-pill: 9999px;

  /* -- spacing (4pt) ------------------------------------------------------------ */
  --space-xxs: 4px;  --space-xs: 8px;   --space-sm: 12px; --space-md: 16px;
  --space-lg: 24px;  --space-xl: 32px;  --space-2xl: 48px; --space-3xl: 64px;
  --space-section: 96px;

  /* -- typography ----------------------------------------------------------------- */
  --font-sans: "InterVariable", Inter, system-ui, "Helvetica Neue", Helvetica, Arial, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  --text-display: 52px;   --text-headline: 36px; --text-title: 26px;
  --text-subtitle: 22px;  --text-body-lg: 16px;  --text-body-size: 14px;
  --text-body-sm: 12px;   --text-caption: 11px;  --text-mono-size: 13px;

  /* -- motion (verbatim from cursor.com) --------------------------------------------- */
  --duration: 140ms;
  --duration-slow: 250ms;
  --ease-out: cubic-bezier(0, 0, 0.2, 1);
  --ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);
  --ease-spring: cubic-bezier(0.25, 1, 0.5, 1);

  /* -- focus: the one shadow-class exception ------------------------------------------- */
  --focus-ring: 0 0 0 2px var(--bg-white), 0 0 0 4px var(--accent);
}
```

Provenance/fidelity: colors, fonts stacks, motion = verbatim cursor.com extraction; radius
and spacing = inferred 4pt system (DESIGN.md §6); Inter/JetBrains Mono substitute the
licensed CursorGothic/Berkeley Mono (§DESIGN.md 5.1 — do not ship the originals).

## 4. Usage rules (the ones reviewers should enforce)

### 4.1 Color
- Need a gray? **You don't.** Pick an ink rung. New rung → tokens.css first.
- `--accent` colors *marks*: focus ring, active indicator, draft-status wash, a highlighted
  glyph. It never fills a button, never colors body text (3.2:1 on paper — fails AA).
  If something accent-colored must carry white text, use `--accent-pressed`.
- Status colors pair with washes (`--status-error` text/icon on `--status-error-wash`),
  or sit as marks next to ink text. Don't color whole sentences.
- Pure white only inside product-mock chrome and the focus-ring offset.

### 4.2 Depth & borders
- **`box-shadow` is banned** except `--focus-ring` on `:focus-visible`. Elevation =
  one-step tone change (`--bg-card` → `--bg-chip`) and/or a hairline.
- Hairlines are always 1px. Emphasis = darker rung (`--border-strong`), never thicker.
- Overlays scrim with `--ink-60`, panel on `--bg-app` with a `--border-default` hairline
  (see `.lightbox-overlay`/`.lightbox-panel` in brand.css).

### 4.3 Type
- Sentence case everywhere — nav, buttons, headings, labels. Display lines end with a
  period ("Review the changes."). No title case; caps only via the eyebrow/uppercase-chip
  styles (11px, +0.07em).
- One `.display`/`.headline` moment per surface, maximum. Section heads are `.title`
  (26px) — we shipped 36px section heads and demoted them on review; don't reintroduce.
- **Mono for data**: hex values, node ids, file names, sizes, coordinates, shortcut keys,
  model names. If a human might copy it, it's mono.
- `--text-muted` never below 14px (AA); below that use `--text-body` or promote the size.

### 4.4 Buttons & actions
- Primary = ink pill. **One per surface.** Secondary = ghost pill (transparent, ink@60%
  hairline). Tertiary = quiet text button. Destructive = ghost with error color + wash
  hover. Never two ink pills side by side; never an orange-filled button.
- Pills for standalone CTAs; small-radius (`--radius-md`) buttons only inside dense
  rows/tables.

### 4.5 Agent pastels (phase-3 cares most about this)
- The five `--agent-*` pastels mark **categories of agent work**: leading dots/bars on
  tool rows, node tints, batch headers, chart series. Mapping: read/retrieval →
  `--agent-read`, search/research → `--agent-research`, generation/editing →
  `--agent-generate`, reasoning/planning → `--agent-thinking`, completion → `--agent-done`.
- The pastel appears ONLY in the dot/bar/tint — the row's text stays ink, the row's
  background stays paper/card. Never pastel text, never pastel buttons, never pastel as
  decoration on non-agent chrome.
- Pastels are near-equal luminance by design: **never encode meaning by color alone** —
  always pair with an icon or label.

### 4.6 Motion & focus
- Hover/fade = `--duration` + `--ease-out`. Expansion (accordion, panel) =
  `--duration-slow`. `--ease-spring` only for one expressive move per surface (toast,
  menu pop). Respect `prefers-reduced-motion` (the `.brand-app` block already does).
- Every interactive element gets the focus ring via `:focus-visible` (free inside
  `.brand-app`).

## 5. Component vocabulary (shipped classes — compose, don't reinvent)

All in `apps/editor/src/app/brand/brand.css`, browser-verified on the /brand pages.
Layout-only additions are fine (prefix per feature, e.g. `.imgedit-*`); new *visual*
patterns go into brand.css only if two surfaces need them.

| Class | What it is |
|---|---|
| `.brand-app` | scope wrapper: paper bg, ink text, sans stack, focus ring |
| `.btn` + `.btn-primary/.btn-ghost/.btn-quiet/.btn-danger/.btn-sm` | the §4.4 action set |
| `.brand-card` (+`.is-clickable`) | tone card, hover deepens + hairline — no shadow |
| `.chip` (+`.is-selected`, `.is-uppercase`) | tags, filters, suggestions |
| `.status-pill` (+`.is-approved/.is-draft/.is-error`) | state pills w/ washes |
| `.display/.headline/.title/.subtitle/.eyebrow/.caption/.mono` | the type roles |
| `.brand-section` + `.brand-section-head` | page section rhythm |
| `.hairline-list` | hairline-separated rows (changelog/FAQ/job lists) |
| `.field` + `.field-label`, scoped `input/textarea/select` | forms (white field on paper, hairline, no shadow) |
| `.swatch` (+`.is-large`), `.ramp-row` | color presentation |
| `.dot` | 8px agent/status dot (pair with `--agent-*`) |
| `.brand-table` | quiet data table (muted th, hairline rows) |
| `.diag-list` | diagnostics rows w/ severity-colored mono codes |
| `.progress-track` + `.progress-fill`, `.stage-line` | staged progress (ink fill on chip track) |
| `.dropzone` | dashed intake target (hide native file inputs inside it) |
| `.lightbox-overlay` + `.lightbox-panel` | modal/lightbox shell (ink@60% scrim) |
| `.grid-cards`, `.asset-thumb` | media grids (4:3 thumb wells on card tone) |

## 6. Phase-3 surface recipes

- **Image-edit modal (3b):** `.lightbox-overlay`/`.lightbox-panel` shell; left = image on
  `--bg-card` well; right rail 320px behind a hairline with `.field` prompt textarea, ink
  pill "Apply edit", ghost "Remove background". While applying: `.stage-line` +
  progress-track, panel locked (moda's pattern, our skin).
- **Before/After accept gate:** two `.asset-thumb` wells labeled with `.eyebrow` "Before"
  / "After" (or a compare slider later); action row = ink pill **Accept**, ghost
  **Reject**, quiet **Save as new**. One ink pill — Accept is the primary, period.
- **Generation status in chat:** tool rows as §4.5 — `.dot` in the category pastel +
  tool name `.mono` 13px + description `--text-muted` + timestamp `.caption .mono`.
  "Design reviewed"-class step ticks are `.status-pill is-approved`.
- **Per-turn Compare | Revert:** quiet text buttons under the agent message, hairline-
  separated; never pills (they'd compete with real CTAs).
- **Errors:** inline `.status-pill is-error` next to the thing that failed + a ghost
  retry. No red banners across the surface, no toasts for recoverable states.

## 7. PR checklist (copy into review)

- [ ] Zero literal colors / `rgb(`/`#hex` outside `tokens.css`
- [ ] Zero `box-shadow` except the focus ring
- [ ] No invented radii/spacing/font sizes — token steps only
- [ ] One primary (ink-pill) action per surface; accent never a fill
- [ ] Agent pastels only on agent motifs, always paired with icon/label
- [ ] Data renders in `.mono`; sentence case; muted text ≥14px
- [ ] Motion uses the duration/easing tokens; reduced-motion respected
- [ ] New visual patterns added to brand.css (shared) not feature CSS (one-off)

## 8. File map & provenance

```
design/DESIGN.md                     source of truth (philosophy + extraction + fidelity map)
design/FRONTEND-BRAND-GUIDE.md       this file (implementation contract)
design/tokens/cursor-design-tokens.yaml  raw extraction (294 custom props, clusters, type samples)
apps/editor/src/app/brand/tokens.css     THE token layer (copy this, not the YAML)
apps/editor/src/app/brand/brand.css      component vocabulary (reference implementation)
apps/editor/src/app/brand/…              /brand pages — living examples, browser-verified
.context/slice4/browser-e2e/             screenshots of the shipped look (local, gitignored)
```

Known gaps (don't guess — flag): dark mode for this skin is unshipped (DESIGN.md §3.7 —
dark values exist as *derived* data in the kit JSON only); the editor-shell restyle is a
separate future phase; Storybook/`packages/ui` extraction happens with the monorepo work
(the token names here already match the token-first frontend brief's `--bg-app`/`--accent`
/`--agent-*` semantics, so that migration is a file move, not a rename).
