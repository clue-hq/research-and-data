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
  boldAvailable,
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
      return "Choose one of the listed fonts.";
    default:
      return "That change could not be made.";
  }
}

/**
 * The site element inspector's text panel (plan 1, spec §2 mockup 1): the selected text element's
 * Typography — colour (brand or custom), font, size, weight, bold / italic / underline, alignment —
 * applied to the whole text box, or (plan 2) to the words highlighted in it; for a button (plan 3) the
 * same rows style its words, under a Text row that retypes them. Every change is the element's whole new override, written by the
 * session as one save. While the agent-run lock holds, everything is disabled.
 */
export function SiteTextPanel({ binding }: { binding: SiteInspectorBinding }) {
  const element = binding.element!;
  const [open, setOpen] = useState(true);
  // A note belongs to the element it was said about; moving to another element clears it.
  const [noteFor, setNoteFor] = useState<{ key: string; text: string } | null>(null);
  const note = noteFor?.key === binding.selectionKey ? noteFor.text : null;
  const setNote = (text: string | null) => setNoteFor(text ? { key: binding.selectionKey, text } : null);
  // Plan 3: a selected button's typography is its label's (the words inside the box); its Text row
  // retypes those words.
  const label = element.kind === "button" ? (element.labelElement ?? null) : null;
  // Plan 2: with words highlighted in rich text, every row but Alignment acts on those words (their
  // styled span); otherwise on the whole text box.
  const words = element.words && (label ? label.rich : element.rich) ? element.words : null;
  const override = label ? (words ? binding.labelWordsOverride : binding.labelOverride) : words ? binding.wordsOverride : binding.elementOverride;
  const computed = words ? words.computed : (label?.computed ?? element.computed);
  const styleWords = label ? binding.onLabelWordStyleCommit : binding.onWordStyleCommit;
  const values = textPanelValues(override, computed, binding.palette, binding.fonts);
  const canBold = boldAvailable(binding.fonts, values.fontFamily);
  // The latest override as this panel last wrote it: a drag's later moves build on its earlier ones.
  const latest = useRef(override);
  useEffect(() => {
    latest.current = override;
  }, [override]);
  const pendingColor = useRef<{ hex: string; timer: ReturnType<typeof setTimeout> } | null>(null);

  const commit = (change: TextPanelChange) => {
    if (binding.disabled) return;
    const next = textPanelPatch(latest.current, change, computed, binding.fonts);
    if (!next) {
      setNote(refusalNote(change));
      return;
    }
    setNote(null);
    if (JSON.stringify(next) === JSON.stringify(latest.current ?? {})) return;
    if (words) {
      // Each stretch of the words keeps its own look and takes this one change.
      const refused = styleWords((old) => textPanelPatch(old, change, computed, binding.fonts) ?? old);
      if (refused) setNote(refused);
      else latest.current = next;
      return;
    }
    latest.current = next;
    binding.onStyleCommit(label?.key ?? element.key, next);
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
  // A colour still settling when the selection moves on is written to its own element, never dropped.
  useEffect(() => () => flushColor(), [binding.selectionKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // The element's own family leads the list when it is not one of the brand's (a seller's font in a
  // copied section), so the list always shows what the text uses.
  const families = binding.fonts.map((font) => font.family);
  const familyOptions = families.includes(values.fontFamily) || !values.fontFamily ? families : [values.fontFamily, ...families];

  return (
    <InspectorSection label="Typography" onOpenChange={setOpen} open={open}>
      <fieldset disabled={binding.disabled} style={{ display: "contents" }}>
        {words ? (
          <p className={styles.inspectorStatusNote} role="status">
            {words.count === 1 ? "1 word selected" : `${words.count} words selected`}
          </p>
        ) : binding.wordsUnavailable ? (
          <p className={styles.inspectorStatusNote} role="status">
            {binding.wordsUnavailable}
          </p>
        ) : null}
        {/* Founder 2026-10-19: words are changed on the page. The Text row stays only for words that cannot
            be typed there: a copied button's words with no slot (a replacement), or a note saying why
            they cannot change at all. */}
        {label && (element.labelSource?.kind === "replacement" || binding.labelText === null) ? (
          <InspectorField label="Text">
            {binding.labelText === null ? (
              <p className={styles.inspectorStatusNote} role="status">
                {element.labelSource?.kind === "fixed" ? element.labelSource.reason : "These words cannot be changed here."}
              </p>
            ) : (
              <InspectorInput
                ariaLabel="Button text"
                disabled={binding.disabled}
                onCommitValue={(value) => {
                  if (value.trim()) binding.onLabelTextCommit(value);
                  else setNote("A button needs words.");
                }}
                value={binding.labelText}
              />
            )}
            {element.labelSource?.kind === "replacement" && element.labelSource.shared ? (
              <p className={styles.inspectorStatusNote} role="status">
                Other text in this section reads the same, so changing it changes that text too.
              </p>
            ) : null}
          </InspectorField>
        ) : null}
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
            boldDisabled={!canBold}
            disabled={binding.disabled}
            italic={values.italic}
            onBoldChange={(on) => commit({ kind: "bold", on })}
            onItalicChange={(on) => commit({ kind: "italic", on })}
            onUnderlineChange={(on) => commit({ kind: "underline", on })}
            underline={values.underline}
          />
        </InspectorField>
        {label ? null : (
          <InspectorField label="Alignment">
            <TextAlignment
              disabled={binding.disabled || words !== null}
              horizontal={values.textAlign}
              onHorizontalChange={(value) => commit({ kind: "textAlign", value })}
              options="four"
            />
          </InspectorField>
        )}
        {words && !label ? (
          <p className={styles.inspectorStatusNote} role="status">
            Alignment applies to the whole text box.
          </p>
        ) : null}
        {canBold ? null : (
          <p className={styles.inspectorStatusNote} role="status">
            {values.fontFamily} has no bold weight, so Bold is not available for this text.
          </p>
        )}
        {note ? (
          <p className={styles.inspectorStatusNote} role="status">
            {note}
          </p>
        ) : null}
      </fieldset>
    </InspectorSection>
  );
}
