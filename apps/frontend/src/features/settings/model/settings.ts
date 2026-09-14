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
  .transform((segments) => {
    const [section = "profile", entity, view] = segments;
    return {
      section: SettingsSectionSchema.parse(section),
      entity,
      view,
    };
  });

export type SettingsRoute = z.infer<typeof SettingsRouteSchema>;
