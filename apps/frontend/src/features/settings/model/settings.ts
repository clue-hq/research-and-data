import { z } from "zod";

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

export const DataModelEntitySchema = z.enum(["accounts", "contacts"]);
export const DataModelViewSchema = z.enum(["fields", "display"]);
export type DataModelEntity = z.infer<typeof DataModelEntitySchema>;
export type DataModelView = z.infer<typeof DataModelViewSchema>;

const DataModelFieldSchema = z.object({
  id: z.string(),
  name: z.string(),
  type: z.string(),
  editableBy: z.string(),
  aiFill: z.enum(["Auto", "None"]),
  system: z.boolean(),
});

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
  dataModel: z.object({
    entities: z.array(
      z.object({ id: DataModelEntitySchema, name: z.string() }),
    ),
    fields: z.array(DataModelFieldSchema),
    display: z.object({
      alwaysShown: z.array(z.string()),
      collapsed: z.array(z.string()),
    }),
  }),
  pages: z.object({
    customDomain: z.string(),
    fallbackUrl: z.string(),
    pageTitle: z.string(),
    pageDescription: z.string(),
    faviconPath: z.string().nullable(),
    socialPreviewPath: z.string().nullable(),
    allowIndexing: z.boolean(),
    allowFollowing: z.boolean(),
    headHtml: z.string(),
    bodyHtml: z.string(),
    llmsText: z.string(),
    autoGenerateLlmsText: z.boolean(),
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
