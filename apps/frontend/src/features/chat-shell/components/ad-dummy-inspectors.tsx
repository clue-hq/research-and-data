"use client";

import { useState, type ReactNode } from "react";
import type { SceneLayerRow } from "@/features/design-editor/adapter/scene-layers";
import type { ChatShellInspectorSelection } from "../model/chat-shell";
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
const STATIC_SIZE = "100";
const NO_CHANGE = () => {};

function DummySection({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  const [open, setOpen] = useState(true);

  return (
    <InspectorSection label={label} onOpenChange={setOpen} open={open}>
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

function AutoLayoutControls() {
  return (
    <DummySection label="Auto Layout">
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

function ShapeControls({ radii }: { radii: boolean }) {
  return (
    <DummySection label="Shape">
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

function StrokeControls() {
  return (
    <DummySection label="Stroke">
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

function LayoutControls() {
  return (
    <DummySection label="Layout">
      <div className={styles.dummyInspectorStack}>
        <InspectorField label="Position">
          <div className={styles.dummyInspectorPairGrid}>
            <StaticInput ariaLabel="X position" prefix="X" />
            <StaticInput ariaLabel="Y position" prefix="Y" />
          </div>
        </InspectorField>
        <InspectorField label="Dimensions">
          <div className={styles.dummyInspectorPairGrid}>
            <StaticInput ariaLabel="Width" prefix="W" value={STATIC_SIZE} />
            <StaticInput ariaLabel="Height" prefix="H" value={STATIC_SIZE} />
          </div>
        </InspectorField>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Rotate">
            <StaticInput ariaLabel="Rotation" prefix="R" />
          </InspectorField>
          <InspectorField label="Opacity">
            <StaticInput ariaLabel="Opacity" prefix="%" value="100" />
          </InspectorField>
        </div>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Width mode">
            <StaticSelect ariaLabel="Width mode" value="Fixed" />
          </InspectorField>
          <InspectorField label="Height mode">
            <StaticSelect ariaLabel="Height mode" value="Fixed" />
          </InspectorField>
        </div>
        <div className={styles.dummyInspectorPairGrid}>
          <InspectorField label="Width fixed">
            <StaticInput ariaLabel="Fixed width" prefix="W" value={STATIC_SIZE} />
          </InspectorField>
          <InspectorField label="Height fixed">
            <StaticInput ariaLabel="Fixed height" prefix="H" value={STATIC_SIZE} />
          </InspectorField>
        </div>
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

function ArrangeControls({ groupActions = false }: { groupActions?: boolean }) {
  return (
    <DummySection label="Arrange">
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
  layers,
  onSelectionChange,
  selection,
  ...binding
}: AdLayersBinding & {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  selection: AdDummyInspectorSelection;
}) {
  // AD2.6: the real tree replaces the per-schema fixture rows below; the
  // fixture branch is untouched and still renders until AD2.7 feeds `layers`.
  if (layers) {
    return (
      <DummySection label="Layers">
        <AdSceneLayers layers={layers} {...binding} />
      </DummySection>
    );
  }

  return (
    <DummySection label="Layers">
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
  onSelectionChange,
  selection,
  ...binding
}: AdLayersBinding & {
  onSelectionChange: (selection: ChatShellInspectorSelection) => void;
  selection: AdDummyInspectorSelection;
}) {
  return (
    <>
      {selection === "auto-layout" ? <AutoLayoutControls /> : null}
      {selection === "auto-layout" || selection === "rectangle" ? (
        <ShapeControls radii />
      ) : null}
      {selection === "ellipse" ? <ShapeControls radii={false} /> : null}
      {selection !== "group" ? <StrokeControls /> : null}
      <LayoutControls />
      <ArrangeControls groupActions={selection === "group"} />
      <LayersControls
        onSelectionChange={onSelectionChange}
        selection={selection}
        {...binding}
      />
    </>
  );
}
