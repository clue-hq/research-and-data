"use client";

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject
} from "react";

import {
  type RichTextCommand,
  type RichTextFormatValue,
  type RichTextSelectionState
} from "@/engine/webBridge";
import type {
  WebRichTextVariable,
  WebTheme
} from "@/engine/webDocuments";
import {
  RICH_TEXT_MARK_CONTROLS,
  richTextAriaPressed,
  richTextHrefError
} from "@/engine/webRichText";

type ToolbarPanel = "text_color" | "highlight" | "link" | "variable";

interface ToolbarPosition {
  left: number;
  top: number;
  placement: "above" | "below";
}

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

const EDGE_GAP = 12;
const RANGE_GAP = 10;

function classFacetValue(
  state: RichTextSelectionState,
  prefix: "text-" | "bg-",
  tokenNames: string[]
): { value: string | null; state: RichTextFormatValue } {
  const matchingCommon = tokenNames.filter((token) =>
    state.commonClasses.includes(`${prefix}${token}`)
  );
  const hasMixed = tokenNames.some((token) =>
    state.mixedClasses.includes(`${prefix}${token}`)
  );
  if (matchingCommon.length === 1 && !hasMixed) {
    return { value: matchingCommon[0], state: "on" };
  }
  if (matchingCommon.length > 1 || hasMixed) {
    return { value: matchingCommon[0] ?? null, state: "mixed" };
  }
  return { value: null, state: "off" };
}

function ColorPanel({
  id,
  label,
  prefix,
  state,
  tokens,
  disabled,
  onPick
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
    tokens.map(([name]) => name)
  );
  return (
    <div id={id} className="web-rich-popover" role="group" aria-label={label}>
      <div className="web-rich-popover-head">{label}</div>
      {tokens.length > 0 ? (
        <div className="web-rich-swatches">
          {tokens.map(([name, color]) => (
            <button
              key={name}
              type="button"
              className={`web-rich-swatch${
                facet.value === name ? " is-selected" : ""
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
                className="web-rich-swatch-color"
                style={{ backgroundColor: color }}
                aria-hidden="true"
              />
              <span>{name}</span>
            </button>
          ))}
          <button
            type="button"
            className="web-rich-swatch is-clear"
            disabled={disabled}
            onClick={() => onPick(null)}
          >
            Clear
          </button>
        </div>
      ) : (
        <p className="web-rich-popover-hint">No resolved theme colors are available.</p>
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

export function WebRichTextToolbar({
  iframeRef,
  nodeId,
  selection,
  theme,
  variables,
  disabled,
  command,
  setInteractionActive,
  settle
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

  const tokens = Object.entries(theme?.tokens ?? {}).sort(([left], [right]) =>
    left.localeCompare(right)
  );
  const tokenNames = tokens.map(([name]) => name);
  const textColor = classFacetValue(selection, "text-", tokenNames);
  const highlight = classFacetValue(selection, "bg-", tokenNames);
  const validContext =
    (!selection.collapsed && selection.selectedText.length > 0) ||
    (selection.collapsed && selection.link.state === "on");

  const recomputePosition = useCallback(() => {
    const iframe = iframeRef.current;
    const range = selection.rect;
    const toolbar = toolbarRef.current;
    if (!iframe || !range || !toolbar || !validContext) {
      setPosition(null);
      return;
    }
    const frameRect = iframe.getBoundingClientRect();
    const rangeTop = frameRect.top + range.top;
    const rangeBottom = frameRect.top + range.bottom;
    const rangeCenter = frameRect.left + range.left + range.width / 2;
    if (
      rangeBottom < frameRect.top ||
      rangeTop > frameRect.bottom ||
      rangeCenter < frameRect.left ||
      rangeCenter > frameRect.right
    ) {
      setPosition(null);
      return;
    }
    const toolbarRect = toolbar.getBoundingClientRect();
    const left = Math.min(
      window.innerWidth - toolbarRect.width - EDGE_GAP,
      Math.max(EDGE_GAP, rangeCenter - toolbarRect.width / 2)
    );
    const above = rangeTop - toolbarRect.height - RANGE_GAP;
    const placement = above >= EDGE_GAP ? "above" : "below";
    const top =
      placement === "above"
        ? above
        : Math.min(
            window.innerHeight - toolbarRect.height - EDGE_GAP,
            rangeBottom + RANGE_GAP
          );
    setPosition({ left, top: Math.max(EDGE_GAP, top), placement });
  }, [iframeRef, selection.rect, validContext]);

  useLayoutEffect(() => {
    recomputePosition();
  }, [recomputePosition, openPanel]);

  useEffect(() => {
    const handleViewportChange = () => recomputePosition();
    window.addEventListener("resize", handleViewportChange, { passive: true });
    window.addEventListener("scroll", handleViewportChange, {
      capture: true,
      passive: true
    });
    return () => {
      window.removeEventListener("resize", handleViewportChange);
      window.removeEventListener("scroll", handleViewportChange, true);
    };
  }, [recomputePosition]);

  useEffect(() => {
    setOpenPanel(null);
    setLinkError(null);
    setVariableError(null);
  }, [nodeId]);

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
    document.addEventListener("pointerdown", handleOutsidePointer, true);
    return () =>
      document.removeEventListener("pointerdown", handleOutsidePointer, true);
  }, [nodeId, openPanel, settle]);

  const togglePanel = (panel: ToolbarPanel) => {
    if (openPanel === panel) {
      setOpenPanel(null);
      setInteractionActive(nodeId, false);
      return;
    }
    if (panel === "link") {
      setLinkHref(selection.link.state === "on" ? selection.link.href ?? "" : "");
      setLinkNewTab(
        selection.link.state === "on" ? Boolean(selection.link.newTab) : false
      );
      setLinkError(null);
    }
    if (panel === "variable") {
      const first = variables[0] ?? null;
      setVariableKey(first?.key ?? "");
      setVariableFallback(
        selection.selectedText.trim() || first?.example?.trim() || ""
      );
      setVariableError(null);
    }
    setInteractionActive(nodeId, true);
    setOpenPanel(panel);
  };

  const setColor = (
    facet: "text_color" | "highlight",
    token: string | null
  ) => {
    command(nodeId, {
      type: "set_class_facet",
      facet,
      token,
      knownTokens: tokenNames
    });
    setOpenPanel(null);
  };

  const submitLink = (event: React.FormEvent) => {
    event.preventDefault();
    const error = richTextHrefError(linkHref);
    if (error) {
      setLinkError(error);
      return;
    }
    command(nodeId, {
      type: "set_link",
      href: linkHref.trim(),
      newTab: linkNewTab
    });
    setOpenPanel(null);
  };

  const submitVariable = (event: React.FormEvent) => {
    event.preventDefault();
    const fallback = variableFallback.trim();
    if (!variableKey || !variables.some((variable) => variable.key === variableKey)) {
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
      fallback
    });
    setOpenPanel(null);
  };

  if (!validContext || !selection.rect) {
    return null;
  }

  return (
    <div
      ref={toolbarRef}
      className={`web-rich-toolbar${
        position ? " is-positioned" : ""
      } is-${position?.placement ?? "above"}`}
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
            const active = document.activeElement;
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
      <div className="web-rich-toolbar-row">
        {RICH_TEXT_MARK_CONTROLS.map((control) => (
          <button
            key={control.format}
            type="button"
            className={`web-rich-tool${
              selection.formats[control.format] === "on" ? " is-selected" : ""
            }${
              selection.formats[control.format] === "mixed" ? " is-mixed" : ""
            }`}
            aria-label={control.label}
            aria-pressed={richTextAriaPressed(
              selection.formats[control.format]
            )}
            title={`${control.label} (${control.shortcut})`}
            disabled={disabled}
            onClick={() =>
              command(nodeId, { type: "format", format: control.format })
            }
          >
            <span
              className={`web-rich-glyph is-${control.format}`}
              aria-hidden="true"
            >
              {control.glyph}
            </span>
          </button>
        ))}
        <span className="web-rich-divider" aria-hidden="true" />
        <button
          type="button"
          className={`web-rich-tool${textColor.state === "mixed" ? " is-mixed" : ""}`}
          aria-label="Text color"
          aria-pressed={richTextAriaPressed(textColor.state)}
          aria-haspopup="true"
          aria-expanded={openPanel === "text_color"}
          aria-controls="web-rich-text-color-panel"
          title="Text color"
          disabled={disabled || tokens.length === 0}
          onClick={() => togglePanel("text_color")}
        >
          <span className="web-rich-color-glyph" aria-hidden="true">
            A
            <span
              style={{
                backgroundColor: textColor.value
                  ? theme?.tokens[textColor.value]
                  : undefined
              }}
            />
          </span>
        </button>
        <button
          type="button"
          className={`web-rich-tool${highlight.state === "mixed" ? " is-mixed" : ""}`}
          aria-label="Highlight color"
          aria-pressed={richTextAriaPressed(highlight.state)}
          aria-haspopup="true"
          aria-expanded={openPanel === "highlight"}
          aria-controls="web-rich-highlight-panel"
          title="Highlight color"
          disabled={disabled || tokens.length === 0}
          onClick={() => togglePanel("highlight")}
        >
          <span className="web-rich-highlight-glyph" aria-hidden="true">A</span>
        </button>
        <span className="web-rich-divider" aria-hidden="true" />
        <button
          type="button"
          className={`web-rich-tool${
            selection.link.state === "on" ? " is-selected" : ""
          }${selection.link.state === "mixed" ? " is-mixed" : ""}`}
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
          className="web-rich-tool"
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
          className="web-rich-tool"
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
          className="web-rich-popover web-rich-form"
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
          <label className="web-rich-check">
            <input
              type="checkbox"
              checked={linkNewTab}
              disabled={disabled}
              onChange={(event) => setLinkNewTab(event.target.checked)}
            />
            Open in a new tab
          </label>
          {linkError ? (
            <p id="web-rich-link-error" className="web-rich-error" role="alert">
              {linkError}
            </p>
          ) : null}
          <div className="web-rich-form-actions">
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
          className="web-rich-popover web-rich-form"
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
              className="web-rich-error"
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
