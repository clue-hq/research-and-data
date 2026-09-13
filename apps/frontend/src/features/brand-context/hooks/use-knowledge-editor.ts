import { useRouter } from "next/navigation";
import type { BrandKnowledgeDocument } from "../model/brand-context";
import { saveKnowledgeDocument } from "../data/brand-knowledge-actions";
import { useVersionedMarkdownEditor } from "@/components/markdown/use-versioned-markdown-editor";

export function useKnowledgeEditor(document: BrandKnowledgeDocument | undefined, options: { scopeKey: string; canWrite: boolean }) {
  const router = useRouter();
  return useVersionedMarkdownEditor(document, { ...options, saveDocument: saveKnowledgeDocument, onSaved: () => router.refresh() });
}
