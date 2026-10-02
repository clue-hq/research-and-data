import type { MarkdownEditorStatus } from "@/components/markdown/markdown-session";

export interface MarkdownDocument { id: string; path: string; body: string; version?: number; bodyLoaded?: boolean }

export interface MarkdownDocumentSession<D extends MarkdownDocument> {
  base: D;
  body: string;
  resetKey: number;
  mode: "preview" | "edit";
  opened: boolean;
  error: string | null;
  validation: MarkdownEditorStatus;
  saved: boolean;
}
const valid: MarkdownEditorStatus = { error: null, viewMode: "rich-text" };

export function markdownDocumentSession<D extends MarkdownDocument>(document: D): MarkdownDocumentSession<D> {
  return { base: document, body: document.body, resetKey: 0, mode: "preview", opened: false, error: null, validation: valid, saved: false };
}

export function markdownDocumentSessionDirty<D extends MarkdownDocument>(session: MarkdownDocumentSession<D>): boolean {
  return session.body !== session.base.body;
}

/** A dirty draft always keeps the revision it was typed over. */
export function acceptMarkdownDocument<D extends MarkdownDocument>(session: MarkdownDocumentSession<D> | undefined, document: D): MarkdownDocumentSession<D> {
  if (!session) return markdownDocumentSession(document);
  if (markdownDocumentSessionDirty(session) || (document.version ?? 0) < (session.base.version ?? 0)) return session;
  if (document.id === session.base.id && document.body === session.base.body && document.bodyLoaded === session.base.bodyLoaded) return session;
  const changed = document.body !== session.body;
  return { ...session, base: document, body: document.body, resetKey: session.resetKey + Number(changed), validation: changed ? valid : session.validation };
}

export function changeMarkdownDocumentBody<D extends MarkdownDocument>(session: MarkdownDocumentSession<D>, body: string): MarkdownDocumentSession<D> {
  return body === session.body ? session : { ...session, body };
}

export function discardMarkdownDocumentDraft<D extends MarkdownDocument>(session: MarkdownDocumentSession<D>, latest: D): MarkdownDocumentSession<D> {
  const base = (latest.version ?? 0) >= (session.base.version ?? 0) ? latest : session.base;
  return { ...session, base, body: base.body, resetKey: session.resetKey + 1, validation: valid, error: null };
}

export function acceptMarkdownDocumentSave<D extends MarkdownDocument>(session: MarkdownDocumentSession<D>, saved: D, submitted: string): MarkdownDocumentSession<D> {
  const body = session.body === submitted ? saved.body : session.body;
  return { ...session, base: saved, body, saved: true, error: null, resetKey: session.resetKey + Number(body !== session.body) };
}
