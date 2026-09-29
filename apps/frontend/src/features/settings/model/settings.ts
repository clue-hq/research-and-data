import { z } from "zod";
import { ResearchEntitySchema } from "./research-fields";

export const SettingsSectionSchema = z.enum([
  "profile",
  "connections",
  "mcp-server",
  "workspace",
  "members",
  "integrations",
  "pages",
  "data-model",
  "billing",
]);

export type SettingsSection = z.infer<typeof SettingsSectionSchema>;

export const DataModelEntitySchema = ResearchEntitySchema;
export const DataModelViewSchema = z.enum(["fields", "display"]);
export type DataModelEntity = z.infer<typeof DataModelEntitySchema>;
export type DataModelView = z.infer<typeof DataModelViewSchema>;

export const ConnectionSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  logoPath: z.string(),
  status: z.enum(["available", "connected"]),
});

/** Preview-only sections; live settings have separate backend contract schemas. */
export const StaticSettingsSchema = z.object({
  connections: z.array(ConnectionSchema),
  billing: z.object({
    planName: z.string(),
    planDescription: z.string(),
    remainingCredits: z.number().int().nonnegative(),
    totalCredits: z.number().int().positive(),
  }),
});

export type StaticSettings = z.infer<typeof StaticSettingsSchema>;

export const SettingsRouteSchema = z
  .array(z.string())
  .max(3)
  .transform(
    ([section = "profile", entity, view]): {
      section: string;
      entity?: string;
      view?: string;
    } => ({ section, entity, view }),
  )
  .pipe(
    z
      .object({
        section: SettingsSectionSchema,
        entity: DataModelEntitySchema.optional(),
        view: DataModelViewSchema.optional(),
      })
      .refine(
        ({ section, entity, view }) =>
          section === "data-model" || (!entity && !view),
        "Only Data model supports nested settings routes",
      ),
  );

export type SettingsRoute = z.infer<typeof SettingsRouteSchema>;
