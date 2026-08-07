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

export const ProjectThreadSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
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

export const GenerationStepSchema = z.object({
  id: z.string().min(1),
  label: z.string().min(1),
  logoPath: z.string().startsWith("/"),
  note: z.string().min(1),
  progress: z.number().min(0).max(100),
});

export const ProjectPreviewTimelineSchema = z.object({
  agentRunningMs: z.number().int().positive(),
  conversationToQuestionnaireMs: z.number().int().positive(),
  generationMilestones: z.array(z.object({
    delayMs: z.number().int().positive(),
    progress: z.number().min(0).max(100),
  })).min(1),
  generationStartProgress: z.number().min(0).max(100),
});

const ReasoningTagSchema = z.object({
  label: z.string().min(1),
  logoPath: z.string().startsWith("/").optional(),
});

export const ProjectReasoningTraceSchema = z.object({
  profile: z.object({
    caption: z.string().min(1),
    detail: z.string().min(1),
    imageAlt: z.string().min(1),
    imagePath: z.string().startsWith("/"),
    label: z.string().min(1),
  }),
  recentSearch: z.object({
    label: z.string().min(1),
    tags: z.array(ReasoningTagSchema).min(1),
  }),
  targetSearch: z.object({
    label: z.string().min(1),
    tags: z.array(ReasoningTagSchema).min(1),
  }),
  title: z.string().min(1),
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

export const ProjectWorkspaceSchema = z.object({
  artifacts: z.array(ProjectArtifactSchema),
  contextEntities: z.array(ProjectEntitySchema),
  defaultModelId: z.string().min(1),
  conversationActivity: z.object({
    sources: z.array(z.object({
      href: z.string().url(),
      id: z.string().min(1),
      label: z.string().min(1),
      logoPath: z.string().startsWith("/").optional(),
    })).min(1),
    tools: z.array(z.object({
      id: z.string().min(1),
      input: z.record(z.string(), z.unknown()).optional(),
      output: z.string().min(1).optional(),
      title: z.string().min(1),
    })).min(2),
  }),
  conversationCopy: z.object({
    agentRunningLabel: z.string().min(1),
    assistantName: z.string().min(1),
    beforeQuestionnaire: z.array(z.string().min(1)).min(1),
    buildingAccepted: z.string().min(1),
    buildingLabel: z.string().min(1),
    initialReasoning: z.string().min(1),
    planCardLabel: z.string().min(1),
    planCreated: z.string().min(1),
    planStarting: z.string().min(1),
    questionnaireCardLabel: z.string().min(1),
    reasoningLabel: z.string().min(1),
  }),
  generationCopy: z.object({
    completeCreditsLabel: z.string().min(1),
    completeLabel: z.string().min(1),
    completeTimingLabel: z.string().min(1),
    progressCreditsLabel: z.string().min(1),
    progressLabel: z.string().min(1),
  }),
  generationSteps: z.array(GenerationStepSchema).min(1),
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
  previewTimeline: ProjectPreviewTimelineSchema,
  questionnaire: ProjectQuestionnaireSchema,
  reasoningTrace: ProjectReasoningTraceSchema,
  threads: z.array(ProjectThreadSchema).min(1),
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

const ProjectToolStateSchema = z.enum([
  "approval-requested",
  "approval-responded",
  "input-available",
  "input-streaming",
  "output-available",
  "output-denied",
  "output-error",
]);

export const ProjectMessagePartSchema = z.discriminatedUnion("type", [
  z.object({
    id: z.string().min(1),
    text: z.string().min(1),
    type: z.literal("text"),
  }),
  z.object({
    detail: z.string().min(1).optional(),
    id: z.string().min(1),
    label: z.string().min(1),
    showTrace: z.boolean().default(false),
    streaming: z.boolean().default(false),
    type: z.literal("reasoning"),
  }),
  z.object({
    action: z.enum(["questionnaire", "plan"]),
    icon: z.enum(["clipboard-list", "list"]),
    id: z.string().min(1),
    label: z.string().min(1),
    type: z.literal("action"),
  }),
  z.object({
    id: z.string().min(1),
    input: z.record(z.string(), z.unknown()).optional(),
    output: z.string().min(1).optional(),
    state: ProjectToolStateSchema,
    title: z.string().min(1),
    type: z.literal("tool"),
  }),
  z.object({
    id: z.string().min(1),
    type: z.literal("plan"),
  }),
  z.object({
    complete: z.boolean(),
    id: z.string().min(1),
    progress: z.number().min(0).max(100),
    type: z.literal("task"),
  }),
  z.object({
    id: z.string().min(1),
    type: z.literal("sources"),
  }),
]);

export const ProjectMessageSchema = z.object({
  authorLabel: z.string().min(1).optional(),
  id: z.string().min(1),
  parts: z.array(ProjectMessagePartSchema).min(1),
  role: z.enum(["assistant", "user"]),
});

export type ProjectEntity = z.infer<typeof ProjectEntitySchema>;
export type ProjectModelOption = z.infer<typeof ProjectModelOptionSchema>;
export type ProjectThread = z.infer<typeof ProjectThreadSchema>;
export type ProjectWebsiteContent = z.infer<typeof ProjectWebsiteContentSchema>;
export type ProjectTableContent = z.infer<typeof ProjectTableContentSchema>;
export type ProjectArtifact = z.infer<typeof ProjectArtifactSchema>;
export type GenerationStep = z.infer<typeof GenerationStepSchema>;
export type ProjectPreviewTimeline = z.infer<typeof ProjectPreviewTimelineSchema>;
export type ProjectReasoningTrace = z.infer<typeof ProjectReasoningTraceSchema>;
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
export type ProjectMessagePart = z.infer<typeof ProjectMessagePartSchema>;
export type ProjectMessage = z.infer<typeof ProjectMessageSchema>;
