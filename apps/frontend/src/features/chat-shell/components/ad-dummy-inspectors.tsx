"use client";

import type { ReactNode } from "react";
import type { SceneInspectorState } from "@/features/design-editor/adapter/scene-hydrate";
import type { SceneLayerRow } from "@/features/design-editor/adapter/scene-layers";
import type { ChatShellInspectorSelection } from "../model/chat-shell";
import {
  useInspectorController,
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
// same number survives as `DEFAULT_STATE`'s seed for the fixture path.)
const NO_CHANGE = () => {};

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

function StaticInput({
  ariaLabel,
  prefix,
  value = STATIC_ZERO,
}: {
  ariaLabel: string;
  prefix: string;
  value?: string;
}) {
  return (
    <InspectorInput
      ariaLabel={ariaLabel}
      onChange={NO_CHANGE}
      prefix={prefix}
      readOnly
      value={value}
    />
  );
}

function StaticSelect({
  ariaLabel,
  value,
}: {
  ariaLabel: string;
  value: string;
}) {
  return (
    <InspectorSelect
      label={ariaLabel}
      onChange={NO_CHANGE}
      options={[value]}
      value={value}
    />
  );
}

function AutoLayoutControls(section: DummySectionBinding) {
  return (
    <DummySection label="Auto Layout" {...section}>
      <div className={styles.dummyInspectorStack}>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Direction">
            <StaticSelect ariaLabel="Auto layout direction" value="Row" />
          </InspectorField>
          <InspectorField label="Wrap">
            <StaticSelect ariaLabel="Auto layout wrap" value="No wrap" />
          </InspectorField>
        </div>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Gap">
            <StaticInput ariaLabel="Auto layout gap" prefix="G" />
          </InspectorField>
          <InspectorField label="Grow">
            <StaticInput ariaLabel="Auto layout grow" prefix="+" />
          </InspectorField>
        </div>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Pad T">
            <StaticInput ariaLabel="Top padding" prefix="T" />
          </InspectorField>
          <InspectorField label="Pad R">
            <StaticInput ariaLabel="Right padding" prefix="R" />
          </InspectorField>
        </div>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Pad B">
            <StaticInput ariaLabel="Bottom padding" prefix="B" />
          </InspectorField>
          <InspectorField label="Pad L">
            <StaticInput ariaLabel="Left padding" prefix="L" />
          </InspectorField>
        </div>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Align X">
            <StaticSelect ariaLabel="Horizontal auto layout alignment" value="Space between" />
          </InspectorField>
          <InspectorField label="Align Y">
            <StaticSelect ariaLabel="Vertical auto layout alignment" value="Center" />
          </InspectorField>
        </div>
      </div>
    </DummySection>
  );
}

function ShapeControls({ radii, ...section }: DummySectionBinding & { radii: boolean }) {
  return (
    <DummySection label="Shape" {...section}>
      <div className={styles.dummyInspectorStack}>
        <InspectorField label="Fill">
          <ColorControl none noneAriaLabel="Fill is none" showOpacity={false} />
        </InspectorField>
        {radii ? (
          <>
            <InspectorField label="Radius all">
              <StaticInput ariaLabel="All corner radius" prefix="R" />
            </InspectorField>
            <div className={styles.dummyInspectorPairGrid}>
              <InspectorField label="Radius TL">
                <StaticInput ariaLabel="Top left radius" prefix="TL" />
              </InspectorField>
              <InspectorField label="Radius TR">
                <StaticInput ariaLabel="Top right radius" prefix="TR" />
              </InspectorField>
            </div>
            <div className={styles.dummyInspectorPairGrid}>
              <InspectorField label="Radius BR">
                <StaticInput ariaLabel="Bottom right radius" prefix="BR" />
              </InspectorField>
              <InspectorField label="Radius BL">
                <StaticInput ariaLabel="Bottom left radius" prefix="BL" />
              </InspectorField>
            </div>
          </>
        ) : null}
      </div>
    </DummySection>
  );
}

function StrokeControls(section: DummySectionBinding) {
  return (
    <DummySection label="Stroke" {...section}>
      <div className={styles.dummyInspectorStack}>
        <InspectorField label="Color">
          <ColorControl none noneAriaLabel="Stroke color is none" showOpacity={false} />
        </InspectorField>
        <InspectorField label="Width">
          <StaticInput ariaLabel="Stroke width" prefix="W" value="1" />
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

const LAYER_ACTIONS = [
  ["Bring to front", "layer-front"],
  ["Bring forward", "layer-up"],
  ["Send backward", "layer-down"],
  ["Send to back", "layer-back"],
] as const satisfies readonly (readonly [string, InspectorIconName])[];

const HORIZONTAL_ALIGNMENT_ACTIONS = [
  ["Align left", "align-start-vertical"],
  ["Align horizontal center", "align-center-vertical"],
  ["Align right", "align-end-vertical"],
] as const satisfies readonly (readonly [string, InspectorIconName])[];

const VERTICAL_ALIGNMENT_ACTIONS = [
  ["Align top", "align-start-horizontal"],
  ["Align vertical center", "align-center-horizontal"],
  ["Align bottom", "align-end-horizontal"],
] as const satisfies readonly (readonly [string, InspectorIconName])[];

const DISTRIBUTION_ACTIONS = [
  ["Distribute horizontally", "align-horizontal-distribute-center"],
  ["Distribute vertically", "align-vertical-distribute-center"],
] as const satisfies readonly (readonly [string, InspectorIconName])[];

const GROUP_ACTIONS = [
  ["Group selection", "group"],
  ["Ungroup selection", "ungroup"],
] as const satisfies readonly (readonly [string, InspectorIconName])[];

function DummyIconButtons({
  actions,
  columns,
}: {
  actions: readonly (readonly [string, InspectorIconName])[];
  columns: 2 | 3 | 4;
}) {
  return (
    <div
      className={styles.dummyInspectorActionGrid}
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
    >
      {actions.map(([label, icon]) => (
        <button aria-label={label} key={label} type="button">
          <InspectorIcon name={icon} size={14} />
        </button>
      ))}
    </div>
  );
}

function ArrangeControls({
  groupActions = false,
  ...section
}: DummySectionBinding & { groupActions?: boolean }) {
  return (
    <DummySection label="Arrange" {...section}>
      <div className={styles.dummyInspectorStack}>
        <InspectorField label="Layer">
          <DummyIconButtons actions={LAYER_ACTIONS} columns={4} />
        </InspectorField>
        <InspectorField label="Alignment">
          <div className={styles.dummyInspectorAlignmentGroups}>
            <DummyIconButtons actions={HORIZONTAL_ALIGNMENT_ACTIONS} columns={3} />
            <DummyIconButtons actions={VERTICAL_ALIGNMENT_ACTIONS} columns={3} />
          </div>
        </InspectorField>
        <InspectorField label="Distribution">
          <DummyIconButtons actions={DISTRIBUTION_ACTIONS} columns={2} />
        </InspectorField>
        {groupActions ? (
          <InspectorField label="Group">
            <DummyIconButtons actions={GROUP_ACTIONS} columns={2} />
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
  return (
    <div className={styles.layerList}>
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
    </div>
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
  hydrated,
  inspectorDisabled = false,
  locked = false,
  onSelectionChange,
  selection,
  suppressAutoLayoutSection = false,
  ...binding
}: AdSchemaBinding & {
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
  // `initial` is the hydrated snapshot alone — these four schemas carry no
  // schema-local default of their own (unlike text's `fontWeight` or canvas's
  // `sizePreset`), because hydration states every Layout key for every kind
  // (the AD4.R rule at `hydrateSceneInspectorState`). It is rebuilt from the
  // live prop every render, which is what makes it the live merge source too.
  const initial = { ...hydrated };
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
        <AutoLayoutControls {...section("alignment")} />
      ) : null}
      {selection === "auto-layout" || selection === "rectangle" ? (
        <ShapeControls radii {...section("shape")} />
      ) : null}
      {selection === "ellipse" ? <ShapeControls radii={false} {...section("shape")} /> : null}
      {selection !== "group" ? <StrokeControls {...section("stroke")} /> : null}
      <LayoutControls controller={controller} inert={inert} {...section("layout")} />
      <ArrangeControls groupActions={selection === "group"} {...section("arrange")} />
      <LayersControls
        onSelectionChange={onSelectionChange}
        selection={selection}
        {...section("layers")}
        {...binding}
      />
    </>
  );
}
