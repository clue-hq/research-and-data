"use client";

import { useEffect, useRef, useState } from "react";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import { ColorControl, InspectorField, InspectorInput, InspectorSection, RadiusControls, SegmentedControl } from "./inspector-primitives";
import {
  BOX_RANGE,
  WIDTH_RANGE,
  buttonPanelPatch,
  buttonPanelValues,
  type ButtonPanelChange,
  type RadiusMode,
  type WidthMode,
} from "./site-button-panel.logic";
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

/** Why an input was not taken, said under the section (the field keeps showing the current value). */
function refusalNote(change: ButtonPanelChange): string {
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
 * The site element inspector's button sections (plan 3, spec §2 mockup 2): the selected button's box —
 * Fill, Stroke with its corner radius, and Layout (padding and width). Its words are styled by the
 * text panel above (label mode) and its link by the Link row below. Every change is the button box's
 * whole new override, written by the session as one save. While the agent-run lock holds, everything
 * is disabled.
 */
export function SiteButtonPanel({ binding }: { binding: SiteInspectorBinding }) {
  const element = binding.element!;
  const box = element.box!;
  const [fillOpen, setFillOpen] = useState(true);
  const [strokeOpen, setStrokeOpen] = useState(true);
  const [layoutOpen, setLayoutOpen] = useState(true);
  const [note, setNote] = useState<string | null>(null);
  const values = buttonPanelValues(binding.elementOverride, box, binding.palette);
  const latest = useRef(binding.elementOverride);
  useEffect(() => {
    latest.current = binding.elementOverride;
  }, [binding.elementOverride]);
  const pendingColor = useRef<{ change: ButtonPanelChange; timer: ReturnType<typeof setTimeout> } | null>(null);

  const commit = (change: ButtonPanelChange) => {
    if (binding.disabled) return;
    const next = buttonPanelPatch(latest.current, change, box);
    if (!next) {
      setNote(refusalNote(change));
      return;
    }
    setNote(null);
    if (JSON.stringify(next) === JSON.stringify(latest.current ?? {})) return;
    latest.current = next;
    binding.onStyleCommit(element.key, next);
  };
  const flushColor = () => {
    const pending = pendingColor.current;
    if (!pending) return;
    clearTimeout(pending.timer);
    pendingColor.current = null;
    commit(pending.change);
  };
  const commitColorSoon = (change: ButtonPanelChange) => {
    if (pendingColor.current && pendingColor.current.change.kind !== change.kind) flushColor();
    if (pendingColor.current) clearTimeout(pendingColor.current.timer);
    pendingColor.current = { change, timer: setTimeout(flushColor, COLOR_DRAG_SETTLE_MS) };
  };
  useEffect(() => () => flushColor(), []); // eslint-disable-line react-hooks/exhaustive-deps

  const allCorners = values.corners.every((corner) => corner === values.corners[0]) ? values.corners[0] : "";
  const radiusValues = {
    all: allCorners,
    bottomLeft: values.corners[3],
    bottomRight: values.corners[2],
    topLeft: values.corners[0],
    topRight: values.corners[1],
  };

  return (
    <fieldset disabled={binding.disabled} style={{ display: "contents" }}>
      <InspectorSection label="Fill" onOpenChange={setFillOpen} open={fillOpen}>
        <InspectorField label="Color">
          <ColorControl
            color={values.fill}
            disabled={binding.disabled}
            onColorChange={(hex) => commitColorSoon({ hex, kind: "fillHex" })}
            onOpacityChange={(value) => commit({ kind: "fillOpacity", value })}
            onTokenChange={(token) => commit({ kind: "fillToken", token })}
            opacity={values.fillOpacity}
            options={binding.palette}
          />
        </InspectorField>
        <p className={styles.inspectorStatusNote} role="status">
          A fill or stroke set here also holds when the button is hovered or focused.
        </p>
      </InspectorSection>
      <InspectorSection label="Stroke" onOpenChange={setStrokeOpen} open={strokeOpen}>
        <InspectorField label="Color">
          <ColorControl
            color={values.stroke}
            disabled={binding.disabled}
            onColorChange={(hex) => commitColorSoon({ hex, kind: "strokeHex" })}
            onOpacityChange={(value) => commit({ kind: "strokeOpacity", value })}
            onTokenChange={(token) => commit({ kind: "strokeToken", token })}
            opacity={values.strokeOpacity}
            options={binding.palette}
          />
        </InspectorField>
        <InspectorField label="Width">
          <InspectorInput
            ariaLabel="Stroke width"
            disabled={binding.disabled}
            onCommitValue={(value) => commit({ kind: "strokeWidth", value })}
            suffix="px"
            value={values.strokeWidth}
          />
        </InspectorField>
        {values.strokeNone ? null : (
          <button className={styles.inspectorControl} disabled={binding.disabled} onClick={() => commit({ kind: "strokeNone" })} type="button">
            Remove stroke
          </button>
        )}
        <InspectorField label="Corner radius">
          <SegmentedControl
            ariaLabel="Corner radius"
            disabled={binding.disabled}
            onChange={(mode) => commit({ kind: mode === "pill" ? "radiusPill" : mode === "custom" ? "radiusCustom" : "radiusNumber" })}
            options={RADIUS_MODES}
            value={values.radiusMode}
          />
        </InspectorField>
        {values.radiusMode === "number" ? (
          <InspectorField label="Radius">
            <InspectorInput
              ariaLabel="Corner radius size"
              disabled={binding.disabled}
              onCommitValue={(value) => commit({ kind: "radius", value })}
              suffix="px"
              value={values.radius}
            />
          </InspectorField>
        ) : values.radiusMode === "custom" ? (
          <RadiusControls
            disabled={binding.disabled}
            onChange={(corner, value) =>
              corner === "all" ? commit({ kind: "radius", value }) : commit({ index: CORNERS.indexOf(corner) as 0 | 1 | 2 | 3, kind: "corner", value })
            }
            values={radiusValues}
          />
        ) : null}
      </InspectorSection>
      <InspectorSection label="Layout" onOpenChange={setLayoutOpen} open={layoutOpen}>
        <div className={styles.fieldGrid}>
          <InspectorField label="Padding Y">
            <InspectorInput
              ariaLabel="Padding top and bottom"
              disabled={binding.disabled}
              onCommitValue={(value) => commit({ kind: "paddingY", value })}
              suffix="px"
              value={values.paddingY}
            />
          </InspectorField>
          <InspectorField label="Padding X">
            <InspectorInput
              ariaLabel="Padding left and right"
              disabled={binding.disabled}
              onCommitValue={(value) => commit({ kind: "paddingX", value })}
              suffix="px"
              value={values.paddingX}
            />
          </InspectorField>
        </div>
        <InspectorField label="Width">
          <SegmentedControl
            ariaLabel="Button width"
            disabled={binding.disabled}
            onChange={(value) => commit({ kind: "widthMode", value })}
            options={WIDTH_MODES}
            value={values.widthMode}
          />
        </InspectorField>
        {values.widthMode === "fixed" ? (
          <InspectorField label="Fixed width">
            <InspectorInput
              ariaLabel="Button width in pixels"
              disabled={binding.disabled}
              onCommitValue={(value) => commit({ kind: "width", value })}
              suffix="px"
              value={values.width}
            />
          </InspectorField>
        ) : null}
        {note ? (
          <p className={styles.inspectorStatusNote} role="status">
            {note}
          </p>
        ) : null}
      </InspectorSection>
    </fieldset>
  );
}
