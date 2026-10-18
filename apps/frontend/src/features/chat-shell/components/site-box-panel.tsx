"use client";

import { useEffect, useRef, useState } from "react";
import type { StyleOverride } from "@clue/site-kit/edits";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import { ColorControl, InspectorField, InspectorInput, InspectorSection, RadiusControls, SegmentedControl, TextAlignment } from "./inspector-primitives";
import { BOX_RANGE, WIDTH_RANGE, type RadiusMode, type WidthMode } from "./site-button-panel.logic";
import { ALIGN_ROOM_NOTE, BOX_GAP_NOTE, boxPanelPatch, boxPanelValues, boxTargets, type BoxPanelChange, type BoxTarget } from "./site-box-panel.logic";
import { SiteArrangeSection } from "./site-arrange-section";
import styles from "./chat-shell.module.css";

/** As in the text panel: a custom colour dragged across the picker is written once the pointer rests. */
const COLOR_DRAG_SETTLE_MS = 400;
const CORNERS = ["topLeft", "topRight", "bottomRight", "bottomLeft"] as const;

const RADIUS_MODES: { label: string; value: RadiusMode }[] = [
  { label: "Pill", value: "pill" },
  { label: "Number", value: "number" },
  { label: "Custom", value: "custom" },
];
const WIDTH_MODES: { label: string; value: WidthMode }[] = [
  { label: "Fit", value: "fit" },
  { label: "Fill", value: "fill" },
  { label: "Fixed", value: "fixed" },
];
const ALIGN_TO = { center: "center", left: "start", right: "end" } as const;
const ALIGN_FROM = { center: "center", end: "right", start: "left" } as const;

type PanelSection = "fill" | "stroke" | "layout" | "arrange";

/** The section a change belongs to. */
function sectionOf(change: BoxPanelChange): PanelSection {
  if (change.kind.startsWith("fill")) return "fill";
  if (change.kind === "contentAlign") return "arrange";
  if (change.kind.startsWith("padding") || change.kind.startsWith("width") || change.kind === "gap") return "layout";
  return "stroke";
}

function Note({ note, section }: { note: { section: PanelSection; text: string } | null; section: PanelSection }) {
  return note?.section === section ? (
    <p className={styles.inspectorStatusNote} role="status">
      {note.text}
    </p>
  ) : null;
}

/** Why an input was not taken, said under the section (the field keeps showing the current value). */
function refusalNote(change: BoxPanelChange): string {
  switch (change.kind) {
    case "fillHex":
    case "strokeHex":
      return "Use a six-digit hex colour, like #0F59B0.";
    case "fillOpacity":
    case "strokeOpacity":
      return "Opacity must be a whole number from 0 to 100.";
    case "width":
      return `Width must be a number from ${WIDTH_RANGE.min} to ${WIDTH_RANGE.max}.`;
    default:
      return `Use a number from ${BOX_RANGE.min} to ${BOX_RANGE.max}.`;
  }
}

/**
 * The site element inspector's box sections, in the mockup's order: Fill, Stroke with its corner
 * radius, Layout (padding, and for a box its gap, then width), and for a box Arrange (move up or down,
 * content alignment). `mode`: a button's box (plan 3; its words are the text panel's, its link the Link
 * row's), any other box (plan 4), or the selected section's own box (ruling R2: Fill and Stroke on its
 * outer box, Layout and content alignment on its inner box, Width disabled). Every change is that key's
 * whole new override, written by the session as one save. While the agent-run lock holds, everything is
 * disabled.
 */
export function SiteBoxPanel({ binding, mode }: { binding: SiteInspectorBinding; mode: "button" | "box" | "section" }) {
  const targets = boxTargets({
    element: mode === "section" ? null : binding.element,
    elementOverride: binding.elementOverride,
    sectionBox: binding.sectionBox,
    sectionBoxOverrides: binding.sectionBoxOverrides,
  });
  const [fillOpen, setFillOpen] = useState(true);
  const [strokeOpen, setStrokeOpen] = useState(true);
  const [layoutOpen, setLayoutOpen] = useState(true);
  // A refusal is said under the section whose control refused it.
  const [note, setNote] = useState<{ section: PanelSection; text: string } | null>(null);
  // Each key's override as last written, so a quick second change builds on the first.
  const latest = useRef<Record<string, StyleOverride | null>>({});
  const paintKey = targets?.paint.key;
  const layoutKey = targets?.layout.key;
  const paintOverride = targets?.paint.override ?? null;
  const layoutOverride = targets?.layout.override ?? null;
  useEffect(() => {
    if (paintKey) latest.current[paintKey] = paintOverride;
    if (layoutKey) latest.current[layoutKey] = layoutOverride;
  }, [paintKey, layoutKey, paintOverride, layoutOverride]);
  const pendingColor = useRef<{ change: BoxPanelChange; target: BoxTarget; timer: ReturnType<typeof setTimeout> } | null>(null);

  const commit = (change: BoxPanelChange, target: BoxTarget) => {
    if (binding.disabled) return;
    const current = target.key in latest.current ? latest.current[target.key] : target.override;
    const next = boxPanelPatch(current, change, target.box);
    if (!next) {
      setNote({ section: sectionOf(change), text: refusalNote(change) });
      return;
    }
    setNote(null);
    if (JSON.stringify(next) === JSON.stringify(current ?? {})) return;
    latest.current[target.key] = next;
    binding.onStyleCommit(target.key, next);
  };
  const flushColor = () => {
    const pending = pendingColor.current;
    if (!pending) return;
    clearTimeout(pending.timer);
    pendingColor.current = null;
    commit(pending.change, pending.target);
  };
  const commitColorSoon = (change: BoxPanelChange, target: BoxTarget) => {
    if (pendingColor.current && pendingColor.current.change.kind !== change.kind) flushColor();
    if (pendingColor.current) clearTimeout(pendingColor.current.timer);
    pendingColor.current = { change, target, timer: setTimeout(flushColor, COLOR_DRAG_SETTLE_MS) };
  };
  useEffect(() => () => flushColor(), []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!targets) return null;
  const { layout, paint } = targets;
  const values = boxPanelValues(paint.override, paint.box, binding.palette);
  const layoutValues = boxPanelValues(layout.override, layout.box, binding.palette);
  const allCorners = values.corners.every((corner) => corner === values.corners[0]) ? values.corners[0] : "";
  const radiusValues = {
    all: allCorners,
    bottomLeft: values.corners[3],
    bottomRight: values.corners[2],
    topLeft: values.corners[0],
    topRight: values.corners[1],
  };
  const isBox = mode !== "button";
  const widthOff = binding.disabled || layout.widthNote !== null;

  return (
    <fieldset disabled={binding.disabled} style={{ display: "contents" }}>
      <InspectorSection label="Fill" onOpenChange={setFillOpen} open={fillOpen}>
        <InspectorField label="Color">
          <ColorControl
            color={values.fill}
            disabled={binding.disabled}
            onColorChange={(hex) => commitColorSoon({ hex, kind: "fillHex" }, paint)}
            onOpacityChange={(value) => commit({ kind: "fillOpacity", value }, paint)}
            onTokenChange={(token) => commit({ kind: "fillToken", token }, paint)}
            opacity={values.fillOpacity}
            options={binding.palette}
          />
        </InspectorField>
        {mode === "button" ? (
          <p className={styles.inspectorStatusNote} role="status">
            A fill or stroke set here also holds when the button is hovered or focused.
          </p>
        ) : null}
        <Note note={note} section="fill" />
      </InspectorSection>
      <InspectorSection label="Stroke" onOpenChange={setStrokeOpen} open={strokeOpen}>
        <InspectorField label="Color">
          <ColorControl
            color={values.stroke}
            disabled={binding.disabled}
            onColorChange={(hex) => commitColorSoon({ hex, kind: "strokeHex" }, paint)}
            onOpacityChange={(value) => commit({ kind: "strokeOpacity", value }, paint)}
            onTokenChange={(token) => commit({ kind: "strokeToken", token }, paint)}
            opacity={values.strokeOpacity}
            options={binding.palette}
          />
        </InspectorField>
        <InspectorField label="Width">
          <InspectorInput
            ariaLabel="Stroke width"
            disabled={binding.disabled}
            onCommitValue={(value) => commit({ kind: "strokeWidth", value }, paint)}
            suffix="px"
            value={values.strokeWidth}
          />
        </InspectorField>
        {values.strokeNone ? null : (
          <button className={styles.inspectorControl} disabled={binding.disabled} onClick={() => commit({ kind: "strokeNone" }, paint)} type="button">
            Remove stroke
          </button>
        )}
        <InspectorField label="Corner radius">
          <SegmentedControl
            ariaLabel="Corner radius"
            disabled={binding.disabled}
            onChange={(radiusMode) => commit({ kind: radiusMode === "pill" ? "radiusPill" : radiusMode === "custom" ? "radiusCustom" : "radiusNumber" }, paint)}
            options={RADIUS_MODES}
            value={values.radiusMode}
          />
        </InspectorField>
        {values.radiusMode === "number" ? (
          <InspectorField label="Radius">
            <InspectorInput
              ariaLabel="Corner radius size"
              disabled={binding.disabled}
              onCommitValue={(value) => commit({ kind: "radius", value }, paint)}
              suffix="px"
              value={values.radius}
            />
          </InspectorField>
        ) : values.radiusMode === "custom" ? (
          <RadiusControls
            disabled={binding.disabled}
            onChange={(corner, value) =>
              corner === "all"
                ? commit({ kind: "radius", value }, paint)
                : commit({ index: CORNERS.indexOf(corner) as 0 | 1 | 2 | 3, kind: "corner", value }, paint)
            }
            values={radiusValues}
          />
        ) : null}
        <Note note={note} section="stroke" />
      </InspectorSection>
      <InspectorSection label="Layout" onOpenChange={setLayoutOpen} open={layoutOpen}>
        <div className={styles.fieldGrid}>
          <InspectorField label="Padding Y">
            <InspectorInput
              ariaLabel="Padding top and bottom"
              disabled={binding.disabled}
              onCommitValue={(value) => commit({ kind: "paddingY", value }, layout)}
              suffix="px"
              value={layoutValues.paddingY}
            />
          </InspectorField>
          <InspectorField label="Padding X">
            <InspectorInput
              ariaLabel="Padding left and right"
              disabled={binding.disabled}
              onCommitValue={(value) => commit({ kind: "paddingX", value }, layout)}
              suffix="px"
              value={layoutValues.paddingX}
            />
          </InspectorField>
        </div>
        {isBox ? (
          <>
            <InspectorField label="Gap">
              <InspectorInput
                ariaLabel="Gap between its contents"
                disabled={binding.disabled || !layoutValues.gapLive}
                onCommitValue={(value) => commit({ kind: "gap", value }, layout)}
                suffix="px"
                value={layoutValues.gap}
              />
            </InspectorField>
            {layoutValues.gapLive ? null : (
              <p className={styles.inspectorStatusNote} role="status">
                {BOX_GAP_NOTE}
              </p>
            )}
          </>
        ) : null}
        <InspectorField label="Width">
          <SegmentedControl
            ariaLabel={mode === "button" ? "Button width" : "Box width"}
            disabled={widthOff}
            onChange={(value) => commit({ kind: "widthMode", value }, layout)}
            options={WIDTH_MODES}
            value={layoutValues.widthMode}
          />
        </InspectorField>
        {layout.widthNote ? (
          <p className={styles.inspectorStatusNote} role="status">
            {layout.widthNote}
          </p>
        ) : layoutValues.widthMode === "fixed" ? (
          <InspectorField label="Fixed width">
            <InspectorInput
              ariaLabel={mode === "button" ? "Button width in pixels" : "Box width in pixels"}
              disabled={binding.disabled}
              onCommitValue={(value) => commit({ kind: "width", value }, layout)}
              suffix="px"
              value={layoutValues.width}
            />
          </InspectorField>
        ) : null}
        <Note note={note} section="layout" />
      </InspectorSection>
      {isBox ? (
        <SiteArrangeSection binding={binding} order={mode === "box"}>
          <InspectorField label="Content alignment">
            <TextAlignment
              disabled={binding.disabled || !layoutValues.alignLive}
              horizontal={ALIGN_FROM[layoutValues.contentAlign]}
              onHorizontalChange={(value) => {
                if (value !== "justify") commit({ kind: "contentAlign", to: ALIGN_TO[value] }, layout);
              }}
              options="three"
            />
          </InspectorField>
          {layoutValues.alignLive ? null : (
            <p className={styles.inspectorStatusNote} role="status">
              {ALIGN_ROOM_NOTE}
            </p>
          )}
          <Note note={note} section="arrange" />
        </SiteArrangeSection>
      ) : null}
    </fieldset>
  );
}
