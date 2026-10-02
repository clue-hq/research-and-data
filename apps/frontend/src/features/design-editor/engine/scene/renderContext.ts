import { z } from "zod";
import type { Diagnostic, DocumentMeta } from "./contracts";

const pin = z.object({ id: z.string().min(1), version: z.number().int().positive() });
const diagnostic = z.object({ severity: z.enum(["error", "warning", "advice"]),
  phase: z.string(), code: z.string(), message: z.string(),
  subject: z.unknown().optional(), hint: z.string().nullable().optional() });
/** Validate identity and selection at the data seam; Rust owns kit/token semantics. */
export const renderContextSchema = z.object({
  context_key: z.string().min(1), document_id: z.string().min(1),
  document_version: z.number().int().nonnegative(), scene_brand_ref: pin.nullable(),
  scene_medium: z.string().nullable(), source: z.string(),
  brand_kit: pin.extend({ tokens: z.record(z.string(), z.unknown()).optional() }).passthrough().nullable(),
  mode: z.object({ values: z.record(z.string(), z.string()) }).nullable(),
  diagnostics: z.array(diagnostic),
});
export type RenderContext = Omit<z.infer<typeof renderContextSchema>, "diagnostics" | "scene_medium"> & {
  diagnostics: Diagnostic[]; scene_medium: DocumentMeta["medium"];
};
export function parseRenderContext(value: unknown, documentId: string, version: number | null): RenderContext | null {
  if (value == null) return null;
  const context = renderContextSchema.parse(value);
  if (context.document_id !== documentId || (version !== null && context.document_version !== version)) {
    throw new Error("Render context belongs to another document or version");
  }
  return context as RenderContext;
}
