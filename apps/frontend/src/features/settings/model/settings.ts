import { z } from "zod";
import { CrmProviderSchema, type CrmProvider } from "@/features/integrations/model/crm";
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

export interface SettingsRoute {
  section: SettingsSection;
  /** Data model only: the entity and its view. */
  entity?: DataModelEntity;
  view?: DataModelView;
  /** Integrations only: the connected CRM's own page. */
  provider?: CrmProvider;
}

const NestedRouteSchema = z.union([
  z.object({
    section: z.literal("data-model"),
    entity: DataModelEntitySchema.optional(),
    view: DataModelViewSchema.optional(),
  }),
  z.object({
    section: z.literal("integrations"),
    entity: CrmProviderSchema.optional(),
    view: z.undefined(),
  }),
  z.object({
    section: SettingsSectionSchema.exclude(["data-model", "integrations"]),
    entity: z.undefined(),
    view: z.undefined(),
  }),
]);

/**
 * `/settings/[section]/[...]`: Data model nests `{entity}/{fields|display}`, Integrations nests
 * the connected CRM (`/settings/integrations/{hubspot|salesforce}`); nothing else nests.
 */
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
  .pipe(NestedRouteSchema)
  .transform((route): SettingsRoute => {
    if (route.section === "data-model") {
      return { section: route.section, entity: route.entity, view: route.view };
    }
    if (route.section === "integrations") {
      return route.entity
        ? { section: route.section, provider: route.entity }
        : { section: route.section };
    }
    return { section: route.section };
  });
