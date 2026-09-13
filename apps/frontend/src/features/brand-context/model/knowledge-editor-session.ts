import type { BrandKnowledgeDocument } from "./brand-context";
import type { MarkdownEditorStatus } from "@/components/markdown/markdown-session";

export interface KnowledgeEditorSession {
  base: BrandKnowledgeDocument;
  body: string;
  resetKey: number;
  mode: "preview" | "edit";
  opened: boolean;
  error: string | null;
  validation: MarkdownEditorStatus;
  saved: boolean;
}
const valid: MarkdownEditorStatus = { error: null, viewMode: "rich-text" };

export function knowledgeSession(document: BrandKnowledgeDocument): KnowledgeEditorSession {
  return { base: document, body: document.body, resetKey: 0, mode: "preview", opened: false, error: null, validation: valid, saved: false };
}

export function knowledgeSessionDirty(session: KnowledgeEditorSession): boolean {
  return session.body !== session.base.body;
}

/** A dirty draft always keeps the revision it was typed over. */
export function acceptKnowledgeDocument(session: KnowledgeEditorSession | undefined, document: BrandKnowledgeDocument): KnowledgeEditorSession {
  if (!session) return knowledgeSession(document);
  if (knowledgeSessionDirty(session) || (document.version ?? 0) < (session.base.version ?? 0)) return session;
  if (document.id === session.base.id && document.body === session.base.body && document.bodyLoaded === session.base.bodyLoaded) return session;
  const changed = document.body !== session.body;
  return { ...session, base: document, body: document.body, resetKey: session.resetKey + Number(changed), validation: changed ? valid : session.validation };
}

export function changeKnowledgeBody(session: KnowledgeEditorSession, body: string): KnowledgeEditorSession {
  return body === session.body ? session : { ...session, body };
}

export function discardKnowledgeDraft(session: KnowledgeEditorSession, latest: BrandKnowledgeDocument): KnowledgeEditorSession {
  const base = (latest.version ?? 0) >= (session.base.version ?? 0) ? latest : session.base;
  return { ...session, base, body: base.body, resetKey: session.resetKey + 1, validation: valid, error: null };
}

export function acceptKnowledgeSave(session: KnowledgeEditorSession, saved: BrandKnowledgeDocument, submitted: string): KnowledgeEditorSession {
  const body = session.body === submitted ? saved.body : session.body;
  return { ...session, base: saved, body, saved: true, error: null, resetKey: session.resetKey + Number(body !== session.body) };
}
