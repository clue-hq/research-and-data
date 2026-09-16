import { z } from "zod";

export const ResearchEntitySchema = z.enum(["accounts", "contacts"]);
export type ResearchEntity = z.infer<typeof ResearchEntitySchema>;

export const ResearchFieldSchema = z.object({
  key: z.string().min(1),
  label: z.string().min(1),
  description: z.string(),
  origin: z.enum(["platform", "workspace"]),
  created_by: z.string().nullable(),
  created_at: z.string().datetime({ offset: true }).nullable(),
});
export type ResearchField = z.infer<typeof ResearchFieldSchema>;
export const ResearchFieldsSchema = z.object({
  entity: ResearchEntitySchema,
  rows: z.array(ResearchFieldSchema),
});
export type ResearchFields = z.infer<typeof ResearchFieldsSchema>;
export type ResearchFieldEdit = Partial<Pick<ResearchField, "label" | "description">>;
