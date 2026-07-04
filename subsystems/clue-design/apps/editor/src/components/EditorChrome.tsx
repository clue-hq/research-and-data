"use client";

import { AlertTriangle, History } from "lucide-react";
import type { Operation, Page } from "@/engine/contracts";
import { EDITOR_PANEL_MODES, type EditorPanelMode } from "@/engine/editorModes";
import { operationLabel } from "@/engine/operationLabels";
import { pageDescriptor } from "@/engine/renderAdapter";

/** Small presentational pieces of the editor shell — topbar chrome, the
 * local operation-history section, and the engine-disabled banner. No
 * workflow policy lives here: everything is props in, callbacks out. */

export function EditorModeSwitch({
  mode,
  onModeChange
}: {
  mode: EditorPanelMode;
  onModeChange: (mode: EditorPanelMode) => void;
}) {
  return (
    <div className="top-mode-switch" aria-label="Editor mode">
      {EDITOR_PANEL_MODES.map((item) => (
        <button
          key={item.mode}
          type="button"
          className={mode === item.mode ? "active" : undefined}
          aria-label={item.ariaLabel}
          aria-pressed={mode === item.mode}
          onClick={() => onModeChange(item.mode)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function topArtboardSizeLabel(page: Page): string {
  const descriptor = pageDescriptor(page);
  return `${formatTopbarDimension(descriptor.width)} x ${formatTopbarDimension(descriptor.height)} pt`;
}

function formatTopbarDimension(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1).replace(/\.0$/, "");
}

export function OperationHistoryPanel({
  operations,
  redoCount
}: {
  operations: Operation[];
  redoCount: number;
}) {
  const recentOperations = operations.slice(-6).reverse();

  return (
    <section className="inspector-section">
      <div className="section-heading">
        <History aria-hidden size={15} />
        Operation history
      </div>
      {operations.length === 0 ? (
        <p className="muted">No accepted editor operations yet.</p>
      ) : (
        <ol className="operation-history-list">
          {recentOperations.map((operation, index) => (
            <li key={`${operations.length - index}-${operation.kind}`}>
              <span>{operations.length - index}</span>
              <code>{operationLabel(operation)}</code>
            </li>
          ))}
        </ol>
      )}
      {redoCount > 0 ? <p className="muted">{redoCount} action{redoCount === 1 ? "" : "s"} available to redo.</p> : null}
    </section>
  );
}

/**
 * Always-visible error signal for diagnostics that would otherwise be
 * invisible outside the Diagnostics panel (sticky persistence failures
 * surfaced mid-agent-chat, export errors while inspecting, …). Renders
 * nothing when there are no errors; clicking opens the Diagnostics panel.
 */
export function DiagnosticsAlertPill({
  errorCount,
  onOpen
}: {
  errorCount: number;
  onOpen: () => void;
}) {
  if (errorCount === 0) {
    return null;
  }
  return (
    <button
      type="button"
      className="diagnostics-alert-pill"
      data-testid="diagnostics-alert-pill"
      onClick={onOpen}
    >
      <AlertTriangle aria-hidden size={13} />
      {errorCount} error{errorCount === 1 ? "" : "s"}
    </button>
  );
}

/** Reason-specific copy for the server-only-mode canvas banner. */
function engineDisabledCopy(reason: "load_failed" | "handshake_failed" | "version_mismatch"): {
  headline: string;
  fix: string;
} {
  switch (reason) {
    case "version_mismatch":
      return {
        headline: "The in-browser engine is a different build than the API.",
        fix: "Rebuild it to match, then hard-refresh (⌘⇧R):"
      };
    case "handshake_failed":
      return {
        headline: "Couldn’t verify the in-browser engine against the API.",
        fix: "Start the API, rebuild the engine, then hard-refresh (⌘⇧R):"
      };
    case "load_failed":
    default:
      return {
        headline: "The in-browser engine failed to load.",
        fix: "Build it, then hard-refresh (⌘⇧R):"
      };
  }
}

/**
 * Loud, persistent banner shown when the WASM engine is expected but not
 * active (server-only mode). Without the live engine the canvas cannot
 * hit-test, so nothing can be selected or edited — a failure that must never
 * again read as "the editor is silently broken."
 */
export function EngineDisabledBanner({
  reason,
  detail
}: {
  reason: "load_failed" | "handshake_failed" | "version_mismatch";
  detail: string;
}) {
  const copy = engineDisabledCopy(reason);
  return (
    <div className="engine-disabled-banner" role="alert" data-testid="engine-disabled-banner">
      <AlertTriangle aria-hidden size={18} className="engine-disabled-banner-icon" />
      <div className="engine-disabled-banner-body">
        <strong>Canvas editing is disabled</strong>
        <span>
          {copy.headline} You can’t select or edit anything on the canvas until the in-browser
          engine is running. {copy.fix}
        </span>
        <code>
          <span className="engine-disabled-banner-cmd">npm run build:wasm</span>
          {` · ${detail}`}
        </code>
      </div>
    </div>
  );
}
