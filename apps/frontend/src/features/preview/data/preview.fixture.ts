import { ProfileSchema } from "@/features/settings/model/profile";
import { WorkspaceSchema } from "@/features/settings/model/workspace";
import { MembersSchema } from "@/features/settings/model/members";
import { PagesSettingsReadSchema } from "@/features/settings/model/pages";
import { ResearchFieldsSchema } from "@/features/settings/model/research-fields";
import { ProjectDocumentDetailSchema } from "@/features/projects/model/project-documents";
import { workspaceProfileFixture } from "@/features/accounts/data/workspace-profile.fixture";

export const previewProfile = ProfileSchema.parse({
  user_id: "usr_demo", first_name: "Aakash", last_name: "Shrivastava",
  full_name: workspaceProfileFixture.fullName, display_name: workspaceProfileFixture.displayName,
  email: "reviewer@example.test",
});
export const previewWorkspace = WorkspaceSchema.parse({
  workspace_id: "ws-demo", name: "Clue Demo", website: "https://example.test", logo_url: null,
});
export const previewMembers = MembersSchema.parse({
  invitations_configured: false,
  rows: [{ kind: "member", id: "usr_demo", name: previewProfile.full_name,
    email: previewProfile.email, role_key: "owner", state: "active", joined_on: "2026-10-01", is_self: true }],
});
export const previewPages = PagesSettingsReadSchema.parse({
  settings: { fallbackUrl: null, pageTitle: "Demo campaign", pageDescription: "Local frontend preview",
    faviconUrl: null, socialPreviewUrl: null },
  systemHostname: { hostname: "preview.example.test", label: "preview", url: "https://preview.example.test" },
  customHostname: null,
});

export function previewResearchFields(entity: "accounts" | "contacts") {
  return ResearchFieldsSchema.parse({ entity, rows: [
    { key: `${entity}.preview.context`, label: entity === "accounts" ? "Business priorities" : "Professional context",
      description: "Example field for reviewing the interface. No live research is performed.",
      origin: "platform", created_by: null, created_at: null },
  ] });
}

/** Synthetic copy only. No pilot/customer data and no claim that an agent generated these. */
export function previewDocuments(projectId: string) {
  return [
    { key: "plan", path: "project/plan.md", kind: "project-plan", title: "Campaign plan",
      markdown: "# Campaign plan\n\n> Demo document for the local frontend preview.\n\n## Objective\n\nReview the customer journey for an account-focused campaign.\n\n## Audience\n\nUse the sample accounts and contacts in this workspace to explore navigation and context selection.\n\n## Review checklist\n\n- Review account context\n- Prepare personalized campaign content\n- Review assets in Gallery\n- Approve the final customer experience\n\n## Next step\n\nDefine the Direct Mail experience before implementing its screens. No research, orders or messages are sent from this preview." },
    { key: "personas", path: "project/personas.md", kind: "audience-persona", title: "Audience personas",
      markdown: "# Audience personas\n\n> Synthetic sample content.\n\n## Campaign owner\n\nA marketing lead planning an account-focused campaign. They need to connect an account insight to a clear campaign decision.\n\n## Reviewer\n\nA teammate who compares options, edits the message and approves the next step.\n\n## Handoff\n\nThis document exercises the same Gallery and document editor used by the connected application. Preview changes reset when the development server restarts." },
  ].map(({ key, ...document }) => ProjectDocumentDetailSchema.parse({
    ...document, id: `preview-${projectId}-${key}`, version: 1, status: "draft",
    updated_at: "2026-10-25T00:00:00Z", icp_key: null, front_matter: { title: document.title, kind: document.kind },
  }));
}
