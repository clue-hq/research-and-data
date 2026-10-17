"use client";

import { useEffect, useRef, useState } from "react";
import type { SiteInspectorBinding } from "@/features/site-editor/model/site-selection";
import {
  ColorControl,
  InspectorField,
  InspectorInput,
  InspectorSection,
  InspectorSelect,
  TextAlignment,
  TextStyleToggles,
} from "./inspector-primitives";
import {
  FONT_SIZE_RANGE,
  textPanelPatch,
  textPanelValues,
  weightOptions,
  type TextPanelChange,
} from "./site-text-panel.logic";
import styles from "./chat-shell.module.css";

/** A custom colour dragged across the picker's plane or hue slider changes on every move; it is
 * written once the pointer rests this long, so one gesture is one save and one undo step. */
const COLOR_DRAG_SETTLE_MS = 400;

/** Why an input was not taken, said under the field (the field itself shows the current value). */
function refusalNote(change: TextPanelChange): string {
  switch (change.kind) {
    case "fontSize":
      return `Size must be a number from ${FONT_SIZE_RANGE.min} to ${FONT_SIZE_RANGE.max}.`;
    case "opacity":
      return "Opacity must be a whole number from 0 to 100.";
    case "colorHex":
      return "Use a six-digit hex colour, like #0F59B0.";
    case "fontWeight":
      return "That weight is not one this font has.";
    case "fontFamily":
      return "Choose one of the brand's fonts.";
    default:
      return "That change could not be made.";
  }
}

/**
 * The site element inspector's text panel (plan 1, spec §2 mockup 1): the selected text element's
 * Typography — colour (brand or custom), font, size, weight, bold / italic / underline, alignment —
 * applied to the whole text box. Every change is the element's whole new override, written by the
 * session as one save. While the agent-run lock holds, everything is disabled.
 */
export function SiteTextPanel({ binding }: { binding: SiteInspectorBinding }) {
  const element = binding.element!;
  const [open, setOpen] = useState(true);
  const [note, setNote] = useState<string | null>(null);
  const values = textPanelValues(binding.elementOverride, element.computed, binding.palette);
  // The latest override as this panel last wrote it: a drag's later moves build on its earlier ones.
  const latest = useRef(binding.elementOverride);
  useEffect(() => {
    latest.current = binding.elementOverride;
  }, [binding.elementOverride]);
  const pendingColor = useRef<{ hex: string; timer: ReturnType<typeof setTimeout> } | null>(null);

  const commit = (change: TextPanelChange) => {
    if (binding.disabled) return;
    const next = textPanelPatch(latest.current, change, element.computed, binding.fonts);
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
    commit({ hex: pending.hex, kind: "colorHex" });
  };
  const commitColorSoon = (hex: string) => {
    if (pendingColor.current) clearTimeout(pendingColor.current.timer);
    pendingColor.current = { hex, timer: setTimeout(flushColor, COLOR_DRAG_SETTLE_MS) };
  };
  // A colour still settling when the selection moves on is written, never dropped.
  useEffect(() => () => flushColor(), []); // eslint-disable-line react-hooks/exhaustive-deps

  // The element's own family leads the list when it is not one of the brand's (a seller's font in a
  // copied section), so the list always shows what the text uses.
  const families = binding.fonts.map((font) => font.family);
  const familyOptions = families.includes(values.fontFamily) || !values.fontFamily ? families : [values.fontFamily, ...families];

  return (
    <InspectorSection label="Typography" onOpenChange={setOpen} open={open}>
      <fieldset disabled={binding.disabled} style={{ display: "contents" }}>
        <InspectorField label="Color">
          <ColorControl
            color={values.color}
            disabled={binding.disabled}
            onColorChange={commitColorSoon}
            onOpacityChange={(value) => commit({ kind: "opacity", value })}
            onTokenChange={(token) => commit({ kind: "colorToken", token })}
            opacity={values.opacity}
            options={binding.palette}
          />
        </InspectorField>
        <InspectorField label="Font">
          <InspectorSelect
            disabled={binding.disabled}
            label="Font family"
            onChange={(value) => commit({ kind: "fontFamily", value })}
            options={familyOptions}
            value={values.fontFamily}
          />
        </InspectorField>
        <div className={styles.fieldGrid}>
          <InspectorField label="Size">
            <InspectorInput
              ariaLabel="Font size"
              disabled={binding.disabled}
              onCommitValue={(value) => commit({ kind: "fontSize", value })}
              value={values.fontSize}
            />
          </InspectorField>
          <InspectorField label="Weight">
            <InspectorSelect
              disabled={binding.disabled}
              label="Font weight"
              onChange={(value) => commit({ kind: "fontWeight", value })}
              options={weightOptions(binding.fonts, values.fontFamily)}
              value={values.fontWeight}
            />
          </InspectorField>
        </div>
        <InspectorField label="Style">
          <TextStyleToggles
            bold={values.bold}
            disabled={binding.disabled}
            italic={values.italic}
            onBoldChange={(on) => commit({ kind: "bold", on })}
            onItalicChange={(on) => commit({ kind: "italic", on })}
            onUnderlineChange={(on) => commit({ kind: "underline", on })}
            underline={values.underline}
          />
        </InspectorField>
        <InspectorField label="Alignment">
          <TextAlignment
            disabled={binding.disabled}
            horizontal={values.textAlign}
            onHorizontalChange={(value) => commit({ kind: "textAlign", value })}
            options="four"
          />
        </InspectorField>
        {note ? (
          <p className={styles.inspectorStatusNote} role="status">
            {note}
          </p>
        ) : null}
      </fieldset>
    </InspectorSection>
  );
}
