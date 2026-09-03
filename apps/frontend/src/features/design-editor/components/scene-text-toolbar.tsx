"use client";

import React, { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { ScenePalette } from "../adapter/scene-palette";
import { richTextAriaPressed } from "../engine/webRichText";
import type { RangeFormatState } from "../engine/scene/textSpans";
import {
  SCENE_TEXT_MARK_CONTROLS,
  sceneTextFillColor,
  sceneTextMarkState,
  sceneTextToolbarPosition,
  sceneTextToolbarSwatches,
  type SceneTextFaceAvailability,
  type SceneTextFillChoice,
  type SceneTextMarkChannel,
  type SceneTextToolbarPosition,
} from "./scene-text-toolbar.logic";
import web from "./web-rich-text-toolbar.module.css";
import styles from "./scene-text-toolbar.module.css";

/**
 * Rung C: the floating formatting toolbar for an open caret session
 * (`docs/superpowers/plans/2026-08-24-rich-text-editing.md`).
 *
 * PRESENTATION TRUTH (standing constraint 2, founder-visible item 2): no new
 * chrome was designed for this. Every control wears
 * `web-rich-text-toolbar.module.css` — the repo's one designed formatting-
 * toolbar surface — so the two read as one system: same 32px tools, same
 * pressed/mixed treatment, same popover, same swatch grid, same aria mapping
 * (`richTextAriaPressed`, imported rather than restated). Only the frame is
 * this file's own (see `scene-text-toolbar.module.css`).
 *
 * What it can do is exactly what a `TextSpan` can carry: the four marks, and a
 * fill that is a brand token or a solid hex. There is no block/list row (a
 * scene text node has no block structure), no link and no variable — offering
 * them would be inventing affordances the engine cannot honour.
 *
 * THE FOCUS HANDSHAKE is the whole reason this is not a trivial component. The
 * session commits on the textarea's blur, so a toolbar that stole focus would
 * end the session it is meant to format. Two mechanisms, in this order:
 *
 *  • a pointer-down on anything that is NOT a text field is `preventDefault`ed,
 *    so a mouse click on a button or swatch never moves focus at all — the
 *    caret and its selection are untouched, which is also what makes the
 *    styling apply to the range the user is still looking at;
 *  • anything that DOES take focus (the hex field) announces itself through
 *    `onInteractionStart`, and every action ends with `onInteractionEnd`, which
 *    is the overlay's cue to put focus and selection back where they were.
 *
 * Every decision this file makes — the control set, what a click authors, the
 * chords, the position, the colour vocabulary — lives in
 * `scene-text-toolbar.logic.ts`, where the renderer-free suite can reach it.
 */

const MARK_GLYPH_CLASS: Record<string, string | undefined> = {
  italic: web.glyphItalic,
  underline: web.glyphUnderline,
  strikethrough: web.glyphStrikethrough,
};

export interface SceneTextToolbarProps {
  /** The edited node's box, in the STAGE px the caret overlay uses. */
  box: { left: number; top: number; width: number; height: number };
  /** No range selected — the span toggles have nothing to act on (item 4). */
  collapsed: boolean;
  /** Which face-dependent marks that family can paint (Plan 1 item B). */
  faces: SceneTextFaceAvailability;
  /** The node's declared family, for the disabled-mark reason. */
  family: string;
  format: RangeFormatState;
  /** The session's own gate: a locked node, or a refused write path. */
  inert: boolean;
  /** The node's own painted colour — what a range with no fill override is. */
  nodeColor: string;
  /** The edited node, published as `data-scene-text-toolbar` — the same
   * machine-readable hook the caret carries, and what lets the session tell an
   * "inside the toolbar" pointer from one that ends the session. */
  nodeId: string;
  onFill: (choice: SceneTextFillChoice) => void;
  onInteractionEnd: () => void;
  onInteractionStart: () => void;
  onMark: (channel: SceneTextMarkChannel) => void;
  palette: ScenePalette | null;
  /** The stage's own size, so the bar can be clamped inside it, plus the band
   * at its top that is already occupied (D3a — the G-D banners), which the bar
   * places itself clear of rather than under. */
  stage: { width: number; height: number; topInset?: number };
}

function isTextField(target: EventTarget | null): boolean {
  return target instanceof HTMLInputElement && target.type === "text";
}

export function SceneTextToolbar({
  box,
  collapsed,
  faces,
  family,
  format,
  inert,
  nodeColor,
  nodeId,
  onFill,
  onInteractionEnd,
  onInteractionStart,
  onMark,
  palette,
  stage,
}: SceneTextToolbarProps): React.ReactElement {
  const toolbarRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<SceneTextToolbarPosition | null>(null);
  const [colorOpen, setColorOpen] = useState(false);
  const [hex, setHex] = useState("");
  const [hexError, setHexError] = useState<string | null>(null);

  const swatches = sceneTextToolbarSwatches(palette);
  const fillColor = sceneTextFillColor(palette, format.fill, nodeColor);
  const selectedToken =
    format.fill.kind === "uniform" && format.fill.paint?.kind === "token"
      ? format.fill.paint.token
      : null;

  // The bar's own size is a DOM fact, so the placement is measured and applied
  // the way the web toolbar measures and applies its own — one layout effect,
  // re-run whenever the box, the stage or the open panel changes its size.
  const recomputePosition = useCallback(() => {
    const toolbar = toolbarRef.current;
    if (!toolbar) {
      return;
    }
    const rect = toolbar.getBoundingClientRect();
    setPosition(
      sceneTextToolbarPosition({
        box,
        stage,
        toolbar: { width: rect.width, height: rect.height },
      }),
    );
  }, [box, stage]);

  useLayoutEffect(() => {
    recomputePosition();
  }, [recomputePosition, colorOpen]);

  const applyFill = (choice: SceneTextFillChoice) => {
    onFill(choice);
    setColorOpen(false);
    onInteractionEnd();
  };

  const submitHex = (event: React.FormEvent) => {
    event.preventDefault();
    // The one inline error this toolbar can raise, in the web toolbar's own
    // error slot: `normalizeHex` refuses anything that is not `#rrggbb(aa)`,
    // and a refused colour must say why rather than silently doing nothing.
    if (!/^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(hex.trim())) {
      setHexError("Enter a hex colour, like #533AFD.");
      return;
    }
    applyFill({ kind: "hex", value: hex.trim() });
  };

  return (
    <div
      className={`${styles.anchor}${position ? ` ${styles.placed}` : ""}`}
      data-scene-text-toolbar={nodeId}
      ref={toolbarRef}
      role="toolbar"
      aria-label="Text formatting"
      aria-orientation="horizontal"
      onClick={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
      onFocusCapture={() => onInteractionStart()}
      onPointerDownCapture={(event) => {
        // A press ANYWHERE in the toolbar is inside the session, whether or not
        // it ends up moving focus — on a touch device it will, and the session
        // must not commit itself out from under the tap that is formatting it.
        // Cleared again by `onInteractionEnd` when the action completes.
        onInteractionStart();
        event.stopPropagation();
      }}
      onMouseDownCapture={(event) => {
        // The canonical don't-steal-focus move, and deliberately on MOUSEDOWN
        // rather than on pointerdown: cancelling pointerdown suppresses the
        // compatibility mousedown this relies on, and the click that follows
        // must still land. Text fields are exempt — they cannot be typed in
        // without focus, which is what `onInteractionStart` above covers.
        if (!isTextField(event.target)) {
          event.preventDefault();
        }
      }}
      style={
        position ? { left: `${position.left}px`, top: `${position.top}px` } : undefined
      }
    >
      <div className={web.row}>
        {SCENE_TEXT_MARK_CONTROLS.map((control) => {
          const state = sceneTextMarkState(control.channel, format, {
            collapsed,
            inert,
            family,
            faces,
          });
          return (
            <button
              key={control.channel}
              type="button"
              className={`${web.tool}${
                state.pressed === "on" ? ` ${web.selected}` : ""
              }${state.pressed === "mixed" ? ` ${web.mixed}` : ""}`}
              aria-label={control.label}
              aria-pressed={richTextAriaPressed(state.pressed)}
              title={
                state.reason ??
                (control.shortcut
                  ? `${control.label} (${control.shortcut})`
                  : control.label)
              }
              disabled={state.disabled}
              onClick={() => {
                onMark(control.channel);
                onInteractionEnd();
              }}
            >
              <span className={MARK_GLYPH_CLASS[control.channel]} aria-hidden="true">
                {control.glyph}
              </span>
            </button>
          );
        })}
        <span className={web.divider} aria-hidden="true" />
        <button
          type="button"
          className={`${web.tool}${
            format.fill.kind === "mixed" ? ` ${web.mixed}` : ""
          }`}
          aria-label="Text color"
          aria-pressed={richTextAriaPressed(
            format.fill.kind === "mixed" ? "mixed" : "off",
          )}
          aria-haspopup="true"
          aria-expanded={colorOpen}
          aria-controls="scene-text-color-panel"
          title="Text color"
          disabled={collapsed || inert}
          onClick={() => {
            setHexError(null);
            // Closing the panel ends the interaction that opened it, so the
            // caret gets its focus and its range back.
            if (colorOpen) {
              onInteractionEnd();
            }
            setColorOpen(!colorOpen);
          }}
        >
          <span className={web.colorGlyph} aria-hidden="true">
            A
            <span style={{ backgroundColor: fillColor ?? undefined }} />
          </span>
        </button>
      </div>

      {colorOpen ? (
        <div
          id="scene-text-color-panel"
          className={web.popover}
          role="group"
          aria-label="Text color"
          // Above the row when the bar is above the caret, so the buttons stay
          // adjacent to the text they act on (the web toolbar's `.above` rule,
          // expressed here because this bar wears its own frame class).
          style={{ order: position?.placement === "above" ? -1 : 0 }}
        >
          <div className={web.popoverHead}>Brand colors</div>
          {swatches.length > 0 ? (
            <div className={web.swatches}>
              {swatches.map((option) => (
                <button
                  key={option.token}
                  type="button"
                  className={`${web.swatch}${
                    selectedToken === option.token ? ` ${web.swatchSelected}` : ""
                  }`}
                  aria-label={`Text color: ${option.label}`}
                  aria-pressed={selectedToken === option.token}
                  title={option.label}
                  disabled={inert}
                  onClick={() => applyFill({ kind: "token", label: option.label })}
                >
                  <span
                    className={web.swatchColor}
                    style={{ backgroundColor: option.value }}
                    aria-hidden="true"
                  />
                  <span>{option.label}</span>
                </button>
              ))}
              <button
                type="button"
                className={`${web.swatch} ${web.swatchClear}`}
                disabled={inert}
                onClick={() => applyFill({ kind: "clear" })}
              >
                Clear
              </button>
            </div>
          ) : (
            // §1.6: with no kit attached there is no brand vocabulary to offer,
            // and the fixture palette is never substituted — a label validated
            // against nothing is not a token. Custom hex still works.
            <p className={web.popoverHint}>
              This document has no brand palette; a custom color still applies.
            </p>
          )}
          <form className={`${web.form}`} onSubmit={submitHex}>
            <label>
              {/* §1.6: custom hex is allowed, and it detaches the run's brand
                  binding — the accepted, informed trade. The "leaves your brand
                  palette" note is Gate G-B's, unrendered anywhere yet. */}
              <span>Custom color</span>
              <input
                type="text"
                value={hex}
                placeholder="#533AFD"
                disabled={inert}
                aria-invalid={Boolean(hexError)}
                aria-describedby={hexError ? "scene-text-color-error" : undefined}
                onChange={(event) => {
                  setHex(event.target.value);
                  setHexError(null);
                }}
              />
            </label>
            {hexError ? (
              <p id="scene-text-color-error" className={web.error} role="alert">
                {hexError}
              </p>
            ) : null}
            <div className={web.formActions}>
              <button type="submit" disabled={inert}>
                Apply color
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
