# Brilliant — Reverse-Engineering Report

**Subject:** `Brilliant` (bundle id `design.brilliant`), a Flutter/Dart macOS design tool with an agent-authored, line-based design language ("Blueprint") and a generative design-system compiler.
**Version analyzed:** `0.1.0.22` (`CFBundleShortVersionString`), `v0.1.0-beta.20`-era knowledge bundle.
**Date:** 2026-06-04
**Scope:** Application architecture, the Blueprint grammar/DSL, and the compiler/runtime — reconstructed from the shipped app package, the bundled assets, the production knowledge corpus, and prior deep-research synthesis.

---

## 1. Executive summary

Brilliant is a **single-binary Flutter desktop application** built around three tightly-coupled subsystems:

1. **Blueprint** — a terse, indentation-structured, one-element-per-line design language. It is the serialization format on disk (`.design` files), the wire format the AI agent emits (`<objects>` streaming blocks), and the in-memory authoring representation. A real compiler sits behind it: a normalize → parse → validate → interpret → lint pipeline implemented with the **petitparser** combinator library, with structured diagnostics and partial-application error recovery.

2. **A generative design-system compiler (v3)** — design tokens are not hand-listed; they are *generated* from a handful of seed values by five generators (`color`, `number`, `boldness`, `tshirt`, `looseness`). A human-authored `Styles/default.styles` file is compiled to a `.gen.yaml` catalog. Colors are computed in **OKLCH** space; semantic roles ("presence ramp", "t-shirt scale") map onto primitive stops; and every token re-resolves under a matrix of **modes** (theme/density/accessibility).

3. **An embedded multi-agent AI layer** — an MCP tool surface (`init`, `create_html`, `create_modify_elements`, `get_knowledge`, `find_elements`, `execute_commands`, `export`, `generate_image/svg`, `vectorize_image`, `plan_agents`/`spawn_agent`, `load_mcp_server`) backed by multiple LLM providers (Claude CLI, Anthropic/OpenAI/Google/OpenRouter HTTP, BYOK), a session model, sub-agent fan-out, conversation compaction, and a screenshot-driven self-review loop.

The engineering is unusually coherent: **one language** does triple duty (disk, wire, authoring), the design system is a *small program* rather than a token dump, and the AI agent is a first-class client of the same compiler a human uses. The main risks are the inherent fragility of a whitespace-significant line language under LLM authorship, an idiosyncratic 8-digit hex color convention (`#AARRGGBB`, not CSS), and heavy reliance on a large opaque AOT binary whose exact parser productions cannot be read directly.

> **Confidence & honesty note.** The application ships as an **AOT-compiled (native machine-code) Dart binary**, so the literal parser productions and method bodies are *not* directly readable. Every structural claim below is grounded in one of: (a) the self-documenting grammar header inside the shipped `.design` sample, (b) the production knowledge markdown bundled in the app, (c) class/method/diagnostic **string-table symbols** recovered from the binary, or (d) the prior research synthesis. Where a claim is inference rather than direct evidence, it is marked **[inferred]**. Symbol names quoted as `Class|method` are verbatim from the binary string table.

---

## 2. Methodology & evidence base

### 2.1 What was examined

| Artifact | Path (in package) | What it gave us |
|---|---|---|
| App metadata | `Contents/Info.plist` | Version `0.1.0.22`, `FLTEnableImpeller=true`, `brilliant://` URL scheme, min macOS 14.0 |
| AOT binary | `Contents/Frameworks/App.framework/Versions/A/App` | 64 MB universal (x86_64 + arm64) Dart AOT image; **124,900** extracted strings — class names, method symbols, diagnostics |
| `.design` sample | `…/flutter_assets/assets/getting-started/Getting started.design` | **Self-documenting grammar header** — the authoritative serialization spec |
| Playground transcripts | `…/flutter_assets/assets/playground/*.jsonl` | Agent conversation logs (`user_message`/tool events) |
| CodeMirror bundle | `…/flutter_assets/assets/codemirror/dist/editor.bundle.js` | Generic editor (1 MB) — **not** the Blueprint grammar; only `@codemirror/state` primitives |
| Knowledge corpus | `Contents/Resources/.claude-prod/**` + `brilliant/knowledge/**` | Agent-facing docs: `blueprint/core.md`, `layout.md`, `directives.md`, `design-systems/*`, `reference/ai.md` |
| Research synthesis | `research/brilliant-design/**` | Prior public-source mapping; `v3-design-spec.md`; open questions |

### 2.2 Methods

String-table mining of the AOT image (`strings -n 6` → 124.9k lines), then targeted `grep` for: compiler class/method symbols (`Blueprint*`, `*Catalog`, `DesignSystem*`), petitparser package paths, diagnostic/error literals, the design-system generator emit/role functions, the auto-layout extension methods, the MCP tool descriptions, and the LLM provider classes. Cross-checked every recovered symbol against the human-readable knowledge docs and the `.design` grammar header so that no single source stands alone.

### 2.3 Caveats

- **AOT opacity.** Function *bodies* are native code; control flow and exact grammar productions are reconstructed from symbol names + docs, not decompiled.
- **Version drift.** The bundled knowledge tracks `v0.1.0-beta.20`; some research docs predate it. v3 design-system terms are used throughout.
- **No live MCP capture.** The running server (`http://127.0.0.1:3333/mcp` per research notes) was not queried; tool schemas come from binary descriptions + docs.

---

## 3. Application architecture

Brilliant is a **Flutter desktop app** (Dart, compiled AOT) rendered through Flutter's **Impeller** engine (`FLTEnableImpeller=true`). It is delivered as a standard macOS `.app` bundle. The entire product logic — editor, compiler, design-system engine, renderer integration, and the AI agent host — lives inside the single `App.framework` Dart image; the surrounding `Contents` tree is the conventional Flutter macOS shell plus bundled assets.

```
Brilliant.app/Contents
├── Info.plist                      # v0.1.0.22 · Impeller on · brilliant:// scheme · macOS 14+
├── MacOS/Brilliant                 # Flutter runner (thin host)
├── Frameworks/
│   ├── FlutterMacOS.framework      # Flutter engine (Skia/Impeller, dart VM-AOT runtime)
│   └── App.framework/.../App       # 64 MB AOT Dart image — ALL product logic
└── Resources/
    ├── .claude-prod/               # bundled production knowledge/skills markdown
    └── flutter_assets/assets/
        ├── getting-started/*.design        # sample blueprint (grammar header)
        ├── playground/*.jsonl              # agent transcripts
        └── codemirror/dist/editor.bundle.js# embedded code editor (generic CM6)
```

Architecturally the app is layered like this (each box is backed by recovered symbols):

```
┌──────────────────────────────────────────────────────────────────────┐
│  UI / Editor (Flutter widgets)                                         │
│   • Canvas, property panels (_build* symbols), CodeMirror code editor  │
│   • AI chat panel (_buildAIChat*, _buildAgentHeaderRow…)               │
├──────────────────────────────────────────────────────────────────────┤
│  Agent / MCP host           package:brilliant/providers/tool_executor │
│   • MCPToolRegistry · MCPServerManager · MCPToolsInit/Create/Execute   │
│   • Providers: Anthropic/Google/OpenAI/OpenRouter + Claude CLI         │
│   • Sessions, spawn_agent fan-out, compaction (LLM summarization)      │
├──────────────────────────────────────────────────────────────────────┤
│  Blueprint compiler                                                    │
│   TokenNormalizer → Parser(petitparser) → Validator → Interpreter →    │
│   LineProcessor → BlueprintDiagnostic                                  │
├──────────────────────────────────────────────────────────────────────┤
│  Design-system compiler                                                │
│   DesignSystemManager · DesignSystemGenerator (boldness/tshirt/        │
│   looseness · color/number · OKLCH) · Catalog · .styles → .gen.yaml    │
├──────────────────────────────────────────────────────────────────────┤
│  Element model + engines                                               │
│   ElementManager(* extensions) · AutoLayoutExtension (flex engine) ·   │
│   ElementGeometry · Shader/Noise effects · Export                      │
├──────────────────────────────────────────────────────────────────────┤
│  Persistence:  .design files (repo mode) · Styles/*.styles + *.gen.yaml│
└──────────────────────────────────────────────────────────────────────┘
```

Notable runtime facts recovered from the binary:
- **Repo mode vs stateless.** Projects operate in a "repo" with a canvas tree on disk; `"Cannot import .design file: not in repo mode"` confirms a distinct repo concept.
- **FFI present.** `FfiTrampolineData`, `_ffi_resolver*` — native FFI is used (likely platform/codec/shader glue).
- **Universal binary.** The image carries both `x86_64` and `arm64` slices (Intel + Apple Silicon).

---

## 4. The `.design` file format (serialization)

The single most valuable artifact in the package is the sample `.design` file, which **documents its own grammar** in a header comment. This is the canonical on-disk serialization and the clearest window into the object model.

### 4.1 The self-describing header (verbatim)

```
# Syntax: {id} {type}[(...)] [p(x,y)] [s(w,h)] [f[(id,spec),...]] [st[(id,color,w(N)),...]]
#   [rd(n)] [o(n)] [rot(n)] [skew(x,y)] [flip(h,v)] [clip] ["name"]
# Types: r, c, l, fr, gr, t(content,family,size,weight,align),
#        al(dir,x(...),y(...),g(n),pad(...)), v(...), inst(ref)
# Fill:   f[(id,#hex)] | f[(id,solid(#hex,o(N)))] | f[(id,linear(angle,stop(#hex,pos),...))]
# Stroke: st[(id,#hex,w(N),cap(start,end),pos(p))]
```

### 4.2 Structural properties

- **Line = element.** Every visual element is one line. Leading token is a **stable 64-bit hex id** (e.g. `a1b2c3d4e5f60718`); `"Refs must be assigned explicitly during creation"` confirms IDs are persistent identity, not positional.
- **Indentation = tree.** Two-space indent nests a child under the previous shallower line. Only container types (`fr`, `gr`, `al`) legally take children (see §6).
- **Fills and strokes carry their own IDs.** `f[(id,#hex)]` — each *paint* is independently addressable, enabling targeted edits ("change fill #2 of element X") and stable token binding. This is a deliberate design choice that most vector formats lack.
- **Vector subpaths.** `vr(id, path)` lines describe sub-paths of a `v(...)` vector; a `hole` marker selects even-odd fill for cut-outs.
- **Rich paint grammar.** Solid with opacity `solid(#hex,o(N))`, `linear(angle, stop(#hex,pos), …)` and radial gradients, plus `shadow()`, inner shadows, and glass/clay effect fills (confirmed by `AddNoiseGrainFillCommand`, shader command symbols in §11).
- **Root constraint.** `"Expected a single root element"` and `"Invalid .design file: root is not a YAML map"` — a `.design` file is a **YAML document** whose body embeds the blueprint text; there is exactly one root element per canvas.

> **Critical observation — the color byte order.** 8-digit hex is interpreted **`#AARRGGBB`** (Flutter's `Color` byte order), *not* CSS's `#RRGGBBAA`. This is confirmed **verbatim** by a recovered diagnostic: *"… is 8-char `#RRGGBBAA` (CSS) but Brilliant's color parser reads 8-char hex as `#AARRGGBB` (Flutter byte order). Auto-corrected to …"* (regex `^(#[0-9a-fA-F]{8})\b`). So the convention mismatch is a real foot-gun — an alpha-first interpretation shifts channels — but the parser **detects and auto-corrects** pasted CSS-style 8-digit hex rather than failing silently. The knowledge docs still steer authors toward 6-digit hex + explicit `o(N)`/`$visibility` to avoid relying on the heuristic.

### 4.3 Why one format for three jobs

The same Blueprint text is (a) what the file stores, (b) what `find_elements … format:"blueprint"` returns for inspection, and (c) what the agent emits to create elements. Collapsing disk/wire/authoring into one grammar is the central architectural bet of the product: it means the AI never translates between an "API" and a "file format" — it reads and writes the literal source of truth.

---

## 5. The object model (element types)

The knowledge corpus (`blueprint/core.md`) and the `.design` header agree on a small, closed set of element types. A recovered diagnostic makes the container rule explicit:

> *"… is a leaf primitive, not a container. Use `fr` (plain frame), `gr` (group), or `al(h,…)` / `al(v,…)` (auto-layout frame) for the parent. For a colored or gradient background, stack fills on the parent instead of nesting a rectangle child."*

| Token | Element | Children? | Notes |
|---|---|---|---|
| `r` | Rectangle | no | leaf primitive; `rd()` for corner radius |
| `c` | Circle/ellipse | no | leaf |
| `l` / `line()` | Line | no | leaf |
| `t(content,family,size,weight,align)` | Text | no | typography via tokens; outline-text path exists (`ElementManagerOutlineText`) |
| `v(...)` + `vr(...)` | Vector | no | sub-paths, `hole` for even-odd |
| `svg(icon:name)` | Icon | no | async import (see error-recovery note below) |
| `inst(ref)` | Component instance | — | instantiates a component/symbol |
| `fr` | Frame | **yes** | plain container; can hold fills (backgrounds) |
| `gr` | Group | **yes** | logical grouping |
| `al(dir,…)` | Auto-layout frame | **yes** | the flex container (see §10) |

Design decisions worth flagging:
- **Backgrounds are fills, not nested rectangles.** The compiler actively discourages the common "wrap everything in a colored rect" habit by stacking fills on the parent frame. This keeps the tree shallow and the layout engine fast.
- **Async children are a known hazard.** A recovered diagnostic warns that modifying an `svg(...)` child *in the same call* that created it can fail because "its async import has not finished … Move the modify to a separate `create_modify_elements` call." This is an honest exposure of an internal asynchrony boundary.
- **"Ghost frames."** The validator flags "empty hug parents with no fills/strokes" — a lint for zero-size invisible containers, a classic LLM-authoring artifact.

---

## 6. The Blueprint language — grammar

Blueprint is a **whitespace-significant, line-oriented PEG language**. There is no official BNF in the package; the grammar below is **reconstructed [inferred]** from the `.design` header, the knowledge docs, and the petitparser symbols, and is consistent with all observed examples.

### 6.1 Lexical structure

- **Line types:** comment (`# …` in files, `// …` in `<objects>` streams), element line, modify line (flat `#ref …`), directive line (`undo(…)`, `delete(…)`, etc.).
- **Indentation:** 2 spaces per depth level; depth defines parent/child. The parser keeps a **parent stack** that persists across streamed blocks (per the `<objects>` protocol).
- **Refs:** a 64-bit hex id (persisted) **or** a session `#ref` (author-assigned, scoped to the call/session).
- **Tokens:** `$name` or `$name.stop` design-system references (see §8–9).

### 6.2 Reconstructed grammar (EBNF-style, [inferred])

```ebnf
document      = { line } ;
line          = indent , ( element | modify | directive | comment ) , newline ;
indent        = { "  " } ;                         (* 2 spaces per depth *)

element       = [ id ] , type , { property } , [ string_name ] , [ ref_decl ] ;
modify        = ref , { property } ;               (* FLAT (no indent) = mutate existing *)
directive     = ("undo"|"redo"|"delete"|"clone"|"replace"|"ungroup"
                |"parent"|"before"|"after"|"override") , "(" , args , ")" ;

type          = "r" | "c" | "l" | "fr" | "gr"
              | "t"  , "(" , text_args , ")"
              | "al" , "(" , layout_args , ")"
              | "v"  , "(" , path , ")"
              | "svg", "(" , "icon:" , name , ")"
              | "inst", "(" , ref , ")" ;

property      = position | size | fills | strokes | radius | opacity
              | rotation | skew | flip | clip | align_spacing | effect ;

position      = "p" , "(" , num , "," , num , ")" ;
size          = "s" , "(" , dim , "," , dim , ")" ;
dim           = num | "hug" | "fill" | "fill:" , num ;
fills         = "f" , "[" , paint , { "," , paint } , "]" ;
paint         = "(" , [ id "," ] , ( hex
                                   | "solid" "(" hex "," "o" "(" num ")" ")"
                                   | "linear" "(" angle "," stop {"," stop} ")"
                                   | "radial" "(" ... ")"
                                   | token ) , ")" ;
strokes       = "st" , "[" , "(" , [id ","] , color , "," , "w" "(" num ")"
                            , [ "," "cap" "(" id "," id ")" ]
                            , [ "," "pos" "(" p ")" ] , ")" , { "," ... } , "]" ;
radius        = "rd" , "(" , (num | token) , ")" ;
opacity       = "o"  , "(" , (num | token) , ")" ;

layout_args   = dir , [ "," "x" "(" anchor ")" ] , [ "," "y" "(" anchor ")" ]
                    , [ "," "g" "(" num|token ")" ] , [ "," "pad" "(" pad ")" ] ;
dir           = "h" | "v" ;
anchor        = "s" | "c" | "e" | "sb" ;            (* start/center/end/space-between *)

color         = hex | token ;
token         = "$" , name , { "." , stop } ;       (* design-system reference *)
hex           = "#" , hexdigit{3,8} ;
string_name   = '"' , { char } , '"' ;
ref_decl      = "#" , name ;                        (* assign a session ref *)
ref           = ("#" , name) | hexid ;
```

### 6.3 Modify-vs-create discipline

From `objects-syntax.md` and confirmed by interpreter behavior:
- **Indented line with a type ⇒ create** a child under the current parent.
- **Flat line beginning with `#ref` ⇒ modify** that existing element (e.g. `#card f[(#FF0000)]`).
- **Reparenting** is explicit: `#badge parent(#new_card)`. The binary guards this hard — `"Cannot reparent to descendant"`, `"Cannot reparent element to itself"`, `"Cannot reparent to non-existent or non-frame"`.

### 6.4 Directives (mutation verbs)

`blueprint/directives.md` plus binary command symbols give the verb set: `parent()`, `before()`, `after()`, `clone()`, `replace()`, `ungroup()`, `delete()`, `override()`, and the history pair `undo()/redo()`. Crucially, **undo/redo are keyed to author-written `// label` checkpoints** — the interpreter snapshots canvas state at each labeled comment and `undo("hero copy")` rolls back to it. Recovered strings confirm the runtime tracks these: `"Recent checkpoints (most recent first):"`, `"No checkpoints registered yet."`, `_checkpointHintLine`, `_checkpointLabel`. This makes narration and undo the *same* artifact — an elegant, unusual choice.

---

## 7. The Blueprint compiler

This is the heart of the product. The binary string table exposes a clean, classically-structured compiler. The pipeline classes recovered verbatim:

```
BlueprintTokenNormalizer  →  BlueprintParser  →  BlueprintValidator
        →  BlueprintInterpreter  →  BlueprintLineProcessor
                       │
                       └── BlueprintDiagnostic / DiagnosticSeverity
```

This maps directly onto the four phases the official blog describes (**parse, validate, execute, lint**), with normalization as a pre-pass and `LineProcessor` as the streaming driver.

### 7.1 Phase 1 — `BlueprintTokenNormalizer`

A normalization pre-pass over raw text before parsing: canonicalizing token spelling, whitespace, and shorthand. Its existence explains why authors can write loose shorthand (`b` for bold weight, bare `$primary`) and still hit a strict parser — the normalizer rewrites to canonical form first. (Body is opaque; role is inferred from name + position in the chain.)

### 7.2 Phase 2 — `BlueprintParser` (petitparser)

The parser is built with **petitparser**, Dart's parser-combinator (PEG) library. This is *directly evidenced*, not inferred — the binary embeds the library's source paths and combinator classes:

```
package:petitparser/src/core/parser.dart   …/context.dart …/result.dart …/token.dart
package:petitparser/src/definition/reference.dart  …/resolve.dart
SequenceParser2 … SequenceParser8        ChoiceParser / toChoiceParser
FlattenParser / flatten                   PossessiveRepeatingParser / star / repeat
LazyRepeatingParser / repeatLazy/starLazy CharacterParser / RepeatingCharacterParser
RecordOfParsersExtension3|toSequenceParser
```

Implications of a PEG/combinator parser here:
- **Ordered choice, no ambiguity.** PEG's prioritized choice fits a terse line grammar well — the first matching alternative wins, so `al(...)` vs `t(...)` vs `r` dispatch is deterministic.
- **`SequenceParser2..8`** indicates productions of fixed arity 2–8 — i.e. property groups like `p(x,y)`, `s(w,h)`, `linear(angle,stop,stop,…)` are sequence parsers of known shape.
- **`PossessiveRepeatingParser` (star/plus)** with no backtracking — fast, predictable, but means malformed input fails *at a point* rather than trying alternate parses. This is consistent with the observed "stop at first error, report the line" behavior.
- **`FlattenParser`** collapses matched sub-trees back to source spans — useful for producing diagnostics that quote the offending substring.

### 7.3 Phase 3 — `BlueprintValidator`

Semantic checks after a syntactic parse. Recovered diagnostics show the validator enforces both structural and design-system rules:

- **Container legality** — leaf-as-parent error (§5).
- **Reparenting safety** — self/descendant/non-frame guards (§6.3).
- **Single root** — `"Expected a single root element"`.
- **Token resolvability** — `formatUnresolvedTokenDiagnostic`; in design-system modes, references that don't resolve to defined tokens error rather than silently passing.
- **Lint-grade warnings** — ghost frames, wrap hints (`"Add s(fill,hug) to enable wrapping"`), overflow notes. These are *advisory* (`DiagnosticSeverity` has multiple levels), separating hard errors from style nits — the "lint" phase.

### 7.4 Phase 4 — `BlueprintInterpreter` + `BlueprintLineProcessor`

`LineProcessor` is the **streaming execution driver**. Each line is processed as it arrives (critical for the agent's streamed `<objects>` blocks), mutating the live element tree via `ElementManager*` operations. The interpreter resolves tokens, materializes elements, assigns/looks-up refs, and applies the auto-layout pass.

### 7.5 Error recovery — partial application, continue-from-failure

The most distinctive compiler behavior, confirmed by both docs and binary strings (`"element(s) previewed (post-error recovery)"`, `firstErrorLine`, `"create_modify_elements cascade halt at row "`, `"Replay skipping line (parser errored): "`):

```
Stream of lines ──► process line N ──► ok? ──► commit, register refs, next line
                                        │
                                        └─ error ─► STOP.
                                            • line N is NOT applied (no element, no ref)
                                            • lines after N are DISCARDED
                                            • lines before N remain committed on canvas
                                            • emit BlueprintDiagnostic: failing line + fix hint
                                                + count of lines applied before the error
```

Recovery is *resumptive*: the agent issues a new block continuing from the failed line, and because the **parent stack is preserved across blocks**, indentation context survives. This "cascade halt + resume" model is what makes an LLM author viable against a strict grammar — partial progress is never lost, and the model gets a precise, single-point error to fix.

### 7.6 Compiler pipeline diagram

```
        raw blueprint text (file load · <objects> stream · quiver SVG import)
                                   │
                 ┌─────────────────▼─────────────────┐
                 │  BlueprintTokenNormalizer          │  canonicalize shorthand/space
                 └─────────────────┬─────────────────┘
                 ┌─────────────────▼─────────────────┐
                 │  BlueprintParser  (petitparser PEG)│  line → typed AST node
                 └─────────────────┬─────────────────┘
                 ┌─────────────────▼─────────────────┐
                 │  BlueprintValidator                │  structure + token + lint rules
                 │   → BlueprintDiagnostic(severity)  │
                 └─────────────────┬─────────────────┘
                 ┌─────────────────▼─────────────────┐
                 │  BlueprintInterpreter              │  resolve tokens, build elements,
                 │   (via ElementManager* ops)        │  bind refs, run auto-layout
                 └─────────────────┬─────────────────┘
                 ┌─────────────────▼─────────────────┐
                 │  BlueprintLineProcessor            │  streaming driver + cascade-halt
                 └─────────────────┬─────────────────┘
                          live element tree  ──►  render (Impeller) · persist (.design)
```

---

## 8. The design-system compiler (v3)

Brilliant's second compiler is arguably its most original idea: **a design system is a small program, not a token list.** A human authors a `Styles/default.styles` file that *calls generators*; the compiler expands those into a full token catalog (`*.gen.yaml`), mode branches and all. Recovered manager string: *"DesignSystemManager initialized (empty baseline; Styles/default.styles is the source of truth)."*

### 8.1 The five generators

Confirmed by both `v3-design-spec.md` and binary symbols (`_emitBoldnessGenerator`, `_emitTshirtGenerator`, `_emitLoosenessGenerator`, `_expandNumericRamp`, `_hexToOklchPure`, `_oklchLiteralToHex`):

**Primitives**
```
color(seed)                          # OKLCH lightness ramp → 11 stops (.50 … .950)
number(seed, count, ramp)            # generative from a seed
number(range(min,max), count, ramp)  # generative within bounds
number([a, b, c, …])                 # explicit list → stops .1..N
```
Ramps: `linear()`, `linear(step:S)`, `geometric()`, `geometric(ratio:R)`.

**Semantic (1:N, mode-keyed)**
```
boldness(scale)    # 9 stops: hint faint subtle soft mid firm bold strong intense
tshirt(scale, [min:{name:val}], [max:{name:val}])   # xs sm md lg xl 2xl…NxL + boundaries
looseness(scale)   # 6 stops: none tight snug normal relaxed loose
```

### 8.2 Two vocabularies, applied uniformly

The conceptual payoff is that the **same nine "boldness" names describe color tone, font weight, stroke width, and opacity/visibility** — and the catalog maps each role onto the right primitive per domain. Recovered role-index functions confirm this is real code: `_boldnessRoleIndex`, `_tshirtRoleIndex`, `_loosenessRoleIndex`, `_isTshirtScaleCategory`.

| Generator | Vocabulary | Used for | Role→stop example (catalog) |
|---|---|---|---|
| `boldness` | hint→intense (9) | color tone, `font.weight`, `stroke.width`, `visibility` | color: `bold→.700`; weight: `bold→700` |
| `tshirt` | xs→NxL + none/full | `spacing`, `radius`, `font.size` | `number([4,8,16,24,32,48])` → xs..; `min:{none:0} max:{full:9999}` |
| `looseness` | none→loose (6) | `font.lineHeight`, `font.letterSpacing` | positional list[0..5] |

So `$primary.bold`, `$font.weight.bold`, and `$stroke.width.bold` all speak one scale; an author who learns "boldness" once applies it everywhere. This is a genuinely elegant unification and the clearest evidence of deliberate language design rather than ad-hoc tokens.

### 8.3 OKLCH color pipeline

Colors are computed in **OKLCH** (perceptually-uniform), not sRGB/HSL. Evidence: `OklchColor`, `colorToOklch`, `_hexToOklchPure`, `_oklchLiteralToHex`, `_oklchDistanceTuple`, and the validator messages `"color(oklch(...)): expected #hex or three positional numerics (L, C, H)"`. A single seed hue generates an 11-stop lightness ramp with perceptually-even spacing — why the palettes look balanced across the whole range, and why dark-mode inversion (§9.3) is principled rather than hand-tuned.

### 8.4 Compilation: `.styles` → `.gen.yaml`

Recovered strings reveal the full lifecycle, including a **legacy migration path**:
- Source of truth: `Styles/default.styles` (+ per-brand `*.styles`).
- Compiled output: `default.gen.yaml` — *"Regenerate all `.gen.yaml` files from their `.styles` sources."*
- Migration: *"Migrated from legacy `.styles` (YAML) on …"*, *"folder(s) from legacy `.styles` to DSL `Styles/` layout"*, plus `.styles.backup` — the team moved from a flat YAML token file to the generator DSL and kept a converter.
- Backup/recovery: *"Root default.styles deleted, recreating."*
- `pin:` / `hide:` directives let a `.styles` file pin or hide palettes/tokens from the catalog.

### 8.5 Generator validation (exact messages)

The DS compiler has its own validator with precise, author-friendly errors (verbatim):
```
boldness(...): expected one inner generator (color(...) or number(...))
tshirt(...):   expected one inner generator (number(...))
looseness(...):expected one inner generator (number(...))
color(...): seed must be a literal value or an oklch(...) call, not a reference / record / list
number([...]): list elements must be numeric
number(value, count, ramp): expected positive integer count
linear(...): expected `base: N` argument
linear(..., count: N): custom count not yet supported by generator
"…": expected linear() or geometric()
(..., transforms: ...): expected a record like `{ axis.value: shift(-1) }`, or `none`
"…": $transforms references unknown stop "…"
expected axis-qualified key like `density.compact`, not bare `…`
```
The last three reveal the **mode-transform syntax**: a generator can carry a `transforms:` record keyed by `axis.value` (e.g. `density.compact: shift(-1)`) describing how its output shifts per mode — the mechanism behind §9.3.

---

## 9. The token resolver

At authoring time, every color/size/typography value is a `$token`. The resolver turns `$token` → concrete value through the active design system and the active mode stack. Recovered resolver symbols: `_resolveDesignSystem`, `_resolveDesignSystemUncached`, `_resolveBrandCascade`, `_resolveBrandFile`, `_resolveBrandScope`, `_resolveAxisScope`, `_resolveCompositeNumericRef`, `_resolveCompositeStringRef`, `_resolveDeferredThemedValue`, `_resolveColor`, `_resolveColorList`, `_resolveFont`, `_resolveFontFamily`, plus `_Resolver` / `_ResolveState`.

### 9.1 Two stop vocabularies (author-facing)

From `design-systems/core.md`:
- **Presence ramp** — `hint faint subtle soft mid firm bold strong intense`. Governs brand/palette tone, `$font.weight`, `$stroke.width`, `$visibility`. Bare `$primary` = `$primary.mid`.
- **T-shirt scale** — `xs sm md lg xl 2xl…Nxl` + `none`. Governs `$spacing`, `$radius`, `$font.size`. Never used bare — always a chosen stop.
- **Chrome aliases** — semantic role names (`$color.surface`, `$color.text.primary`, `$color.outline`, `$color.shadow`, …) that point at resolver outputs and *are* their own names.

### 9.2 Strict-mode halting

A key safety property: in explicit/DS modes the resolver **halts on bare values** in tokenizable slots (`g() pad() rd() o() w() lh() ls()`, `t()` size, and any color). The author must supply a `$token`; primitive stops like `$primary.500` or `$spacing.4` are rejected in favor of role names. The one numeric exception is the bare color seed (`$primary` → `.mid`). The binary encodes three session modes (verbatim):
- **NONE mode** — "No design system constraints. Use bare hex / numerics freely … Token references must resolve to defined tokens or they will error."
- **NEW DS mode** — author the design system first via `ds_file("name") <body>`; element rows before a successful `ds_file()` error; afterwards behaves as explicit mode.
- **Explicit mode** — tokens only, no bare hex on tokenizable slots.

### 9.3 Mode resolution (theme / density / accessibility)

Tokens re-resolve under a mode matrix. Default axes: `theme:[light,dark]`, `density:[comfortable,compact]`, `accessibility:[standard,high-contrast,large-text]`. Mode keys are **axis-qualified** (`$default`, `dark`, `density.compact`) — confirmed by the binary comment *"# ($default, dark, density.compact, etc.). External tools can …"* and the validator's insistence on `density.compact` over bare `compact`.

Generator-level mode behavior (from spec, consistent with the `transforms:` syntax in §8.5):
- `boldness(color(...))` **inverts** under `theme.dark` (hint↔intense, faint↔strong, subtle↔bold, soft↔firm; mid fixed) — so the same low stops that read light in light mode read dark in dark mode. This is why "presence" is *loudness against the surface*, not brightness, and why `$color.shadow` (absolute) never flips.
- `tshirt(number(...))` shifts a notch under `density.compact` / `accessibility.large-text`.
- `looseness(number(...))` loosens a step under `large-text`.

These transforms live in **catalog code**, not user files — the author writes `boldness(...)` once and inherits canonical mode-aware behavior. `ds()` switches brand/mode inline (`ds(editorial, theme(dark))`); a top-level frame stamps the active DS and children inherit.

---

## 10. The auto-layout engine

Brilliant ships a **Flexbox-equivalent constraint engine**, fully exposed by the `AutoLayoutExtension|*` symbol cluster — one of the richest in the binary. This is bespoke layout code, not a thin wrapper over Flutter's widgets (it operates on the element model, computing absolute positions).

### 10.1 Model (from `blueprint/layout.md`)

```
al(dir, x(anchor), y(anchor), g(gap), pad(...))
  dir     = h | v                 main axis
  x()/y() = s | c | e | sb        start / center / end / space-between
  g()     = gap between children  (token or number)
  pad()   = padding (1/2/4 values)
  sizing per child: fixed | hug (shrink-to-content) | fill | fill:N (flex-grow weight)
  wrap    = multi-line flow (needs s(fill,hug))
  abs     = take a child out of flow (absolute), p(c,c) to center
```

### 10.2 Engine internals (recovered methods)

```
_computeAndApplyLayout / _computeAndApplyLayoutWithGap     ← main entry
_layoutHorizontal / _layoutVertical (+ …WithGap)           ← axis solvers
_layoutHorizontalWrap / _layoutVerticalWrap (+ …WithGap)   ← wrapping variants
_calculateHorizontalPositions / _calculateVerticalPositions
_computeNaturalHugDimension      ← shrink-to-content sizing
_isFillResolvedAsHug             ← fill→hug fallback when no free space
_frameDimensions / resizeParentToFitChildren / _resizeElement
_calculateCurrentInsertionIndex / _calculateWrappedInsertionIndex
                                 ← live drag-to-insert index math
initAutoLayoutDragState / clearAutoLayoutDragState / _computeInsertionIndicator
reorderInAutoLayout / _reorderSelectedToIndex / _registerAutoLayoutReorderUndo
isAutoLayoutParent / isInAutoLayoutFrame / checkAutoLayoutAfterResize
_isRotatedOrSkewed               ← excludes transformed children from flow math
```

What this tells us:
- **Hug and fill are first-class** with a real fallback path (`_isFillResolvedAsHug`): a `fill` child with no free space degrades to `hug`, preventing zero/negative sizes.
- **Layout is interactive, not just declarative** — insertion-index math, drag indicators, and reorder-undo mean the *same* engine drives both agent-authored blueprints and human drag-and-drop on the canvas, with undo integration.
- **Transformed children are handled specially** (`_isRotatedOrSkewed`) — rotated/skewed elements are taken out of naive bounds math, a correctness detail many flex engines get wrong.
- **Parent auto-resize** (`resizeParentToFitChildren`, `_computeNaturalHugDimension`) implements the hug semantics bottom-up.

---

## 11. Rendering & effects

Rendering runs on Flutter **Impeller**. Beyond flat fills, the binary reveals a full **programmable paint/effects** subsystem:

- **Shaders.** `AddShaderColorCommand`, `ChangeShaderEffectTypeCommand`, `applyShaderPreset`, `resolveShaderInfo`, `toggleShaderAnimation`, `_applyShaderTransform`, `_shaderParamPrefix`, plus drag-to-adjust param/transform commands. Shaders are *animatable* and have presets, multiple color inputs, and an adjustable scale/offset/rotation transform.
- **Noise / grain.** `AddNoiseGrainFillCommand`, `DropdownSetNoiseGrainPresetCommand`, presets "Blue Noise / Color Noise" — a dedicated grain fill type.
- **Effects as fills.** Glass/clay/inner-shadow effects stack as fills on an element (the `.design` header's `f[…]` list), composing with solids and gradients. Resize compensation exists for shader fills (`_compensateShaderFillsForResize`, `_compensateShaderRegionFillsForResize`) so procedural paint tracks geometry changes.
- **Outline text & per-glyph fills.** `ElementManagerOutlineText|_resolveFillsForGlyph` — text can be converted to outlines with per-glyph fill resolution.
- **Image filters / blur.** `_resolveImageFilterPart`, `_buildBackdropBlurClipPath`, `_buildBlurStrokeOutline` — backdrop blur and blurred stroke outlines.
- **Geometry kernel.** `ElementGeometry|fillIntersectsRect`, `_circleFillIntersectsRect`, `_rectangleFillIntersectsRect`, `_computeVectorGeometricBounds` — hit-testing and bounds for marquee select, snapping (`_buildGeometricEquidistantGuides`), and measurement.

---

## 12. The agent / MCP layer

Brilliant is an **AI-native** tool: the design agent is a first-class client of the same compiler a human uses, mediated by an MCP (Model Context Protocol) tool surface. The host lives in `package:brilliant/providers/tool_executor.dart` with `MCPToolRegistry`, `MCPServerManager`, and the `MCPToolsInit/Create/Execute/Read/Generate/Skills` families.

### 12.1 Tool surface (recovered descriptions)

| Tool | Purpose (from binary descriptions) |
|---|---|
| `init` | "Bootstrap a design session. Returns a unique session ID, session context (canvas ID, repo path), and documentation. Call this first." Session ID scopes refs + DS state across calls. |
| `create_html` | Primary fast path — "use `create_html` directly for most tasks (no knowledge loading needed)." |
| `create_modify_elements` | Stream Blueprint via `<objects>`; the compiler entry point. Errors: "elements must be a string", "no elements provided", "failed to load canvas", "cascade halt at row N". |
| `get_knowledge` | Load Blueprint DSL docs on demand — "Only … when using the Blueprint DSL for advanced features." |
| `find_elements` | "Find or read elements across the design repo. Unifies discovery (by name/text/type/color/component) and inspection." `format:"summary"|"blueprint"`, `scope`, `depth`. |
| `get_selection` | Read the user's current canvas selection. |
| `execute_commands` | Run named element commands (auto_layout, scale_elements_to_width/height, unbind_tokens, reorder, boolean ops, …). |
| `export` | Render/export elements (`ElementManagerExport|buildBlueprintTokenColorResolver`). |
| `generate_image` / `generate_images` | Image gen, incl. batch — "Generate images with Nano Banana 2 (Gemini Image)". |
| `generate_svg` / `vectorize_image` | Vector generation and raster→vector ("Vectorized SVG placed on canvas. Source raster element left intact."). |
| `plan_agents` / `spawn_agent` | Multi-agent: announce a plan, then fan out blocking sub-agents — "Launch multiple `spawn_agent` calls in a single turn for parallel execution." |
| `load_mcp_server` | Lazily load external MCP servers' tools on demand. |

### 12.2 Session & multi-agent model

- **Sessions** scope element refs and design-system state so parallel agents don't collide: "Pass this EXACT string as the `sessionId` … It scopes your element refs and design-system state so you never collide with other agents."
- **Sub-agents** run in parallel and block until each returns a summary; `plan_agents` shows the user the plan first.
- **External MCP servers** can be attached and their tools humanized/namespaced (`_humanizeToolName`, `_normalizeMcpToolName`, `_toolNameRegex`, `validateAndWarnToolName`).

### 12.3 Providers (BYOK, multi-model)

`tool_executor` is provider-agnostic. Recovered providers and models:
- **Claude CLI** (`@anthropic-ai/claude-code`) — local CLI bridge with `/cost`, `/compact`.
- **HTTP providers:** `AnthropicHttpProvider`, `GoogleHttpProvider`, plus OpenAI/OpenRouter (env keys `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`).
- **Model menu (as shipped):** GPT-5.4 / 5.4 Pro / 5.5 / 5.5 Pro / 5.3 Codex; Gemini 3 Pro / 3.1 Pro / 3 Flash / 3.5 Flash; Gemini image (`gemini-3.1-flash-image-preview`, "Nano Banana 2"). Note these reflect the app's *forward-dated* model catalog, not an endorsement of availability.

### 12.4 The streaming `<objects>` protocol & self-review loop

The agent authors by emitting one `<objects canvasId="…" previewIds="#ref">` block at a time. After each successful block the runtime **interrupts the response**, injects a **screenshot + self-review checklist** (spacing, typography, contrast, alignment, clipping) and flagged composition problems (duplicate sibling names, collapsed zero-size elements, invisible text). The agent fixes issues in the next block or replies to the user. On error there's no interrupt — the failing line + fix hint + applied-count are surfaced and the agent resumes (§7.5). This closes a perception loop: the model *sees* its own output and critiques it before continuing.

### 12.5 Context management

`ClaudeCompactionEvent`, "Compacting conversation history…", "Compacted history via LLM summarization", "Context limit reached. Auto-compacting…" — long sessions are compacted by LLM summarization with a truncation fallback, mirroring Claude Code's `/compact`.

---

## 13. Critical assessment

### 13.1 Strengths

- **One language, three roles.** Disk format = wire format = authoring format. This eliminates an entire class of translation bugs and makes the AI agent a true peer of the human editor. It is the product's strongest idea.
- **The design system is a program.** Generators + OKLCH + mode transforms mean a coherent, perceptually-even, dark-mode-correct system falls out of ~150 lines of `.styles`. The unified "boldness" vocabulary across color/weight/stroke/opacity is genuinely novel ergonomics.
- **A real compiler with real diagnostics.** Normalize→parse→validate→interpret→lint with severities, single-point errors, fix hints, and resumptive recovery — engineered for fallible (LLM) authors, not just well-formed input.
- **Layout engine is interactive and correct in the hard cases** (hug/fill fallback, transformed children, drag-insert + undo).
- **Stable per-element and per-paint IDs** make targeted edits and token binding robust.

### 13.2 Weaknesses & risks

- **Whitespace-significant line grammar under LLM authorship is inherently fragile.** A single mis-indent reparents a subtree; the cascade-halt model mitigates but does not remove this. The proliferation of "ghost frame", wrap-hint, and async-svg diagnostics shows these are recurring real failures.
- **The `#AARRGGBB` hex convention is a latent correctness trap.** It diverges from CSS and from designer intuition. The parser ships a heuristic that detects and auto-corrects pasted CSS-style 8-digit hex (§4.2), which is pragmatic but heuristic-dependent — an intentional alpha-first value is ambiguous against a pasted CSS one. Documentation patches the rest rather than the format itself.
- **Forward-dated, multi-vendor model catalog** (GPT-5.5, Gemini 3.x) ties UX to external APIs and pricing tables (`AnthropicPricing`) the app must track; idle-timeout and token-exchange error strings hint at real reliability surface area.
- **Opaque 64 MB AOT monolith.** All logic in one image is simple to ship but hard to audit, sandbox, or extend; FFI + shader + codec surface widens the trust boundary.
- **Async boundaries leak into the authoring model** (the "modify svg in a later call" rule). Correct, but it pushes an implementation detail onto the author/agent.
- **No first-party formal grammar.** The lack of a published BNF (only docs + a self-describing header) makes third-party tooling and verification harder, and forces reconstruction like this report.

### 13.3 Overall

This is a thoughtfully-designed, internally-consistent system whose central bets (one language for everything; a generative, mode-aware design system; an AI agent that compiles against the same pipeline as the human) are sound and unusually well-executed for a `0.1.x` build. The fragilities are the predictable costs of those bets — terse line syntax and a Flutter-native color convention — and are currently papered over with documentation and diagnostics rather than format changes.

---

## 14. Evidence appendix

### 14.1 Compiler & DSL symbols (verbatim from binary)
```
BlueprintTokenNormalizer  BlueprintParser  BlueprintValidator
BlueprintInterpreter  BlueprintLineProcessor  BlueprintDiagnostic  DiagnosticSeverity
formatUnresolvedTokenDiagnostic  firstErrorLine  "cascade halt at row "
petitparser: SequenceParser2..8 · ChoiceParser · FlattenParser ·
             PossessiveRepeatingParser · LazyRepeatingParser · CharacterParser ·
             RecordOfParsersExtension3|toSequenceParser
             package:petitparser/src/core/{parser,context,result,token}.dart
```

### 14.2 Design-system symbols
```
DesignSystemManager · DesignSystemGenerator · Catalog · _appendComponentCatalog
_emitBoldnessGenerator · _emitTshirtGenerator · _emitLoosenessGenerator · _emitDefaultCatalog
_boldnessRoleIndex · _tshirtRoleIndex · _loosenessRoleIndex · _isTshirtScaleCategory
_expandNumericRamp · _formatGeometric · _composeWithSeedTemplate
OklchColor · colorToOklch · _hexToOklchPure · _oklchLiteralToHex · _oklchDistanceTuple
.styles · .gen.yaml · .styles.backup · pin:/hide:
```

### 14.3 Layout / geometry / effects symbols
```
AutoLayoutExtension|{_computeAndApplyLayout,_layoutHorizontal,_layoutVertical,
  _layoutHorizontalWrap,_layoutVerticalWrap,_computeNaturalHugDimension,
  _isFillResolvedAsHug,resizeParentToFitChildren,reorderInAutoLayout,_isRotatedOrSkewed}
ElementGeometry|{fillIntersectsRect,_circleFillIntersectsRect,_computeVectorGeometricBounds}
Shaders: AddShaderColorCommand · ChangeShaderEffectTypeCommand · applyShaderPreset ·
  toggleShaderAnimation · AddNoiseGrainFillCommand · DropdownSetNoiseGrainPresetCommand
```

### 14.4 Agent / MCP / provider symbols
```
MCPToolRegistry · MCPServerManager · MCPToolsInit/Create/Execute/Read/Generate/Skills
tools: init · create_html · create_modify_elements · get_knowledge · find_elements ·
  get_selection · execute_commands · export · generate_image(s) · generate_svg ·
  vectorize · plan_agents · spawn_agent · load_mcp_server
providers: AnthropicHttpProvider · GoogleHttpProvider · Claude CLI · OpenAI/OpenRouter
package:brilliant/providers/tool_executor.dart
ClaudeCompactionEvent · CompactionEvent · "Compacted history via LLM summarization"
```

### 14.5 File inventory
```
Contents/Info.plist                                   v0.1.0.22, Impeller, brilliant://
Contents/Frameworks/App.framework/Versions/A/App      64 MB AOT (x86_64+arm64)
…/flutter_assets/assets/getting-started/*.design      grammar header (Rosetta Stone)
…/flutter_assets/assets/playground/*.jsonl            agent transcripts
…/flutter_assets/assets/codemirror/dist/editor.bundle.js  generic CM6 (not the grammar)
Contents/Resources/.claude-prod/**                    bundled prod knowledge/skills
brilliant/knowledge/blueprint/{core,layout,directives}.md
brilliant/knowledge/design-systems/{core,authoring}.md
brilliant/{v3-design-spec,objects-syntax}.md
```

---

## 15. Open questions / unverified

- **Exact parser productions.** petitparser is confirmed, but individual grammar rules are reconstructed [inferred]; the AOT bodies are not decompiled here.
- **`BlueprintTokenNormalizer` exact rewrites** — the canonicalization rules (which shorthands expand to what) are inferred from position + examples.
- **Live MCP schemas** — the running server at `127.0.0.1:3333` was not queried; argument contracts come from binary descriptions, which may lag the live tool.
- **Catalog role-index numeric mappings** — confirmed the functions exist; the precise index tables (e.g. spacing's xs→1, md→4) come from `v3-design-spec.md`, not the binary tables.
- **Radial gradient & effect sub-grammars** — present (header + symbols) but not fully enumerated.
- **CodeMirror Blueprint mode** — the bundle is generic CM6; the Blueprint syntax-highlighting/language definition was not found in it and is likely supplied at runtime from Dart, not the JS asset.

*Claims marked [inferred] are reconstructions; all unmarked structural claims trace to a verbatim binary symbol, the `.design` grammar header, or the bundled knowledge docs.*
