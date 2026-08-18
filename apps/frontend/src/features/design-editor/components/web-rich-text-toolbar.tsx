"use client";

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import type {
  RichTextCommand,
  RichTextFormatValue,
  RichTextSelectionState,
} from "../engine/webBridge";
import type { WebRichTextVariable, WebTheme } from "../engine/webDocuments";
import {
  RICH_TEXT_BLOCK_CONTROLS,
  RICH_TEXT_MARK_CONTROLS,
  richTextAriaPressed,
} from "../engine/webRichText";
import {
  classFacetValue,
  computeToolbarPosition,
  richTextLinkSubmission,
  richTextToolbarValidContext,
  toolbarKnownTokenNames,
  toolbarThemeTokens,
  type ToolbarPosition,
} from "./web-rich-text-toolbar.logic";
import styles from "./web-rich-text-toolbar.module.css";

/**
 * W4.8a: the floating toolbar for an in-iframe rich-text session, ported from
 * the design editor's `components/web/WebRichTextToolbar.tsx` (714 lines).
 *
 * Ruling 24 (founder, 2026-08-18): this toolbar is kept AS THE SOURCE SHIPPED
 * IT — it is canvas UI, not part of the dummy inspector vocabulary. So the
 * logic is verbatim: same controls in the same order, same disabled/`title`
 * copy, same aria wiring, same focus handshake, same positioning math, same
 * render gating. Only two things were adapted:
 *
 *  • styling — the source's global `web.css` classes became the CSS module
 *    beside this file (see its header for the token resolution);
 *  • the pure decisions (render gate, class-facet read, token list, position
 *    math, link submit) moved to `web-rich-text-toolbar.logic.ts`, because
 *    this repo's runner (`tsx --test`) cannot render React and the source's
 *    12-case suite would otherwise have nothing to test.
 *
 * It renders inside `WebArtifactCanvas` — the canvas owns it (the `iframeRef`
 * it positions against never leaves that component), and `position: fixed`
 * keeps it out of the canvas's layout.
 */

export interface WebRichTextToolbarProps {
  iframeRef: RefObject<HTMLIFrameElement | null>;
  nodeId: string;
  selection: RichTextSelectionState;
  theme: WebTheme | null;
  variables: WebRichTextVariable[];
  disabled: boolean;
  command: (nodeId: string, command: RichTextCommand) => void;
  setInteractionActive: (nodeId: string, active: boolean) => void;
  settle: (nodeId: string, action: "commit" | "cancel") => void;
}

type ToolbarPanel = "text_color" | "highlight" | "link" | "variable";

function ColorPanel({
  id,
  label,
  prefix,
  state,
  tokens,
  disabled,
  onPick,
}: {
  id: string;
  label: string;
  prefix: "text-" | "bg-";
  state: RichTextSelectionState;
  tokens: [string, string][];
  disabled: boolean;
  onPick: (token: string | null) => void;
}): React.ReactElement {
  const facet = classFacetValue(
    state,
    prefix,
    tokens.map(([name]) => name),
  );
  return (
    <div id={id} className={styles.popover} role="group" aria-label={label}>
      <div className={styles.popoverHead}>{label}</div>
      {tokens.length > 0 ? (
        <div className={styles.swatches}>
          {tokens.map(([name, color]) => (
            <button
              key={name}
              type="button"
              className={`${styles.swatch}${
                facet.value === name ? ` ${styles.swatchSelected}` : ""
              }`}
              aria-label={`${label}: ${name}`}
              aria-pressed={
                facet.value === name
                  ? facet.state === "mixed"
                    ? "mixed"
                    : true
                  : false
              }
              title={name}
              disabled={disabled}
              onClick={() => onPick(name)}
            >
              <span
                className={styles.swatchColor}
                style={{ backgroundColor: color }}
                aria-hidden="true"
              />
              <span>{name}</span>
            </button>
          ))}
          <button
            type="button"
            className={`${styles.swatch} ${styles.swatchClear}`}
            disabled={disabled}
            onClick={() => onPick(null)}
          >
            Clear
          </button>
        </div>
      ) : (
        <p className={styles.popoverHint}>
          No resolved theme colors are available.
        </p>
      )}
    </div>
  );
}

function isEnabledToolbarControl(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) {
    return false;
  }
  const interactive = target.closest("button, input, select, textarea, label");
  if (!interactive) {
    return false;
  }
  const control =
    interactive instanceof HTMLLabelElement ? interactive.control : interactive;
  if (
    control instanceof HTMLButtonElement ||
    control instanceof HTMLInputElement ||
    control instanceof HTMLSelectElement ||
    control instanceof HTMLTextAreaElement
  ) {
    return !control.disabled;
  }
  return false;
}

const GLYPH_STYLES: Record<string, string | undefined> = {
  italic: styles.glyphItalic,
  underline: styles.glyphUnderline,
  strikethrough: styles.glyphStrikethrough,
};

export function WebRichTextToolbar({
  iframeRef,
  nodeId,
  selection,
  theme,
  variables,
  disabled,
  command,
  setInteractionActive,
  settle,
}: WebRichTextToolbarProps): React.ReactElement | null {
  const toolbarRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<ToolbarPosition | null>(null);
  const [openPanel, setOpenPanel] = useState<ToolbarPanel | null>(null);
  const [linkHref, setLinkHref] = useState("");
  const [linkNewTab, setLinkNewTab] = useState(false);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [variableKey, setVariableKey] = useState("");
  const [variableFallback, setVariableFallback] = useState("");
  const [variableError, setVariableError] = useState<string | null>(null);

  // Two token lists, deliberately: the OFFERED swatches (F3-filtered, and what
  // the facet state is read against, so an off-list ramp shows as no
  // selection — the inspector's documented F3 behaviour) and the full set the
  // command carries so the runtime can strip the classes it replaces.
  const tokens = toolbarThemeTokens(theme);
  const tokenNames = tokens.map(([name]) => name);
  const knownTokens = toolbarKnownTokenNames(theme);
  const textColor = classFacetValue(selection, "text-", tokenNames);
  const highlight = classFacetValue(selection, "bg-", tokenNames);
  const validContext = richTextToolbarValidContext(selection);

  const recomputePosition = useCallback(() => {
    const iframe = iframeRef.current;
    const range = selection.rect;
    const toolbar = toolbarRef.current;
    if (!iframe || !range || !toolbar || !validContext) {
      setPosition(null);
      return;
    }
    const frameRect = iframe.getBoundingClientRect();
    const toolbarRect = toolbar.getBoundingClientRect();
    setPosition(
      computeToolbarPosition({
        frame: {
          top: frameRect.top,
          left: frameRect.left,
          right: frameRect.right,
          bottom: frameRect.bottom,
        },
        range,
        toolbar: { width: toolbarRect.width, height: toolbarRect.height },
        viewport: { width: window.innerWidth, height: window.innerHeight },
      }),
    );
  }, [iframeRef, selection.rect, validContext]);

  useLayoutEffect(() => {
    recomputePosition();
  }, [recomputePosition, openPanel]);

  useEffect(() => {
    const handleViewportChange = () => recomputePosition();
    window.addEventListener("resize", handleViewportChange, { passive: true });
    window.addEventListener("scroll", handleViewportChange, {
      capture: true,
      passive: true,
    });
    return () => {
      window.removeEventListener("resize", handleViewportChange);
      window.removeEventListener("scroll", handleViewportChange, true);
    };
  }, [recomputePosition]);

  // NOTE (the one structural deviation from the source): the source resets
  // `openPanel`/`linkError`/`variableError` in a `useEffect` keyed on
  // `nodeId`. This repo's lint forbids a synchronous setState inside an effect
  // (react-hooks/set-state-in-effect), so the reset is expressed as a REMOUNT
  // instead — the canvas mounts this component with `key={editingNodeId}`.
  // Same outcome, more so: a new session starts with every panel closed and
  // every inline error cleared. Do not reintroduce the effect.

  useEffect(() => {
    const handleOutsidePointer = (event: PointerEvent) => {
      if (
        openPanel &&
        toolbarRef.current &&
        !toolbarRef.current.contains(event.target as Node)
      ) {
        settle(nodeId, "commit");
      }
    };
    window.document.addEventListener("pointerdown", handleOutsidePointer, true);
    return () =>
      window.document.removeEventListener(
        "pointerdown",
        handleOutsidePointer,
        true,
      );
  }, [nodeId, openPanel, settle]);

  const togglePanel = (panel: ToolbarPanel) => {
    if (openPanel === panel) {
      setOpenPanel(null);
      setInteractionActive(nodeId, false);
      return;
    }
    if (panel === "link") {
      setLinkHref(
        selection.link.state === "on" ? (selection.link.href ?? "") : "",
      );
      setLinkNewTab(
        selection.link.state === "on" ? Boolean(selection.link.newTab) : false,
      );
      setLinkError(null);
    }
    if (panel === "variable") {
      const first = variables[0] ?? null;
      setVariableKey(first?.key ?? "");
      setVariableFallback(
        selection.selectedText.trim() || first?.example?.trim() || "",
      );
      setVariableError(null);
    }
    setInteractionActive(nodeId, true);
    setOpenPanel(panel);
  };

  const setColor = (
    facet: "text_color" | "highlight",
    token: string | null,
  ) => {
    command(nodeId, {
      type: "set_class_facet",
      facet,
      token,
      knownTokens,
    });
    setOpenPanel(null);
  };

  const submitLink = (event: React.FormEvent) => {
    event.preventDefault();
    const submission = richTextLinkSubmission(linkHref, linkNewTab);
    if (!submission.ok) {
      setLinkError(submission.error);
      return;
    }
    command(nodeId, submission.command);
    setOpenPanel(null);
  };

  const submitVariable = (event: React.FormEvent) => {
    event.preventDefault();
    const fallback = variableFallback.trim();
    if (
      !variableKey ||
      !variables.some((variable) => variable.key === variableKey)
    ) {
      setVariableError("Choose an available variable.");
      return;
    }
    if (!fallback) {
      setVariableError("Fallback text is required and must remain visible.");
      return;
    }
    command(nodeId, {
      type: "insert_variable",
      key: variableKey,
      fallback,
    });
    setOpenPanel(null);
  };

  if (!validContext || !selection.rect) {
    return null;
  }

  return (
    <div
      ref={toolbarRef}
      className={`${styles.toolbar}${position ? ` ${styles.positioned}` : ""}${
        (position?.placement ?? "above") === "above" ? ` ${styles.above}` : ""
      }`}
      style={
        position
          ? { left: `${position.left}px`, top: `${position.top}px` }
          : undefined
      }
      role="toolbar"
      aria-label="Selected text formatting"
      aria-orientation="horizontal"
      onClick={(event) => event.stopPropagation()}
      onPointerDownCapture={(event) => {
        if (isEnabledToolbarControl(event.target)) {
          setInteractionActive(nodeId, true);
        }
      }}
      onFocusCapture={(event) => {
        if (isEnabledToolbarControl(event.target)) {
          setInteractionActive(nodeId, true);
        }
      }}
      onKeyDownCapture={(event) => {
        if (event.key === "Tab") {
          // Let the browser perform ordinary focus traversal, then settle the
          // iframe interaction state according to where focus actually landed.
          // This keeps the toolbar reachable with Shift+Tab without trapping
          // keyboard users inside it.
          window.setTimeout(() => {
            const toolbar = toolbarRef.current;
            const active = window.document.activeElement;
            if (
              !toolbar ||
              (active instanceof Node && toolbar.contains(active))
            ) {
              return;
            }
            if (active === iframeRef.current) {
              setInteractionActive(nodeId, false);
            } else {
              settle(nodeId, "commit");
            }
          }, 0);
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          settle(nodeId, "cancel");
        }
      }}
    >
      <div className={styles.row}>
        {RICH_TEXT_BLOCK_CONTROLS.map((control) => {
          const state: RichTextFormatValue =
            selection.blockType === "mixed"
              ? "mixed"
              : selection.blockType === control.block
                ? "on"
                : "off";
          return (
            <button
              key={control.block}
              type="button"
              className={`${styles.tool}${
                state === "on" ? ` ${styles.selected}` : ""
              }${state === "mixed" ? ` ${styles.mixed}` : ""}`}
              aria-label={control.label}
              aria-pressed={richTextAriaPressed(state)}
              title={
                selection.structured
                  ? control.label
                  : "Paragraphs and lists are available for Body and Small text."
              }
              disabled={disabled || !selection.structured}
              onClick={() =>
                command(nodeId, { type: "set_block", block: control.block })
              }
            >
              <span aria-hidden="true">{control.glyph}</span>
            </button>
          );
        })}
        <button
          type="button"
          className={styles.tool}
          aria-label="Outdent list item"
          title={
            selection.structured
              ? "Outdent list item (Shift+Tab)"
              : "Lists are available for Body and Small text."
          }
          disabled={disabled || !selection.structured || !selection.canOutdent}
          onClick={() => command(nodeId, { type: "outdent_list" })}
        >
          <span aria-hidden="true">⇤</span>
        </button>
        <button
          type="button"
          className={styles.tool}
          aria-label="Indent list item"
          title={
            selection.structured
              ? "Indent list item (Tab)"
              : "Lists are available for Body and Small text."
          }
          disabled={disabled || !selection.structured || !selection.canIndent}
          onClick={() => command(nodeId, { type: "indent_list" })}
        >
          <span aria-hidden="true">⇥</span>
        </button>
        <span className={styles.divider} aria-hidden="true" />
        {RICH_TEXT_MARK_CONTROLS.map((control) => (
          <button
            key={control.format}
            type="button"
            className={`${styles.tool}${
              selection.formats[control.format] === "on"
                ? ` ${styles.selected}`
                : ""
            }${
              selection.formats[control.format] === "mixed"
                ? ` ${styles.mixed}`
                : ""
            }`}
            aria-label={control.label}
            aria-pressed={richTextAriaPressed(selection.formats[control.format])}
            title={`${control.label} (${control.shortcut})`}
            disabled={disabled}
            onClick={() =>
              command(nodeId, { type: "format", format: control.format })
            }
          >
            <span className={GLYPH_STYLES[control.format]} aria-hidden="true">
              {control.glyph}
            </span>
          </button>
        ))}
        <span className={styles.divider} aria-hidden="true" />
        <button
          type="button"
          className={`${styles.tool}${
            textColor.state === "mixed" ? ` ${styles.mixed}` : ""
          }`}
          aria-label="Text color"
          aria-pressed={richTextAriaPressed(textColor.state)}
          aria-haspopup="true"
          aria-expanded={openPanel === "text_color"}
          aria-controls="web-rich-text-color-panel"
          title="Text color"
          disabled={disabled || tokens.length === 0}
          onClick={() => togglePanel("text_color")}
        >
          <span className={styles.colorGlyph} aria-hidden="true">
            A
            <span
              style={{
                backgroundColor: textColor.value
                  ? theme?.tokens[textColor.value]
                  : undefined,
              }}
            />
          </span>
        </button>
        <button
          type="button"
          className={`${styles.tool}${
            highlight.state === "mixed" ? ` ${styles.mixed}` : ""
          }`}
          aria-label="Highlight color"
          aria-pressed={richTextAriaPressed(highlight.state)}
          aria-haspopup="true"
          aria-expanded={openPanel === "highlight"}
          aria-controls="web-rich-highlight-panel"
          title="Highlight color"
          disabled={disabled || tokens.length === 0}
          onClick={() => togglePanel("highlight")}
        >
          <span className={styles.highlightGlyph} aria-hidden="true">
            A
          </span>
        </button>
        <span className={styles.divider} aria-hidden="true" />
        <button
          type="button"
          className={`${styles.tool}${
            selection.link.state === "on" ? ` ${styles.selected}` : ""
          }${selection.link.state === "mixed" ? ` ${styles.mixed}` : ""}`}
          aria-label={selection.link.state === "on" ? "Edit link" : "Insert link"}
          aria-pressed={richTextAriaPressed(selection.link.state)}
          aria-haspopup="true"
          aria-expanded={openPanel === "link"}
          aria-controls="web-rich-link-panel"
          title={selection.link.state === "on" ? "Edit link" : "Insert link"}
          disabled={disabled}
          onClick={() => togglePanel("link")}
        >
          ↗
        </button>
        <button
          type="button"
          className={styles.tool}
          aria-label="Insert personalization variable"
          aria-haspopup="true"
          aria-expanded={openPanel === "variable"}
          aria-controls="web-rich-variable-panel"
          aria-describedby={
            variables.length === 0 ? "web-rich-variable-unavailable" : undefined
          }
          title={
            variables.length === 0
              ? "No account variable catalog is available."
              : "Insert personalization variable"
          }
          disabled={disabled || variables.length === 0 || selection.collapsed}
          onClick={() => togglePanel("variable")}
        >
          {"{ }"}
        </button>
        <button
          type="button"
          className={styles.tool}
          aria-label="Clear formatting"
          title="Clear visual formatting; keep links and variables"
          disabled={disabled || selection.collapsed}
          onClick={() => command(nodeId, { type: "clear_formatting" })}
        >
          Tx
        </button>
      </div>

      {variables.length === 0 ? (
        <span id="web-rich-variable-unavailable" className="sr-only">
          Add an account before inserting personalization variables.
        </span>
      ) : null}

      {openPanel === "text_color" ? (
        <ColorPanel
          id="web-rich-text-color-panel"
          label="Text color"
          prefix="text-"
          state={selection}
          tokens={tokens}
          disabled={disabled}
          onPick={(token) => setColor("text_color", token)}
        />
      ) : null}
      {openPanel === "highlight" ? (
        <ColorPanel
          id="web-rich-highlight-panel"
          label="Highlight color"
          prefix="bg-"
          state={selection}
          tokens={tokens}
          disabled={disabled}
          onPick={(token) => setColor("highlight", token)}
        />
      ) : null}
      {openPanel === "link" ? (
        <form
          id="web-rich-link-panel"
          className={`${styles.popover} ${styles.form}`}
          aria-label="Link settings"
          onSubmit={submitLink}
        >
          <label>
            <span>URL</span>
            <input
              value={linkHref}
              onChange={(event) => {
                setLinkHref(event.target.value);
                setLinkError(null);
              }}
              placeholder="https://example.com"
              autoFocus
              disabled={disabled}
              aria-invalid={Boolean(linkError)}
              aria-describedby={linkError ? "web-rich-link-error" : undefined}
            />
          </label>
          <label className={styles.check}>
            <input
              type="checkbox"
              checked={linkNewTab}
              disabled={disabled}
              onChange={(event) => setLinkNewTab(event.target.checked)}
            />
            Open in a new tab
          </label>
          {linkError ? (
            <p id="web-rich-link-error" className={styles.error} role="alert">
              {linkError}
            </p>
          ) : null}
          <div className={styles.formActions}>
            {selection.link.state !== "off" ? (
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  command(nodeId, { type: "remove_link" });
                  setOpenPanel(null);
                }}
              >
                Remove link
              </button>
            ) : null}
            <button type="submit" disabled={disabled}>
              Apply link
            </button>
          </div>
        </form>
      ) : null}
      {openPanel === "variable" ? (
        <form
          id="web-rich-variable-panel"
          className={`${styles.popover} ${styles.form}`}
          aria-label="Personalization variable"
          onSubmit={submitVariable}
        >
          <label>
            <span>Variable</span>
            <select
              value={variableKey}
              disabled={disabled}
              onChange={(event) => {
                setVariableKey(event.target.value);
                setVariableError(null);
              }}
              autoFocus
            >
              {variables.map((variable) => (
                <option key={variable.key} value={variable.key}>
                  {variable.label} — {variable.key}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Visible fallback</span>
            <input
              value={variableFallback}
              disabled={disabled}
              onChange={(event) => {
                setVariableFallback(event.target.value);
                setVariableError(null);
              }}
              aria-invalid={Boolean(variableError)}
              aria-describedby={
                variableError ? "web-rich-variable-error" : undefined
              }
            />
          </label>
          {variableError ? (
            <p
              id="web-rich-variable-error"
              className={styles.error}
              role="alert"
            >
              {variableError}
            </p>
          ) : null}
          <button type="submit" disabled={disabled}>
            Insert variable
          </button>
        </form>
      ) : null}
    </div>
  );
}
