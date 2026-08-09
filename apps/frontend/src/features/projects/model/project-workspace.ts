import { z } from "zod";

export const ProjectEntitySchema = z.object({
  accountName: z.string().optional(),
  id: z.string().min(1),
  imagePath: z.string().startsWith("/"),
  label: z.string().min(1),
  secondaryLabel: z.string().min(1),
  type: z.enum(["account", "contact"]),
});

export const ProjectModelOptionSchema = z.object({
  description: z.string().min(1),
  id: z.string().min(1),
  label: z.string().min(1),
  shortLabel: z.string().min(1),
});

export const ProjectWebsiteContentSchema = z.object({
  badge: z.string().min(1),
  brandAlt: z.string().min(1),
  brandLogoPath: z.string().startsWith("/"),
  ctaLabel: z.string().min(1),
  headline: z.string().min(1),
  heroAlt: z.string().min(1),
  heroImagePath: z.string().startsWith("/"),
  navItems: z.array(z.string().min(1)).min(1),
  subheading: z.string().min(1),
});

export const ProjectTableContentSchema = z.object({
  actionLabel: z.string().min(1),
  columns: z.array(z.string().min(1)).length(4),
  rows: z.array(z.object({
    company: z.string().min(1),
    contact: z.string().min(1),
    logoPath: z.string().startsWith("/"),
    status: z.string().min(1),
    tier: z.string().min(1),
  })).min(1),
  title: z.string().min(1),
});

export const ProjectArtifactSchema = z.object({
  accountLogoPath: z.string().startsWith("/").optional(),
  canvasPagePaths: z.array(z.string().startsWith("/")).optional(),
  editedLabel: z.string().min(1),
  id: z.string().min(1),
  imagePath: z.string().startsWith("/"),
  originRunId: z.string().min(1),
  originThreadId: z.string().min(1),
  title: z.string().min(1),
  tableContent: ProjectTableContentSchema.optional(),
  type: z.enum(["table", "website", "canvas", "presentation"]),
  viewerTitle: z.string().min(1).optional(),
  websiteContent: ProjectWebsiteContentSchema.optional(),
});

export const ProjectQuestionChoiceSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
});

export const ProjectQuestionGroupSchema = z.object({
  defaultChoiceId: z.string().min(1),
  hint: z.string().min(1),
  options: z.array(ProjectQuestionChoiceSchema).min(1),
  question: z.string().min(1),
});

export const ProjectQuestionnaireSchema = z.object({
  primaryAction: ProjectQuestionGroupSchema,
  secondaryAction: ProjectQuestionGroupSchema,
  targetAccounts: z.object({
    defaultValue: z.string().min(1),
    hint: z.string().min(1),
    question: z.string().min(1),
  }),
  theme: ProjectQuestionGroupSchema,
  title: z.string().min(1),
});

export const ProjectHomeSchema = z.object({
  entities: z.array(ProjectEntitySchema),
  models: z.array(ProjectModelOptionSchema).min(1),
  suggestions: z.array(z.string().min(1)).length(3),
  suggestedProjectId: z.string().min(1),
  suggestedThreadId: z.string().min(1),
});

/**
 * The project shell: the artifact-side surfaces and the composer's catalogs.
 *
 * The conversation left this schema in slice D5. Threads, messages, parts, the
 * six-value phase transcript, the `previewTimeline` timer blob a real backend
 * would have had to ship, the `reasoningTrace` and `conversationCopy` display
 * strings, and the `conversationActivity` tool/source records the frontend used
 * to manufacture cards from are all gone: the transcript is durable turns and
 * streamed parts now, under `model/chat-*.ts`.
 */
export const ProjectWorkspaceSchema = z.object({
  artifacts: z.array(ProjectArtifactSchema),
  contextEntities: z.array(ProjectEntitySchema),
  defaultModelId: z.string().min(1),
  id: z.string().min(1),
  models: z.array(ProjectModelOptionSchema).min(1),
  plan: z.object({
    audience: z.string().min(1),
    sections: z.array(z.object({
      lines: z.array(z.string().min(1)).min(1),
      title: z.string().min(1),
    })).min(1),
    title: z.string().min(1),
  }),
  prompt: z.string().min(1),
  questionnaire: ProjectQuestionnaireSchema,
  title: z.string().min(1),
});

export const ProjectPhaseSchema = z.enum([
  "conversation",
  "questionnaire",
  "agent-running",
  "planning",
  "generating",
  "complete",
]);

export const ArtifactSurfaceSchema = z.enum(["gallery", "artifact"]);
export const GalleryLayoutSchema = z.enum(["grid", "list"]);
export const ArtifactFilterSchema = z.enum([
  "all",
  "table",
  "website",
  "canvas",
  "presentation",
]);
export const ArtifactSortSchema = z.enum(["last-viewed", "name"]);
export const PreviewDeviceSchema = z.enum(["desktop", "tablet", "mobile"]);
export const InspectorSelectionSchema = z.enum([
  "canvas",
  "text",
  "image",
  "button",
]);

export type ProjectEntity = z.infer<typeof ProjectEntitySchema>;
export type ProjectModelOption = z.infer<typeof ProjectModelOptionSchema>;
export type ProjectWebsiteContent = z.infer<typeof ProjectWebsiteContentSchema>;
export type ProjectTableContent = z.infer<typeof ProjectTableContentSchema>;
export type ProjectArtifact = z.infer<typeof ProjectArtifactSchema>;
export type ProjectQuestionnaire = z.infer<typeof ProjectQuestionnaireSchema>;
export type ProjectQuestionGroup = z.infer<typeof ProjectQuestionGroupSchema>;
export type ProjectHome = z.infer<typeof ProjectHomeSchema>;
export type ProjectWorkspace = z.infer<typeof ProjectWorkspaceSchema>;
export type ProjectPhase = z.infer<typeof ProjectPhaseSchema>;
export type ArtifactSurface = z.infer<typeof ArtifactSurfaceSchema>;
export type GalleryLayout = z.infer<typeof GalleryLayoutSchema>;
export type ArtifactFilter = z.infer<typeof ArtifactFilterSchema>;
export type ArtifactSort = z.infer<typeof ArtifactSortSchema>;
export type PreviewDevice = z.infer<typeof PreviewDeviceSchema>;
export type InspectorSelection = z.infer<typeof InspectorSelectionSchema>;
