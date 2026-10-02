import { z } from "zod";
export const WorkspaceSchema = z.object({
  workspace_id: z.string(),
  name: z.string(),
  website: z.string().nullable(),
  logo_url: z.string().nullable(),
});
export type SettingsOrganization = z.infer<typeof WorkspaceSchema>;
