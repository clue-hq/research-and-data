import type { SceneClipboardPayloadV1 } from "./scene-clipboard";
import {
  SCENE_CLIPBOARD_MIME,
  decodeClipboardHtml,
  validateClipboardPayload,
} from "./scene-clipboard";

/**
 * Scene clipboard Task 6 — what a paste IS, decided before anything acts on it.
 *
 * Two pieces, deliberately separate. {@link snapshotClipboardData} copies a
 * live `DataTransfer` into plain data SYNCHRONOUSLY: the object is dead after
 * any async boundary (the Firefox lesson — one `await` and `files` is empty
 * and `getData` returns ""), so the copy must happen inside the event's own
 * turn. {@link classifyPaste} then decides over that plain snapshot, which
 * makes the decision pure and testable without a DOM or an event.
 *
 * Nothing here touches `window`, installs a listener, or calls
 * `preventDefault` — the event wiring (Task 7) composes these; they compose
 * nothing back.
 */

/** A `DataTransfer` copied into plain, inert data. */
export interface ClipboardSnapshot {
  /** Raw `application/vnd.clue.scene+json` — our own carrier, still unparsed. */
  internal: string;
  /** `text/html` — the Figma-style envelope's carrier when the internal mime
   * did not survive the OS clipboard (cross-tab, cross-app). */
  html: string;
  /** `text/plain`, verbatim — never trimmed here, so the plain-text class can
   * paste exactly what the user copied. */
  text: string;
  /** A real array, never the live `FileList`, which the browser empties when
   * the paste event ends. */
  files: File[];
}

/** What a paste is, in exactly one shape. */
export type PasteIntent =
  /** A Clue subtree — from EITHER internal carrier. Which one won is
   * deliberately invisible: the payload is identical, and downstream branching
   * on the carrier would be branching on browser trivia. */
  | { kind: "internal"; payload: SceneClipboardPayloadV1 }
  /** Allowlisted image files, plus the names of any dropped alongside them so
   * the caller can refuse LOUDLY rather than silently ingest a subset. */
  | { kind: "image-files"; files: File[]; rejected: string[] }
  | { kind: "svg-markup"; svg: string }
  | { kind: "plain-text"; text: string }
  | { kind: "none" };

/**
 * The image types a paste may ingest. An allowlist, not a blocklist: an
 * unknown type is refused, never guessed at. (`image/gif` is absent on
 * purpose — an animated frame has no honest still representation here.)
 */
export const ALLOWED_IMAGE_MIMES = [
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/svg+xml",
] as const;

/**
 * Copy everything a paste event carries, synchronously and totally.
 *
 * Total in both senses: every representation is read (no early return skips
 * one), and no read can throw out of here — some browsers throw on `getData`
 * for a type the clipboard does not hold, which must read as "absent", not as
 * a failed paste.
 */
export function snapshotClipboardData(dt: DataTransfer): ClipboardSnapshot {
  return {
    internal: readData(dt, SCENE_CLIPBOARD_MIME),
    html: readData(dt, "text/html"),
    text: readData(dt, "text/plain"),
    // Materialized now, while the event is still alive.
    files: Array.from(dt.files),
  };
}

function readData(dt: DataTransfer, type: string): string {
  try {
    return dt.getData(type);
  } catch {
    return "";
  }
}

/**
 * Decide what the snapshot is, first match wins:
 *
 *   1. the internal mime, parsed and validated;
 *   2. the html envelope, decoded and validated;
 *   3. allowlisted image files;
 *   4. text that IS an svg document;
 *   5. any other non-blank text;
 *   6. nothing.
 *
 * The ordering is the contract, and so is the FALL-THROUGH: a carrier that is
 * present but unreadable — mangled internal JSON, html with no envelope, a
 * file list with nothing allowed — hands the decision to the next class down
 * instead of dead-ending the paste. A copy that lost its internal mime in the
 * OS clipboard still pastes as a subtree via the envelope; a clipboard whose
 * every carrier is unreadable ends at `none`, which is an honest answer, not
 * a failure.
 */
export function classifyPaste(snap: ClipboardSnapshot): PasteIntent {
  const internal = parseInternalPayload(snap.internal);
  if (internal) {
    return { kind: "internal", payload: internal };
  }
  const enveloped = snap.html === "" ? null : decodeClipboardHtml(snap.html);
  if (enveloped) {
    return { kind: "internal", payload: enveloped };
  }

  const files = snap.files.filter(isAllowedImage);
  if (files.length > 0) {
    return {
      kind: "image-files",
      files,
      rejected: snap.files.filter((file) => !isAllowedImage(file)).map((file) => file.name),
    };
  }

  // Only the LEAD-IN is trimmed — enough to recognize an svg document that a
  // source prefixed with a BOM or indentation. `\s` covers U+FEFF, so one
  // strip handles both. What follows is the document, trailing bytes included.
  const lead = snap.text.replace(/^\s+/, "");
  if (lead === "") {
    return { kind: "none" };
  }
  if (SVG_ROOT.test(lead.replace(XML_PROLOG, ""))) {
    return { kind: "svg-markup", svg: lead };
  }
  return { kind: "plain-text", text: snap.text };
}

/** An optional XML prolog and the whitespace after it — an svg document may
 * lead with one, and it is part of the document, not part of the decision. */
const XML_PROLOG = /^<\?xml[\s\S]*?\?>\s*/i;
const SVG_ROOT = /^<svg\b/i;

/** The internal carrier, parsed and validated — null on ANY failure, so the
 * caller falls through. Untrusted input like any other: `JSON.parse` is
 * guarded and the result must clear the same strict validation the envelope
 * decode applies. */
function parseInternalPayload(raw: string): SceneClipboardPayloadV1 | null {
  if (raw === "") {
    return null;
  }
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  return validateClipboardPayload(value);
}

/** Mime types are case-insensitive, and some platforms stamp the non-standard
 * `image/jpg` on a JPEG. Nothing else is normalized — an extension is not
 * evidence of a type, so a mislabelled file is refused, not sniffed.
 *
 * Exported for Task 8's ingestion, which re-asks it for the gesture the
 * clipboard never sees (a canvas drag-drop). ONE allowlist test, so a dropped
 * `image/jpg` and a pasted one cannot get different answers. */
export function isAllowedImage(file: File): boolean {
  const mime = file.type.toLowerCase();
  const normalized = mime === "image/jpg" ? "image/jpeg" : mime;
  return (ALLOWED_IMAGE_MIMES as readonly string[]).includes(normalized);
}
