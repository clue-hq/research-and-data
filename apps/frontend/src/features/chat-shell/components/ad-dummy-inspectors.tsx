"use client";

import type { ReactNode } from "react";
import type { ZOrderAction } from "@/features/design-editor/adapter/scene-arrange";
import type { SceneInspectorState } from "@/features/design-editor/adapter/scene-hydrate";
import type { SceneLayerRow } from "@/features/design-editor/adapter/scene-layers";
import type {
  AlignMode,
  DistributeAxis,
} from "@/features/design-editor/engine/scene/alignDistribute";
import type { SceneArrangeBinding } from "@/features/design-editor/hooks/use-scene-arrange";
import type { ChatShellInspectorSelection } from "../model/chat-shell";
import {
  useInspectorController,
  type InspectorDirection,
  type InspectorEventAddressing,
  type InspectorSectionId,
  type InspectorSizeMode,
} from "../hooks/use-inspector-controller";
import {
  ColorControl,
  InspectorField,
  InspectorIcon,
  type InspectorIconName,
  InspectorInput,
  InspectorLayerRow,
  InspectorSection,
  InspectorSelect,
} from "./inspector-primitives";
import styles from "./chat-shell.module.css";
// AD4.B step 3 (§1.6): the ONE colour row every ad picker goes through, and
// the palette it is offered. It lives in its own module rather than in
// `image-inspector.tsx` where it was written, because importing from there
// would be a cycle (that file imports this one) — `AdLayersBinding`'s reason
// exactly. The provider still wraps the whole panel from `image-inspector.tsx`,
// so these schemas inherit the palette through context with no new props.
import { useAdColorRow, useScenePaletteOptions } from "./inspector-color-row";
import { LayerList } from "./layer-list";

export const AD_DUMMY_INSPECTOR_SELECTIONS = [
  "auto-layout",
  "rectangle",
  "ellipse",
  "group",
] as const satisfies readonly ChatShellInspectorSelection[];

export type AdDummyInspectorSelection =
  (typeof AD_DUMMY_INSPECTOR_SELECTIONS)[number];

export function isAdDummyInspectorSelection(
  selection: ChatShellInspectorSelection,
): selection is AdDummyInspectorSelection {
  return AD_DUMMY_INSPECTOR_SELECTIONS.includes(
    selection as AdDummyInspectorSelection,
  );
}

const STATIC_ZERO = "0";
// (`STATIC_SIZE` — the scaffolding's invented `100` — left with AD4.B step 1's
// Layout section: its W/H and fixed-size boxes read the document now, and the
// same number survives as `DEFAULT_STATE`'s seed for the fixture path.
// `NO_CHANGE` and `StaticInput` left with step 3: the Shape radii and the
// Stroke width were the last read-only boxes in this file, and every control
// outside the Arrange section now commits for real.)
/** The ad scaffolding's own Pad T/R/B/L values — all `STATIC_ZERO` — for the
 * FIXTURE path only. See `AdDummyInspector`'s `initial` below. */
const FIXTURE_PADDING = {
  bottom: STATIC_ZERO,
  left: STATIC_ZERO,
  right: STATIC_ZERO,
  top: STATIC_ZERO,
};
/** The ad scaffolding's own Radius all/TL/TR/BR/BL values — all `STATIC_ZERO`,
 * exactly what its five `StaticInput`s rendered before step 3 bound them — for
 * the FIXTURE path only, same as `FIXTURE_PADDING`. The shared `DEFAULT_STATE`
 * seeds the WEB dummy's `all: "0"` beside corners of `"4"`, which would make
 * this section state two different radii at once. See `AdDummyInspector`'s
 * `initial` below. */
const FIXTURE_RADIUS = {
  all: STATIC_ZERO,
  bottomLeft: STATIC_ZERO,
  bottomRight: STATIC_ZERO,
  topLeft: STATIC_ZERO,
  topRight: STATIC_ZERO,
};

/**
 * AD4.B step 1: what a caller supplies to drive an ad schema from a REAL scene
 * node — the web branch's own prop set (`WebInspector`'s `hydrated` +
 * `addressing` + `error`/`note`), ad-side.
 *
 * Every field is optional and absent means "the dummy as it shipped", so the
 * fixture path keeps compiling and keeps rendering (the AD0.4 `fontOptions?`
 * precedent, extended).
 *
 * It lives in THIS file, not in `image-inspector.tsx` where it was written, for
 * `AdLayersBinding`'s reason exactly: the import already runs one way
 * (image-inspector → ad-dummy-inspectors) and the reverse would be a cycle.
 * `image-inspector.tsx` imports it back and still composes
 * `AdSchemaBinding = AdLayersBinding & AdHydrationBinding` for its own three
 * schemas, so there is ONE statement of the shape rather than two that drift.
 */
export interface AdHydrationBinding {
  /** Write addressing stamped onto every inspector event this panel raises.
   * Its `documentVersion` is null on this lane permanently — the W3.1 null
   * contract, i.e. "not addressable" for optimistic concurrency; the ad lane's
   * D10 CAS reconciliation is the net instead. */
  addressing?: InspectorEventAddressing;
  /** AD4.R-10 / GATE G-H (founder-ruled 2026-08-22): an agent turn is in flight
   * on this thread, so the human may not operate this panel — "we cannot let
   * humans change any value when the agents are at work with designing".
   *
   * PREVENTION AT THE SOURCE, which is what makes it different in kind from
   * every other refusal on this lane: the adapter's silent no and the D10 CAS
   * reconciliation both act AFTER an interaction; this one means the
   * interaction never happens.
   *
   * It gates OPERATIONS ONLY (the founder's own scope, 2026-08-22): every value
   * control, the header lock, Replace image and the AI suite. Layer selection,
   * layer expansion, section open/close and zoom read and navigate — they
   * produce no document operation, so they stay live. The flag reaches nothing
   * outside this panel: the chat side of the shell (composer, sending, gates,
   * queueing) is not a consumer, and whatever it does during a running turn
   * today is exactly what it goes on doing. */
  inspectorDisabled?: boolean;
  /** RULING A29: the selected node's lock, routed from the HEADER controller —
   * the one that owns the lock button's write — so all seven schemas read ONE
   * statement of it. Since AD4.R-4 every schema's own `state.locked` is live
   * too (the accepted scene owns it), so this is no longer live-vs-seeded; it
   * is one source rather than seven. The controls use it to skip a dispatch §4
   * would refuse. */
  locked?: boolean;
  /** The selected node's real values (or the page's, for the canvas schema).
   *
   * AD4.R: this prop is read PER RENDER, not once at mount. Every ad controller
   * passes `{ liveHydration: hydrated != null }`, so its `state` is composed as
   * `{...uiState, ...hydrated}` on each render (`openSections` excepted — the
   * panel owns those): the accepted scene owns every key hydration carries, and
   * a document change re-derives them all. That is what makes a refused write
   * unable to stick — the control never left the document's value.
   *
   * Absent/null (the dummy fixture path) keeps the original contract exactly:
   * the values merge over the dummy defaults at mount and the local state owns
   * them thereafter.
   *
   * Selection changes still REMOUNT the panel (`key={primaryNodeId ?? "canvas"}`,
   * the discipline the web branch uses) — not for hydration, which no longer
   * needs it, but to reset the UI state the document does not own. */
  hydrated?: SceneInspectorState | null;
}

type AdSchemaBinding = AdLayersBinding & AdHydrationBinding;

/** The one controller these schemas share (this component renders exactly one
 * selection per mount, and the panel remounts keyed on the selected node). */
type AdInspectorController = ReturnType<typeof useInspectorController>;

/**
 * AD4.B step 1: a section's open/closed state, which moved out of
 * `DummySection`'s own `useState(true)` and onto the controller — the panel
 * convention the three bound schemas already follow (`image-inspector.tsx`'s
 * `Section`), so a section's default and its toggle event are stated once for
 * every schema in the panel rather than twice.
 *
 * No new `InspectorSectionId` was needed. The mapping is by CONTENT, so the
 * Layout section here opens exactly as the Layout section of the text and image
 * schemas does: Layout→`layout`, Shape→`shape`, Stroke→`stroke`,
 * Arrange→`arrange`, Layers→`layers`, and Auto Layout→`alignment` (its rows are
 * the alignment/gap/padding set, and it is the id no other ad section uses).
 */
interface DummySectionBinding {
  id: InspectorSectionId;
  open: boolean;
  toggle: () => void;
}

function DummySection({
  children,
  id,
  label,
  open,
  toggle,
}: DummySectionBinding & {
  children: ReactNode;
  label: string;
}) {
  return (
    <InspectorSection key={id} label={label} onOpenChange={toggle} open={open}>
      {children}
    </InspectorSection>
  );
}

// (`StaticSelect` — the one-option, `NO_CHANGE` select — left with AD4.B step
// 2: the Auto Layout section held every select in this file, and its four were
// bound then. `StaticInput` followed with step 3, which bound the last of them.)

/**
 * §1.4 Auto Layout / OQ-2 — the Direction select's two DISPLAY labels.
 *
 * They are the co-founder's ("Row"/"Column"), and the state key's own
 * vocabulary is `InspectorDirection` ("horizontal"/"vertical"), so the mapping
 * lives here — the panel side — and the STATE word is what crosses the write
 * seam. `scene-apply.ts` refuses an off-vocabulary word a second time, where a
 * stored document (JSON, unchecked by these compile-time unions) could reach.
 */
const DIRECTION_OPTIONS = ["Row", "Column"] as const;
const DIRECTION_LABELS = {
  horizontal: "Row",
  vertical: "Column",
} as const satisfies Record<InspectorDirection, (typeof DIRECTION_OPTIONS)[number]>;

function directionValue(label: string): InspectorDirection | null {
  return label === "Row" ? "horizontal" : label === "Column" ? "vertical" : null;
}

/** §1.4 Auto Layout — the Wrap select's two labels over a BOOLEAN state key.
 * The mapping is the panel's for `direction`'s reason exactly, and the write
 * adapter takes the boolean ahead of its string coercion (the §1.0 lock's
 * posture, and the web lane's own Wrap row). */
const WRAP_OPTIONS = ["No wrap", "Wrap"] as const;

/** §1.4 Auto Layout — the Align X/Y selects' five labels. ONE statement of the
 * vocabulary the adapter inverts (`scene-hydrate.ts`'s `LAYOUT_ANCHOR_LABELS`
 * → `scene-apply.ts`'s `LAYOUT_ANCHOR_VALUES`); an anchor absent from this list
 * cannot be picked, and one absent from the adapter's cannot be written. */
const LAYOUT_ANCHOR_OPTIONS = [
  "Start",
  "Center",
  "End",
  "Space between",
  "Stretch",
] as const;

/**
 * §1.4 Auto Layout — AD4.B step 2's bound section.
 *
 * Same rules as `LayoutControls` below: live `state`, dispatch-only setters,
 * typed boxes commit on blur/Enter and selects on change, everything gated on
 * `inert`. The markup is the co-founder's, unchanged — same fields, same
 * labels, same classes; only the values and the handlers are real.
 *
 * The section renders for the AUTO-LAYOUT kind alone (OQ-1's plain Frame
 * suppresses it upstream), which is exactly the kind hydrate states these rows
 * for and the kind `scene-apply.ts` accepts them from — so no control here can
 * be shown over a node whose write would be refused.
 *
 * §1.4/OQ-2: gap/padding TOKENS and fill WEIGHTS stay off this surface. They
 * are not dropped by a numeric commit either — the write spreads what the node
 * holds — so a binding no control here can restate survives a Gap edit.
 */
function AutoLayoutControls({
  controller,
  inert,
  ...section
}: DummySectionBinding & {
  controller: AdInspectorController;
  inert: boolean;
}) {
  const { setNestedValue, setValue, state } = controller;
  return (
    <DummySection label="Auto Layout" {...section}>
      <div className={styles.dummyInspectorStack}>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Direction">
            <InspectorSelect disabled={inert} label="Auto layout direction" onChange={(value) => { const direction = directionValue(value); if (direction) setValue("direction", direction); }} options={DIRECTION_OPTIONS} value={DIRECTION_LABELS[state.direction]} />
          </InspectorField>
          <InspectorField label="Wrap">
            <InspectorSelect disabled={inert} label="Auto layout wrap" onChange={(value) => setValue("wrap", value === "Wrap")} options={WRAP_OPTIONS} value={state.wrap ? "Wrap" : "No wrap"} />
          </InspectorField>
        </div>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Gap">
            <InspectorInput ariaLabel="Auto layout gap" disabled={inert} onCommitValue={(value) => setValue("gap", value)} prefix="G" value={state.gap} />
          </InspectorField>
          <InspectorField label="Grow">
            <InspectorInput ariaLabel="Auto layout grow" disabled={inert} onCommitValue={(value) => setValue("grow", value)} prefix="+" value={state.grow} />
          </InspectorField>
        </div>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Pad T">
            <InspectorInput ariaLabel="Top padding" disabled={inert} onCommitValue={(value) => setNestedValue("padding", "top", value)} prefix="T" value={state.padding.top} />
          </InspectorField>
          <InspectorField label="Pad R">
            <InspectorInput ariaLabel="Right padding" disabled={inert} onCommitValue={(value) => setNestedValue("padding", "right", value)} prefix="R" value={state.padding.right} />
          </InspectorField>
        </div>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Pad B">
            <InspectorInput ariaLabel="Bottom padding" disabled={inert} onCommitValue={(value) => setNestedValue("padding", "bottom", value)} prefix="B" value={state.padding.bottom} />
          </InspectorField>
          <InspectorField label="Pad L">
            <InspectorInput ariaLabel="Left padding" disabled={inert} onCommitValue={(value) => setNestedValue("padding", "left", value)} prefix="L" value={state.padding.left} />
          </InspectorField>
        </div>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Align X">
            <InspectorSelect disabled={inert} label="Horizontal auto layout alignment" onChange={(value) => setValue("alignX", value)} options={LAYOUT_ANCHOR_OPTIONS} value={state.alignX} />
          </InspectorField>
          <InspectorField label="Align Y">
            <InspectorSelect disabled={inert} label="Vertical auto layout alignment" onChange={(value) => setValue("alignY", value)} options={LAYOUT_ANCHOR_OPTIONS} value={state.alignY} />
          </InspectorField>
        </div>
      </div>
    </DummySection>
  );
}

/**
 * §1.4 Shape — AD4.B step 3's bound section: the Fill swatch, and the five
 * radius boxes on the kinds that have corners.
 *
 * FILL goes through the panel's ONE colour row (`useAdColorRow`), so this
 * swatch behaves exactly as the text schema's Color and the canvas schema's
 * Background do: brand swatches are offered FIRST (they ARE the Theme tab,
 * which is the tab `ColorControl` opens on), a brand pick writes a TOKEN
 * (`tokenBackgroundColor`), and a custom hex writes a literal and detaches the
 * binding — §1.6's ratified, informed trade. There is no fixture palette to
 * keep off the write path any more (founder ruling 2026-09-04).
 *
 * A node whose fill is a GRADIENT displays the derivation hydrate already
 * makes for it (its first stop), and every commit against it is refused at the
 * adapter — a bare swatch cannot show a gradient, so a solid write would
 * destroy one the user never saw. The "this leaves your brand palette" note
 * chrome is Gate G-B and is deliberately NOT invented here.
 *
 * RADII render for the rectangle and auto-layout schemas only (the `radii`
 * prop routes it, and the ellipse schema has a Shape section without them —
 * §1.4). They are five plain boxes rather than the `RadiusControls` primitive
 * because that is the markup the co-founder authored for these schemas, and
 * the dummy is presentation truth. The apply rows they commit through already
 * exist and carry no kind guard, exactly so these schemas inherit them.
 */
function ShapeControls({
  controller,
  inert,
  radii,
  ...section
}: DummySectionBinding & {
  controller: AdInspectorController;
  inert: boolean;
  radii: boolean;
}) {
  const { previewValue, setNestedValue, setRadiusAll, setValue, state } = controller;
  const paletteOptions = useScenePaletteOptions();
  const fillRow = useAdColorRow({
    hydratedValue: state.backgroundColor,
    onHex: (hex) => setValue("backgroundColor", hex),
    onPreview: (hex) => previewValue("backgroundColor", hex),
    onToken: (label) => setValue("tokenBackgroundColor", label),
    paletteOptions,
  });
  return (
    <DummySection label="Shape" {...section}>
      <div className={styles.dummyInspectorStack}>
        <InspectorField label="Fill">
          <ColorControl color={fillRow.color} disabled={inert} onColorChange={fillRow.onColorChange} onColorPreview={fillRow.onColorPreview} onTokenChange={fillRow.onTokenChange} options={paletteOptions} showOpacity={false} />
        </InspectorField>
        {radii ? (
          <>
            <InspectorField label="Radius all">
              {/* The controller's own one-event `radius.all` — ONE dispatch
                  that writes all four corners, never four. `state.radius.all`
                  is hydrate's uniform value (or "" when the corners differ),
                  so an empty box is the honest "these corners are not one
                  radius" rather than a zero the node does not have — which is
                  also why an empty commit is dropped here instead of
                  dispatching a value the adapter would refuse anyway. The
                  `true` says an all-corners commit RESTATES the four corners;
                  it is read on the fixture path alone (under live hydration
                  the document answers), where leaving the corner boxes on
                  their old numbers would have the section stating two
                  different radii at once. */}
              <InspectorInput ariaLabel="All corner radius" disabled={inert} onCommitValue={(value) => { if (value.trim() === "") return; setRadiusAll(value, true); }} prefix="R" value={state.radius.all} />
            </InspectorField>
            <div className={styles.dummyInspectorPairGrid}>
              <InspectorField label="Radius TL">
                <InspectorInput ariaLabel="Top left radius" disabled={inert} onCommitValue={(value) => setNestedValue("radius", "topLeft", value)} prefix="TL" value={state.radius.topLeft} />
              </InspectorField>
              <InspectorField label="Radius TR">
                <InspectorInput ariaLabel="Top right radius" disabled={inert} onCommitValue={(value) => setNestedValue("radius", "topRight", value)} prefix="TR" value={state.radius.topRight} />
              </InspectorField>
            </div>
            <div className={styles.dummyInspectorPairGrid}>
              <InspectorField label="Radius BR">
                <InspectorInput ariaLabel="Bottom right radius" disabled={inert} onCommitValue={(value) => setNestedValue("radius", "bottomRight", value)} prefix="BR" value={state.radius.bottomRight} />
              </InspectorField>
              <InspectorField label="Radius BL">
                <InspectorInput ariaLabel="Bottom left radius" disabled={inert} onCommitValue={(value) => setNestedValue("radius", "bottomLeft", value)} prefix="BL" value={state.radius.bottomLeft} />
              </InspectorField>
            </div>
          </>
        ) : null}
      </div>
    </DummySection>
  );
}

/**
 * §1.4 Stroke — AD4.B step 3's bound section, rendered for every schema except
 * the group (the scaffolding already omits it there — OQ-6).
 *
 * The same colour row again, on the stroke paint, and the same two apply rows
 * the text and image schemas already use — including RULING A9, which makes
 * the two fields move TOGETHER: a colour on a strokeless node mints upstream's
 * default width, a width on a colourless one mints upstream's default colour,
 * and a width of exactly 0 clears the stroke. Under live hydration both halves
 * simply read the minted scene back, so the panel never has to mirror a mint.
 *
 * `none` is a real hydrated value here (a strokeless node) and names no token,
 * so it stands as it is — the swatch shows the document's own honest state.
 */
function StrokeControls({
  controller,
  inert,
  ...section
}: DummySectionBinding & {
  controller: AdInspectorController;
  inert: boolean;
}) {
  const { previewValue, setValue, state } = controller;
  const paletteOptions = useScenePaletteOptions();
  const strokeRow = useAdColorRow({
    hydratedValue: state.strokeColor,
    onHex: (hex) => setValue("strokeColor", hex),
    onPreview: (hex) => previewValue("strokeColor", hex),
    onToken: (label) => setValue("tokenStrokeColor", label),
    paletteOptions,
  });
  return (
    <DummySection label="Stroke" {...section}>
      <div className={styles.dummyInspectorStack}>
        <InspectorField label="Color">
          <ColorControl color={strokeRow.color} disabled={inert} onColorChange={strokeRow.onColorChange} onColorPreview={strokeRow.onColorPreview} onTokenChange={strokeRow.onTokenChange} options={paletteOptions} showOpacity={false} />
        </InspectorField>
        <InspectorField label="Width">
          <InspectorInput ariaLabel="Stroke width" disabled={inert} onCommitValue={(value) => setValue("strokeWidth", value)} prefix="W" value={state.strokeWidth} />
        </InspectorField>
      </div>
    </DummySection>
  );
}

/**
 * §1.4/OQ-2: the mode select's three options. `as const satisfies` keeps this
 * list and the state field's own union one vocabulary — a relabel that forgets
 * the other side does not compile — and `sizeMode` below is the narrowing the
 * select's `(value: string)` handler needs, in `isAdDummyInspectorSelection`'s
 * own shape rather than a bare cast. `scene-apply.ts` refuses an off-list label
 * a second time at the write, where a stored document (JSON, unchecked by these
 * compile-time unions) could otherwise reach.
 */
const SIZE_MODE_OPTIONS = ["Fixed", "Hug", "Fill"] as const satisfies readonly InspectorSizeMode[];

function sizeMode(value: string): InspectorSizeMode | null {
  return SIZE_MODE_OPTIONS.includes(value as InspectorSizeMode)
    ? (value as InspectorSizeMode)
    : null;
}

/**
 * §1.4 Layout — AD4.B step 1's bound section.
 *
 * Every row reads `state` (the controller's live composition of the accepted
 * scene) and commits through `setValue`/`setNestedValue`, which DISPATCH and
 * record nothing: a refused write leaves the box showing the document's own
 * value, because the box never left it. Typed rows commit on blur/Enter
 * (`InspectorInput`'s `onCommitValue`); the two selects commit on change.
 *
 * `inert` is G-H's one expression per schema (`locked || inspectorDisabled`) —
 * the node's own lock, which §4 would refuse anyway, OR an agent turn in
 * flight, which must never reach a write at all.
 *
 * The markup is the co-founder's, unchanged: same fields, same labels, same
 * classes. Only the values and the handlers are real now.
 */
function LayoutControls({
  controller,
  inert,
  ...section
}: DummySectionBinding & {
  controller: AdInspectorController;
  inert: boolean;
}) {
  const { setNestedValue, setValue, state } = controller;
  return (
    <DummySection label="Layout" {...section}>
      <div className={styles.dummyInspectorStack}>
        <InspectorField label="Position">
          <div className={styles.dummyInspectorPairGrid}>
            <InspectorInput ariaLabel="X position" disabled={inert} onCommitValue={(value) => setNestedValue("position", "x", value)} prefix="X" value={state.position.x} />
            <InspectorInput ariaLabel="Y position" disabled={inert} onCommitValue={(value) => setNestedValue("position", "y", value)} prefix="Y" value={state.position.y} />
          </div>
        </InspectorField>
        {/* The W/H boxes state the size the node HAS in every mode — the fixed
            value, or the solver's own bounds — which is why they read `width`/
            `height` and not the Fixed-only pair below. A commit flips that axis
            to Fixed (the MVP editor's `emitExtent`; `scene-apply.ts` owns it). */}
        <InspectorField label="Dimensions">
          <div className={styles.dummyInspectorPairGrid}>
            <InspectorInput ariaLabel="Width" disabled={inert} onCommitValue={(value) => setValue("width", value)} prefix="W" value={state.width} />
            <InspectorInput ariaLabel="Height" disabled={inert} onCommitValue={(value) => setValue("height", value)} prefix="H" value={state.height} />
          </div>
        </InspectorField>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Rotate">
            <InspectorInput ariaLabel="Rotation" disabled={inert} onCommitValue={(value) => setValue("rotation", value)} prefix="R" value={state.rotation} />
          </InspectorField>
          <InspectorField label="Opacity">
            {/* OQ-3: the percent is what is shown and typed; the engine's 0–1
                conversion is the write adapter's, at the seam. */}
            <InspectorInput ariaLabel="Opacity" disabled={inert} onCommitValue={(value) => setValue("opacity", value)} prefix="%" value={state.opacity} />
          </InspectorField>
        </div>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Width mode">
            <InspectorSelect disabled={inert} label="Width mode" onChange={(value) => { const mode = sizeMode(value); if (mode) setValue("widthMode", mode); }} options={SIZE_MODE_OPTIONS} value={state.widthMode} />
          </InspectorField>
          <InspectorField label="Height mode">
            <InspectorSelect disabled={inert} label="Height mode" onChange={(value) => { const mode = sizeMode(value); if (mode) setValue("heightMode", mode); }} options={SIZE_MODE_OPTIONS} value={state.heightMode} />
          </InspectorField>
        </div>
        {/* OQ-2: the "fixed" inputs exist only in Fixed mode — the MVP editor's
            own `SizingSection` rule, and hydration states the empty string for
            them in every other mode, so rendering them would show a blank box
            beside a mode that has no fixed value. They commit the SAME
            `width`/`height` property as the Dimensions pair above: one write
            path, so the two controls cannot disagree about what a size means. */}
        {state.widthMode === "Fixed" || state.heightMode === "Fixed" ? (
          <div className={styles.dummyInspectorPairGrid}>
            {state.widthMode === "Fixed" ? (
              <InspectorField label="Width fixed">
                <InspectorInput ariaLabel="Fixed width" disabled={inert} onCommitValue={(value) => setValue("width", value)} prefix="W" value={state.widthFixed} />
              </InspectorField>
            ) : null}
            {state.heightMode === "Fixed" ? (
              <InspectorField label="Height fixed">
                <InspectorInput ariaLabel="Fixed height" disabled={inert} onCommitValue={(value) => setValue("height", value)} prefix="H" value={state.heightFixed} />
              </InspectorField>
            ) : null}
          </div>
        ) : null}
      </div>
    </DummySection>
  );
}

/**
 * §1.5 Arrange — AD4.B step 4's bound section.
 *
 * The five action tables below gained a THIRD column: the typed action the
 * button performs, so the wiring is a lookup rather than a match on a human
 * label. The labels, the icons, the grids and the column counts are the
 * co-founder's, unchanged.
 *
 * The group row still renders for the GROUP schema alone — that is the
 * scaffolding's own routing (`groupActions`) and step 4 does not touch it. It
 * is a real limit and is recorded rather than worked around: ⌘G reaches the
 * same action from every schema, so a multi-node selection under a non-group
 * primary is still groupable by keyboard.
 */
const LAYER_ACTIONS = [
  ["Bring to front", "layer-front", "front"],
  ["Bring forward", "layer-up", "forward"],
  ["Send backward", "layer-down", "backward"],
  ["Send to back", "layer-back", "back"],
] as const satisfies readonly (readonly [string, InspectorIconName, ZOrderAction])[];

const HORIZONTAL_ALIGNMENT_ACTIONS = [
  ["Align left", "align-start-vertical", "left"],
  ["Align horizontal center", "align-center-vertical", "center-h"],
  ["Align right", "align-end-vertical", "right"],
] as const satisfies readonly (readonly [string, InspectorIconName, AlignMode])[];

const VERTICAL_ALIGNMENT_ACTIONS = [
  ["Align top", "align-start-horizontal", "top"],
  ["Align vertical center", "align-center-horizontal", "middle-v"],
  ["Align bottom", "align-end-horizontal", "bottom"],
] as const satisfies readonly (readonly [string, InspectorIconName, AlignMode])[];

const DISTRIBUTION_ACTIONS = [
  ["Distribute horizontally", "align-horizontal-distribute-center", "horizontal"],
  ["Distribute vertically", "align-vertical-distribute-center", "vertical"],
] as const satisfies readonly (readonly [string, InspectorIconName, DistributeAxis])[];

const GROUP_ACTIONS = [
  ["Group selection", "group", "group"],
  ["Ungroup selection", "ungroup", "ungroup"],
] as const satisfies readonly (readonly [string, InspectorIconName, "group" | "ungroup"])[];

/**
 * G-H (AD4.R-10): the whole grid is OPERATIONS on the document, so `inert`
 * (locked node / in-flight agent turn) closes every button in it, and the
 * per-action `enabled` predicate closes the ones this selection cannot perform.
 *
 * `onAction` ABSENT is the fixture/dummy path: the buttons render exactly as
 * they shipped — no handler, and `enabled` left saying yes, so nothing dims on
 * a panel that was never going to write.
 *
 * A disabled button also SAYS SO: it wears the G-H-approved
 * `.inspectorControlDisabled` (the sheet's own 0.45), the same treatment every
 * other disabled inspector control already carries — reused, never re-authored.
 * This grid paints nothing of its own (its buttons carry the border and fill),
 * so the modifier rides each button rather than the wrapper, exactly as the
 * layer rows' lock/visibility buttons already do.
 */
function DummyIconButtons<Action extends string>({
  actions,
  columns,
  enabled,
  inert,
  onAction,
}: {
  actions: readonly (readonly [string, InspectorIconName, Action])[];
  columns: 2 | 3 | 4;
  enabled: (action: Action) => boolean;
  inert: boolean;
  onAction?: (action: Action) => void;
}) {
  return (
    <div
      className={styles.dummyInspectorActionGrid}
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
    >
      {actions.map(([label, icon, action]) => {
        const off = inert || !enabled(action);
        return (
          <button
            aria-label={label}
            className={off ? styles.inspectorControlDisabled : ""}
            disabled={off}
            key={label}
            onClick={onAction ? () => onAction(action) : undefined}
            type="button"
          >
            <InspectorIcon name={icon} size={14} />
          </button>
        );
      })}
    </div>
  );
}

/** Absent binding ⇒ every action reads as available, which with no `onAction`
 * leaves the fixture path's buttons exactly as inert and exactly as bright as
 * they shipped. */
const ALWAYS = () => true;

function ArrangeControls({
  arrange,
  groupActions = false,
  inert,
  ...section
}: DummySectionBinding & {
  arrange?: SceneArrangeBinding;
  groupActions?: boolean;
  inert: boolean;
}) {
  const enablement = arrange?.enablement;
  return (
    <DummySection label="Arrange" {...section}>
      <div className={styles.dummyInspectorStack}>
        <InspectorField label="Layer">
          <DummyIconButtons
            actions={LAYER_ACTIONS}
            columns={4}
            enabled={enablement ? (action) => enablement.zOrder[action] : ALWAYS}
            inert={inert}
            onAction={arrange?.zOrder}
          />
        </InspectorField>
        <InspectorField label="Alignment">
          <div className={styles.dummyInspectorAlignmentGroups}>
            <DummyIconButtons
              actions={HORIZONTAL_ALIGNMENT_ACTIONS}
              columns={3}
              enabled={enablement ? () => enablement.align : ALWAYS}
              inert={inert}
              onAction={arrange?.align}
            />
            <DummyIconButtons
              actions={VERTICAL_ALIGNMENT_ACTIONS}
              columns={3}
              enabled={enablement ? () => enablement.align : ALWAYS}
              inert={inert}
              onAction={arrange?.align}
            />
          </div>
        </InspectorField>
        <InspectorField label="Distribution">
          <DummyIconButtons
            actions={DISTRIBUTION_ACTIONS}
            columns={2}
            enabled={enablement ? () => enablement.distribute : ALWAYS}
            inert={inert}
            onAction={arrange?.distribute}
          />
        </InspectorField>
        {groupActions ? (
          <InspectorField label="Group">
            <DummyIconButtons
              actions={GROUP_ACTIONS}
              columns={2}
              enabled={enablement ? (action) => enablement[action] : ALWAYS}
              inert={inert}
              onAction={
                arrange
                  ? (action) =>
                      action === "group" ? arrange.group() : arrange.ungroup()
                  : undefined
              }
            />
          </InspectorField>
        ) : null}
      </div>
    </DummySection>
  );
}

const LAYER_ROWS: Record<
  AdDummyInspectorSelection,
  readonly {
    icon: Extract<InspectorIconName, "ellipse" | "layout-template" | "rectangle" | "square-dashed">;
    label: string;
    selection: AdDummyInspectorSelection;
  }[]
> = {
  "auto-layout": [
    { icon: "layout-template", label: "Auto layout", selection: "auto-layout" },
    { icon: "rectangle", label: "Rectangle", selection: "rectangle" },
    { icon: "ellipse", label: "Ellipse", selection: "ellipse" },
  ],
  rectangle: [
    { icon: "rectangle", label: "Rectangle", selection: "rectangle" },
  ],
  ellipse: [
    { icon: "ellipse", label: "Ellipse", selection: "ellipse" },
  ],
  group: [
    { icon: "square-dashed", label: "Group", selection: "group" },
    { icon: "rectangle", label: "Rectangle", selection: "rectangle" },
    { icon: "ellipse", label: "Ellipse", selection: "ellipse" },
  ],
};

/**
 * AD2.6: what a caller supplies to drive the Layers panel from the REAL scene
 * instead of the dummy's fixture rows. Every field is optional and absent means
 * "keep the fixture tree", so the panel is unchanged until AD2.7 binds the
 * session (the AD0.4 `fontOptions?` precedent).
 *
 * It lives in this file, not in `image-inspector.tsx`, only because the import
 * already runs this way (image-inspector → ad-dummy-inspectors) and the reverse
 * would be a cycle.
 */
export interface AdLayersBinding {
  /** The real rows, already expansion-filtered by `sceneLayerRows`. */
  layers?: readonly SceneLayerRow[];
  /** A click on a selectable row. `additive` is the §1.7 shift/⌘ modifier —
   * the caller accumulates ids; this panel never owns the selection. */
  onSelectLayer?: (nodeId: string, additive: boolean) => void;
  /** A click on a container row's chevron area (the whole row, as the dummy's
   * own group row does it). The caller owns the expansion set that produced
   * `layers` — the dummy's `useInspectorLayerTree` — so the toggle goes back to
   * it rather than forking a second source of truth here. */
  onToggleLayer?: (nodeId: string) => void;
  /** The whole additive selection; `[0]` is the primary (§1.8: the inspector
   * renders the primary's schema). Membership drives the row's active/accented
   * treatment. */
  selectedIds?: readonly string[];
}

/**
 * AD2.6: the real scene tree, rendered with the dummy's own `InspectorLayerRow`
 * — same primitive, same props, same class names as the fixture rows it
 * replaces. Only the data source changed.
 *
 * §1.7's `accented` active treatment marks every member of the additive
 * selection (not just the primary); auto-scroll-to-primary is the primitive's
 * own `scrollIntoView` on `active`. A row whose node has no v1 schema (§5's
 * line / vector / instance) renders with no click handler at all — a dead
 * click, not a hidden layer.
 *
 * `row.fillSwatch` is deliberately NOT rendered: §1.7 asks for a fill chip on
 * Rect/Ellipse rows, but `InspectorLayerRow` has no swatch slot and inventing
 * one is founder-gated chrome (the dummy is presentation truth). The value is
 * computed and carried so the chip is a markup change and nothing more when the
 * row design lands.
 */
export function AdSceneLayers({
  layers = [],
  onSelectLayer,
  onToggleLayer,
  selectedIds = [],
}: AdLayersBinding) {
  // Founder 2026-10-19: Layers fills the panel to its bottom (or the chat box), like the site editor.
  return (
    <LayerList>
      {layers.map((row) => {
        const active = selectedIds.includes(row.nodeId);
        const clickable = row.selectable || row.expandable;
        return (
          <InspectorLayerRow
            accented={active}
            active={active}
            depth={row.depth}
            expandable={row.expandable}
            expanded={row.expandable ? row.expanded : undefined}
            icon={row.icon}
            key={row.nodeId}
            label={row.label}
            onClick={
              clickable
                ? (event) => {
                    if (row.expandable) onToggleLayer?.(row.nodeId);
                    if (row.selectable) {
                      onSelectLayer?.(
                        row.nodeId,
                        event.shiftKey || event.metaKey || event.ctrlKey,
                      );
                    }
                  }
                : undefined
            }
          />
        );
      })}
    </LayerList>
  );
}

function LayersControls({
  id,
  layers,
  onSelectionChange,
  open,
  selection,
  toggle,
  ...binding
}: AdLayersBinding &
  DummySectionBinding & {
    onSelectionChange: (selection: ChatShellInspectorSelection) => void;
    selection: AdDummyInspectorSelection;
  }) {
  const section = { id, open, toggle };
  // AD2.6: the real tree replaces the per-schema fixture rows below; the
  // fixture branch is untouched and still renders until AD2.7 feeds `layers`.
  if (layers) {
    return (
      <DummySection label="Layers" {...section}>
        <AdSceneLayers layers={layers} {...binding} />
      </DummySection>
    );
  }

  return (
    <DummySection label="Layers" {...section}>
      <div className={styles.layerList}>
        {LAYER_ROWS[selection].map((row) => {
          const active = row.selection === selection;
          return (
            <InspectorLayerRow
              accented={active}
              active={active}
              icon={row.icon}
              key={`${selection}-${row.label}`}
              label={row.label}
              onClick={() => onSelectionChange(row.selection)}
            />
          );
        })}
      </div>
    </DummySection>
  );
}

export function AdDummyInspector({
  addressing,
  arrange,
  hydrated,
  inspectorDisabled = false,
  locked = false,
  onSelectionChange,
  selection,
  suppressAutoLayoutSection = false,
  ...binding
}: AdSchemaBinding & {
  /** §1.5 (AD4.B step 4): the session's Arrange actions and their enablement.
   * Absent (the dummy fixture path) leaves the section's buttons exactly as
   * inert as they shipped. */
  arrange?: SceneArrangeBinding;
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  selection: AdDummyInspectorSelection;
  /** AD2.4/OQ-1: a plain Frame routes to this auto-layout schema but has no
   * auto layout, so its Auto Layout section is absent (mapping contract §2:
   * hidden = absent). Every other section still applies. */
  suppressAutoLayoutSection?: boolean;
}) {
  // G-H (AD4.R-10): one expression for every write control below — the node's
  // own lock OR an in-flight agent turn. The Layers section is navigation and
  // takes neither.
  const inert = locked || inspectorDisabled;
  // ONE controller for the whole component: it renders exactly one selection
  // per mount, and the panel remounts keyed on the selected node id.
  //
  // `initial` is the hydrated snapshot under this schema's own defaults — the
  // text schema's `fontWeight` and the canvas schema's `sizePreset` pattern
  // (AD4.R: explicit defaults live in the SCHEMA, not the adapter). It is
  // rebuilt from the live prop every render, which is what makes it the live
  // merge source too.
  //
  // AD4.B steps 2 and 3 need exactly THREE of them, and only for the FIXTURE
  // path: the Auto Layout section's Wrap and Pad boxes read `wrap`/`padding`
  // and the Shape section's five boxes read `radius`, keys the web lane
  // authored long before this panel existed, so `DEFAULT_STATE` seeds them with
  // the WEB dummy's values (`true`, `4/8/8/4`, `all: "0"` beside corners of
  // `"4"`) rather than the ad scaffolding's ("No wrap", zeros, zeros).
  // Restating them here keeps the mock rendering what it rendered before AND
  // leaves the shared defaults — and so the web inspector — untouched. On a
  // real node they are never seen: ruling L10 makes hydration state wrap and
  // padding for every auto-layout node and `scene-hydrate` states all five
  // radius keys as one object, and `hydrated` spreads last.
  const initial = {
    padding: FIXTURE_PADDING,
    radius: FIXTURE_RADIUS,
    wrap: false,
    ...hydrated,
  };
  const controller = useInspectorController([], selection, initial, addressing, {
    // AD4.R: live only when a real scene is behind the panel — the dummy
    // fixture path (no hydration) stays the interactive mock it shipped as.
    // The flag reads the `hydrated` PROP, never `initial`, which is an object
    // either way.
    liveHydration: hydrated != null,
  });
  const { state, toggleSection } = controller;
  const section = (id: InspectorSectionId): DummySectionBinding => ({
    id,
    open: state.openSections[id],
    toggle: () => toggleSection(id),
  });

  return (
    <>
      {selection === "auto-layout" && !suppressAutoLayoutSection ? (
        <AutoLayoutControls controller={controller} inert={inert} {...section("alignment")} />
      ) : null}
      {/* OQ-6: the GROUP schema renders NEITHER a Shape nor a Stroke section —
          the scaffolding omits them and step 3 keeps it that way. The adapter
          still maps both rows for a group (its kind condition is hydrate's, and
          hydrate states a group's fill and stroke like any other kind); hiding
          a control is this panel's decision, not the write seam's. */}
      {selection === "auto-layout" || selection === "rectangle" ? (
        <ShapeControls controller={controller} inert={inert} radii {...section("shape")} />
      ) : null}
      {selection === "ellipse" ? (
        <ShapeControls controller={controller} inert={inert} radii={false} {...section("shape")} />
      ) : null}
      {selection !== "group" ? (
        <StrokeControls controller={controller} inert={inert} {...section("stroke")} />
      ) : null}
      <LayoutControls controller={controller} inert={inert} {...section("layout")} />
      <ArrangeControls arrange={arrange} groupActions={selection === "group"} inert={inert} {...section("arrange")} />
      <LayersControls
        onSelectionChange={onSelectionChange}
        selection={selection}
        {...section("layers")}
        {...binding}
      />
    </>
  );
}
