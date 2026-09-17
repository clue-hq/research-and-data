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

export const WorkspaceMemberSchema = z.object({
  id: z.string(),
  name: z.string(),
  email: z.string().email(),
  joinedOn: z.string(),
  role: z.enum(["Admin", "Member"]),
});

export const DataModelFieldSchema = z.object({
  id: z.string(),
  name: z.string(),
  type: z.string(),
  editableBy: z.string(),
  aiFill: z.enum(["Auto", "None"]),
  system: z.boolean(),
});

export const SettingsWorkspaceSchema = z.object({
  profile: z.object({
    id: z.string().min(1).optional(),
    avatarUrl: z.string().optional(),
    fullName: z.string(),
    displayName: z.string(),
    initials: z.string(),
    avatarColor: z.string(),
  }),
  connections: z.array(ConnectionSchema),
  workspace: z.object({
    name: z.string(),
    website: z.string().url(),
    logoPath: z.string().nullable(),
  }),
  members: z.array(WorkspaceMemberSchema),
  billing: z.object({
    planName: z.string(),
    planDescription: z.string(),
    remainingCredits: z.number().int().nonnegative(),
    totalCredits: z.number().int().positive(),
  }),
  dataModel: z.object({
    entities: z.array(
      z.object({
        id: z.string(),
        name: z.string(),
      }),
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

export type SettingsWorkspace = z.infer<typeof SettingsWorkspaceSchema>;

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
