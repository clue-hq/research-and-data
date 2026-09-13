import type { BrandKnowledgeDocument } from "./brand-context";
import {
  markdownDocumentSession, markdownDocumentSessionDirty, acceptMarkdownDocument,
  changeMarkdownDocumentBody, discardMarkdownDocumentDraft, acceptMarkdownDocumentSave,
  type MarkdownDocumentSession,
} from "@/components/markdown/markdown-document-session";

export type KnowledgeEditorSession = MarkdownDocumentSession<BrandKnowledgeDocument>;
export const knowledgeSession = markdownDocumentSession<BrandKnowledgeDocument>;
export const knowledgeSessionDirty = markdownDocumentSessionDirty<BrandKnowledgeDocument>;
export const acceptKnowledgeDocument = acceptMarkdownDocument<BrandKnowledgeDocument>;
export const changeKnowledgeBody = changeMarkdownDocumentBody<BrandKnowledgeDocument>;
export const discardKnowledgeDraft = discardMarkdownDocumentDraft<BrandKnowledgeDocument>;
export const acceptKnowledgeSave = acceptMarkdownDocumentSave<BrandKnowledgeDocument>;
