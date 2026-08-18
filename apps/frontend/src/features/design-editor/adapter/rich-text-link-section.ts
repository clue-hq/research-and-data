import type {
  RichTextCommand,
  RichTextFormatValue,
  RichTextSelectionState,
} from "../engine/webBridge";
import { richTextLinkSubmission } from "../components/web-rich-text-toolbar.logic";

/**
 * W4.8b — the pure decisions behind the TEXT schema's conditional "Link to"
 * section (`web-inspector.tsx`, TextControls region).
 *
 * The binding contract, item 3
 * (`docs/specs/website-editor-integration/web-inspector-mapping-contract.md`):
 * the Text → "Link to" section is hidden by default and appears — functional —
 * only while a rich-text range is selected. It binds to the RANGE link, never
 * to a whole-node href (which does not exist for text). Hidden = ABSENT (§2),
 * not disabled.
 *
 * Every function here is pure so it is testable under this repo's renderer-free
 * runner (`tsx --test`, node:test) — the same extraction pattern as
 * `components/web-rich-text-toolbar.logic.ts`, whose `richTextLinkSubmission`
 * this module reuses rather than restating: the inspector and the canvas
 * toolbar are two surfaces over ONE validated href path, so their grammar and
 * their error copy can never drift apart.
 */

/** The mirrored rich-text session this section reads (the canvas's
 * `WebRichTextSessionState`, minus the error slot it does not consult). */
export interface RichTextLinkSessionState {
  editingNodeId: string | null;
  richTextSelection: RichTextSelectionState | null;
}

/**
 * Ledgered lane ruling (2026-08-18) — the section renders iff a session is open
 * AND its live selection is actionable:
 *
 *   editingNodeId !== null && richTextSelection !== null &&
 *   ((!collapsed && selectedText.length > 0) || link.state === "on")
 *
 * This is the toolbar's own actionable-selection predicate (scout §3;
 * `WebRichTextToolbar.tsx:189-192`), so the two surfaces sharing the validated
 * href path can never disagree about whether there is a link to edit.
 *
 * One deliberate difference from `richTextToolbarValidContext`: that gate also
 * mounts the toolbar for a `structured` selection, because the toolbar carries
 * BLOCK controls (paragraph/list/indent) which act on a bare caret. Link-to has
 * no such control — with a collapsed caret outside a link there is no range to
 * bind an href to — so a structured caret alone does not summon this section.
 * Anything else is ABSENT: no disabled fields, no empty shell.
 */
export function richTextLinkSectionVisible(
  session: RichTextLinkSessionState,
): boolean {
  const selection = session.richTextSelection;
  if (session.editingNodeId === null || selection === null) return false;
  return (
    (!selection.collapsed && selection.selectedText.length > 0) ||
    selection.link.state === "on"
  );
}

export interface RichTextLinkPrefill {
  href: string;
  newTab: boolean;
}

/**
 * The toolbar's own prefill semantics (`WebRichTextToolbar.tsx:276-282`): an
 * existing link fills both fields, anything else (off, mixed, a null href
 * riding along) starts empty. Never surfaces `null` to the DOM — a controlled
 * input needs a string.
 */
export function richTextLinkPrefill(
  selection: RichTextSelectionState,
): RichTextLinkPrefill {
  const linked = selection.link.state === "on";
  return {
    href: linked ? (selection.link.href ?? "") : "",
    newTab: linked ? Boolean(selection.link.newTab) : false,
  };
}

/** What produced the commit: the URL field settling (blur/Enter), or the
 * new-tab checkbox changing. They differ only in how they treat an href that
 * is not usable — see {@link richTextLinkCommit}. */
export type RichTextLinkTrigger = "submit" | "toggle";

export type RichTextLinkCommitDecision =
  /** Nothing to send and nothing to say. */
  | { kind: "none" }
  /** The href failed the shared grammar — show this, send nothing. */
  | { kind: "invalid"; error: string }
  /** Exactly one range-link command for `commandRichText`. */
  | { kind: "command"; command: RichTextCommand };

/**
 * The write decision. Range link COMMANDS only — a range link is never a node
 * prop, so this path must never reach `setValue("url", …)` /
 * `clue:inspector-property-change` (contract item 3).
 *
 * Failure/empty semantics (ledgered ruling, 2026-08-18):
 * - an empty URL committed while the range IS linked → `remove_link`;
 * - an empty URL otherwise → a no-op (never the "Enter a link URL." scold,
 *   which belongs to the toolbar's explicit Apply button, not to a field the
 *   user simply tabbed through);
 * - anything else is validated FIRST with the shared `richTextHrefError`
 *   grammar, so an invalid href yields the error string and no command.
 *
 * The checkbox (`trigger: "toggle"`) commits immediately, but only when a valid
 * href is already present: toggling "open in a new tab" must never remove a
 * link and never scold about a URL the user has not finished typing.
 */
export function richTextLinkCommit({
  href,
  linkState,
  newTab,
  trigger,
}: {
  href: string;
  linkState: RichTextFormatValue;
  newTab: boolean;
  trigger: RichTextLinkTrigger;
}): RichTextLinkCommitDecision {
  if (!href.trim()) {
    if (trigger === "submit" && linkState === "on") {
      return { kind: "command", command: { type: "remove_link" } };
    }
    return { kind: "none" };
  }
  const submission = richTextLinkSubmission(href, newTab);
  if (!submission.ok) {
    return trigger === "toggle"
      ? { kind: "none" }
      : { kind: "invalid", error: submission.error };
  }
  return { kind: "command", command: submission.command };
}

/**
 * What the inspector needs to render and drive the section, shaped so
 * presentation stays transport-free: a value snapshot in, callbacks out. The
 * senders live with the canvas bridge; the surface between them only speaks
 * hrefs and booleans.
 */
export interface RichTextLinkBinding {
  /** The text node whose session is live — the section's remount identity. */
  nodeId: string;
  selection: RichTextSelectionState;
  /**
   * Focus is moving into (true) or out of (false) these controls. The iframe
   * bridge commits an edit session 180ms after its contenteditable loses focus
   * (`web_bridge.py:415-422,548-555`) unless it is told the parent is holding
   * focus deliberately — without this the section would settle its own session
   * the moment the user clicked into the URL field.
   */
  onInteractionChange: (active: boolean) => void;
  /** The raw draft; the owner decides with {@link richTextLinkCommit}. */
  onSubmitLink: (
    href: string,
    newTab: boolean,
    trigger: RichTextLinkTrigger,
  ) => void;
}
