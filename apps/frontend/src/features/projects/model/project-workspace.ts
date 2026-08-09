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

export const ProjectBrandSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
});

export const ProjectComposerCapabilitiesSchema = z.object({
  attachments: z.boolean(),
  contextRefs: z.boolean(),
  agentProfileSelection: z.boolean(),
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

export const ProjectPlanSchema = z.object({
  audience: z.string().min(1),
  sections: z.array(z.object({
    lines: z.array(z.string().min(1)).min(1),
    title: z.string().min(1),
  })).min(1),
  title: z.string().min(1),
});

export const ProjectHomeSchema = z.object({
  brands: z.array(ProjectBrandSchema),
  composerCapabilities: ProjectComposerCapabilitiesSchema,
  defaultAgentProfileId: z.string().min(1).nullable(),
  defaultBrandId: z.string().min(1).nullable(),
  entities: z.array(ProjectEntitySchema),
  models: z.array(ProjectModelOptionSchema),
  suggestions: z.array(z.string().min(1)).max(3),
});

const ProjectBootstrapMessageSchema = z
  .string()
  .min(1)
  .max(32_000)
  .refine((message) => message.trim().length > 0, {
    message: "message must contain something other than whitespace",
  });

/** The complete browser-owned portion of one atomic Home bootstrap act. */
export const ProjectBootstrapRequestSchema = z.object({
  agentProfileId: z.string().min(1).max(200).nullable().default(null),
  attachmentRefs: z.array(z.object({
    artifactKey: z.string().min(1).max(1_000),
    byteCount: z.number().int().nonnegative(),
    filename: z.string().min(1).max(255),
    mediaType: z.string().min(1).max(255),
    sha256: z.string().regex(/^[0-9a-f]{64}$/),
  }).strict()).default([]),
  brandId: z.string().min(1).max(200),
  contextRefs: z.array(z.object({
    objectId: z.string().min(1).max(200),
    objectType: z.enum(["account", "contact"]),
    version: z.number().int().positive().nullable().default(null),
  }).strict()).default([]),
  message: ProjectBootstrapMessageSchema,
}).strict();

const ProjectHomeWireSchema = z.object({
  data: z.object({
    brands: z.array(z.object({
      id: z.string().min(1),
      name: z.string().min(1),
    })),
    default_brand_id: z.string().min(1).nullable(),
    context_entities: z.array(z.object({
      object_type: z.enum(["account", "contact"]),
      object_id: z.string().min(1),
      label: z.string().min(1),
      secondary_label: z.string().min(1),
      image_url: z.string().nullable(),
    })),
    agent_profiles: z.array(z.unknown()),
    default_agent_profile_id: z.string().min(1).nullable(),
    composer_capabilities: z.object({
      context_refs: z.boolean(),
      attachments: z.boolean(),
      agent_profile_selection: z.boolean(),
    }),
    suggestions: z.array(z.string().min(1)).max(3),
  }),
});

export const ProjectHomeResponseSchema = ProjectHomeWireSchema.transform(({ data }) =>
  ProjectHomeSchema.parse({
    brands: data.brands,
    composerCapabilities: {
      attachments: data.composer_capabilities.attachments,
      contextRefs: data.composer_capabilities.context_refs,
      agentProfileSelection:
        data.composer_capabilities.agent_profile_selection,
    },
    defaultAgentProfileId: data.default_agent_profile_id,
    defaultBrandId: data.default_brand_id,
    entities: data.context_entities.map((entity) => ({
      id: entity.object_id,
      imagePath: entity.image_url?.startsWith("/")
        ? entity.image_url
        : "/logos/clue.svg",
      label: entity.label,
      secondaryLabel: entity.secondary_label,
      type: entity.object_type,
    })),
    // R2 advertises profile selection as unavailable. A future profile slice
    // will add the governed profile -> picker mapping rather than treating a
    // model id as a profile id.
    models: [],
    suggestions: data.suggestions,
  }),
);

const ProjectBootstrapWireSchema = z.object({
  data: z.object({
    project: z.object({
      id: z.string().min(1),
      title: z.literal("Untitled project"),
      brand_id: z.string().min(1),
      href: z.string().startsWith("/projects/"),
      created_at: z.string().min(1),
    }),
    thread: z.object({
      id: z.string().min(1),
      title: z.string().min(1),
      href: z.string().startsWith("/projects/"),
      status: z.literal("running"),
      pinned: z.boolean(),
      project_id: z.string().min(1),
      created_at: z.string().min(1),
      updated_at: z.string().min(1),
    }),
    turn: z.object({
      turn_id: z.string().min(1),
      thread_id: z.string().min(1),
      requested_at: z.string().min(1),
      replayed: z.boolean(),
    }),
    href: z.string().startsWith("/projects/"),
  }),
});

export const ProjectBootstrapResponseSchema = ProjectBootstrapWireSchema.transform(
  ({ data }) => ({
    href: data.href,
    project: {
      id: data.project.id,
      title: data.project.title,
      brandId: data.project.brand_id,
      href: data.project.href,
      createdAt: data.project.created_at,
    },
    thread: {
      id: data.thread.id,
      title: data.thread.title,
      href: data.thread.href,
      status: data.thread.status,
      pinned: data.thread.pinned,
      projectId: data.thread.project_id,
      createdAt: data.thread.created_at,
      updatedAt: data.thread.updated_at,
    },
    turn: {
      turnId: data.turn.turn_id,
      threadId: data.turn.thread_id,
      requestedAt: data.turn.requested_at,
      replayed: data.turn.replayed,
    },
  }),
);

const ProjectWorkspaceWireSchema = z.object({
  data: z.object({
    id: z.string().min(1),
    title: z.string().min(1),
    brand_id: z.string().min(1),
    product_id: z.string().min(1).nullable(),
    status: z.enum(["draft", "active", "paused", "archived"]),
    created_at: z.string().min(1),
    context_entities: z.array(z.never()),
    agent_profiles: z.array(z.never()),
    default_agent_profile_id: z.null(),
    composer_capabilities: z.object({
      context_refs: z.literal(false),
      attachments: z.literal(false),
      agent_profile_selection: z.literal(false),
    }),
    artifacts: z.array(z.never()),
  }),
});

/**
 * The real project shell served before artifact integration exists.
 *
 * It deliberately excludes the prototype's plan, questionnaire, model list,
 * prompt, phase, and context catalog. Those values are not backend project
 * state. `artifacts` is an exact empty tuple until a separately contracted
 * artifact read surface can supply real records.
 */
export const ProjectWorkspaceSchema = z.object({
  artifacts: z.tuple([]),
  brandId: z.string().min(1),
  composerCapabilities: ProjectComposerCapabilitiesSchema,
  createdAt: z.string().min(1),
  id: z.string().min(1),
  productId: z.string().min(1).nullable(),
  status: z.enum(["draft", "active", "paused", "archived"]),
  title: z.string().min(1),
}).strict();

export const ProjectWorkspaceResponseSchema = ProjectWorkspaceWireSchema.transform(
  ({ data }) =>
    ProjectWorkspaceSchema.parse({
      artifacts: [],
      brandId: data.brand_id,
      composerCapabilities: {
        attachments: data.composer_capabilities.attachments,
        contextRefs: data.composer_capabilities.context_refs,
        agentProfileSelection:
          data.composer_capabilities.agent_profile_selection,
      },
      createdAt: data.created_at,
      id: data.id,
      productId: data.product_id,
      status: data.status,
      title: data.title,
    }),
);
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
export type ProjectBrand = z.infer<typeof ProjectBrandSchema>;
export type ProjectComposerCapabilities = z.infer<
  typeof ProjectComposerCapabilitiesSchema
>;
export type ProjectModelOption = z.infer<typeof ProjectModelOptionSchema>;
export type ProjectWebsiteContent = z.infer<typeof ProjectWebsiteContentSchema>;
export type ProjectTableContent = z.infer<typeof ProjectTableContentSchema>;
export type ProjectArtifact = z.infer<typeof ProjectArtifactSchema>;
export type ProjectQuestionnaire = z.infer<typeof ProjectQuestionnaireSchema>;
export type ProjectPlan = z.infer<typeof ProjectPlanSchema>;
export type ProjectQuestionGroup = z.infer<typeof ProjectQuestionGroupSchema>;
export type ProjectHome = z.infer<typeof ProjectHomeSchema>;
export type ProjectBootstrapRequest = z.infer<
  typeof ProjectBootstrapRequestSchema
>;
export type ProjectBootstrapRequestInput = z.input<
  typeof ProjectBootstrapRequestSchema
>;
export type ProjectBootstrap = z.infer<typeof ProjectBootstrapResponseSchema>;
export type ProjectWorkspace = z.infer<typeof ProjectWorkspaceSchema>;
export type GalleryLayout = z.infer<typeof GalleryLayoutSchema>;
export type ArtifactFilter = z.infer<typeof ArtifactFilterSchema>;
export type ArtifactSort = z.infer<typeof ArtifactSortSchema>;
export type PreviewDevice = z.infer<typeof PreviewDeviceSchema>;
export type InspectorSelection = z.infer<typeof InspectorSelectionSchema>;
