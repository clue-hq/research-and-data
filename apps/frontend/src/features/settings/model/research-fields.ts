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

export const ResearchFieldInputSchema = z.object({
  label: z.string().trim().min(1, "Name is required.").max(200, "Use 200 characters or fewer."),
  description: z.string().trim().min(1, "Description is required.").max(2000, "Use 2,000 characters or fewer."),
});
export type ResearchFieldAttribute = "label" | "description";

export const researchEntities = [
  { id: "accounts", name: "Accounts", description: "Company facts, signals and research instructions" },
  { id: "contacts", name: "Contacts", description: "Professional context and person research instructions" },
] as const;

export function researchFieldCreatedLabel(value: string | null) {
  if (!value) return null;
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
  }).format(new Date(value));
}
