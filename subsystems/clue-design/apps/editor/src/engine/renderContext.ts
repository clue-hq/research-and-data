import type { Diagnostic, DocumentMeta } from "./contracts";

/** Shared WASM context contract. Standalone application loading remains unchanged. */
export interface RenderContext {
  context_key: string;
  document_id: string;
  document_version: number;
  scene_brand_ref: { id: string; version: number } | null;
  scene_medium: DocumentMeta["medium"];
  source: string;
  brand_kit: { id: string; version: number; [key: string]: unknown } | null;
  mode: { values: Record<string, string> } | null;
  diagnostics: Diagnostic[];
}
