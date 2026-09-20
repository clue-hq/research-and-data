import { z } from "zod";

export const ProjectRenameResponseSchema = z.object({
  data: z.object({ id: z.string().min(1), title: z.string().min(1).max(200) }),
}).transform(({ data }) => data);

export type RenamedProject = z.infer<typeof ProjectRenameResponseSchema>;

export const ProjectEntityTypeSchema = z.enum([
  "account",
  "contact",
  "project_document",
  "design_document",
]);
export const ProjectEntityCategorySchema = z.enum([
  "accounts",
  "files",
  "microsites",
]);
export const ProjectEntityIconSchema = z.enum(["file-text", "image", "web"]);

/**
 * The two shapes an entity image may take: a rooted path the BFF serves (the platform's own
 * logo route, a local asset) or Brandfetch's embed-only Logo API URL, which the accounts screens
 * already hand the browser directly. Anything else is no image, never a placeholder path.
 */
const BRANDFETCH_LOGO_ORIGIN = "https://cdn.brandfetch.io/";

export function isComposerEntityImagePath(value: string): boolean {
  return value.startsWith("/") || value.startsWith(BRANDFETCH_LOGO_ORIGIN);
}

export function composerEntityImagePath(
  value: string | null | undefined,
): string | undefined {
  return value && isComposerEntityImagePath(value) ? value : undefined;
}

export const ProjectEntitySchema = z.object({
  // A contact's account, so the picker can nest it under that account's row.
  accountId: z.string().min(1).optional(),
  accountName: z.string().optional(),
  // Absent means the legacy account/contact catalog served by the backend.
  category: ProjectEntityCategorySchema.optional(),
  icon: ProjectEntityIconSchema.optional(),
  id: z.string().min(1),
  imagePath: z.string().refine(isComposerEntityImagePath).optional(),
  label: z.string().min(1),
  secondaryLabel: z.string().min(1),
  type: ProjectEntityTypeSchema,
  version: z.number().int().positive().nullable().optional(),
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

// Gallery facet vocabulary (W0.5): adopted verbatim from the chat-shell
// branch's model so the lifted gallery module consumes the same shapes its
// filter/sort/group functions were written against. All artifact-level gallery
// fields are optional — existing parsers and fixtures are unaffected.
export const GalleryCollateralTypeSchema = z.enum([
  "account-list",
  "microsite",
  "direct-mail",
  "linkedin-ad",
  "meta-ad",
  "report",
  "presentation",
]);

export const GallerySizeCategorySchema = z.enum([
  "responsive",
  "landscape",
  "square",
  "portrait",
]);

export const ProjectArtifactSizeSchema = z.object({
  category: GallerySizeCategorySchema,
  height: z.number().int().positive(),
  label: z.string().min(1),
  width: z.number().int().positive(),
});

export const ProjectArtifactSchema = z.object({
  accountId: z.string().min(1).optional(),
  // A platform path or Brandfetch's Logo API URL — the same rule the composer's
  // entity images follow (`isComposerEntityImagePath`).
  accountLogoPath: z.string().refine(isComposerEntityImagePath).optional(),
  accountName: z.string().min(1).optional(),
  canvasPagePaths: z.array(z.string().startsWith("/")).optional(),
  collateralType: GalleryCollateralTypeSchema.optional(),
  createdAt: z.string().datetime().optional(),
  // The design document behind a design artifact, and its current version — what a
  // composer tag of this artifact sends. Absent on table/presentation cards.
  documentId: z.string().min(1).optional(),
  editedLabel: z.string().min(1),
  id: z.string().min(1),
  // Design artifacts now carry a versioned BFF thumbnail URL, so this is
  // populated on the common path. It stays optional because other artifact
  // sources still omit it, and because a thumbnail that is missing or fails to
  // load falls back to the empty preview frame (ratified ruling 2). Absent
  // means absent — consumers render without artwork rather than substituting
  // placeholder imagery.
  imagePath: z.string().startsWith("/").optional(),
  lastViewedAt: z.string().datetime().optional(),
  originRunId: z.string().min(1).optional(),
  originThreadId: z.string().min(1),
  size: ProjectArtifactSizeSchema.optional(),
  title: z.string().min(1),
  tableContent: ProjectTableContentSchema.optional(),
  type: z.enum(["table", "website", "canvas", "presentation"]),
  updatedAt: z.string().datetime().optional(),
  version: z.number().int().positive().optional(),
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
    uploadId: z.string().min(1).max(200),
  }).strict()).default([]),
  brandId: z.string().min(1).max(200),
  contextRefs: z.array(z.object({
    objectId: z.string().min(1).max(200),
    objectType: ProjectEntityTypeSchema,
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
      version: z.number().int().positive().nullable().default(null),
      // A contact's account: the id the picker nests it under, the name search shows.
      account_id: z.string().min(1).nullable().default(null),
      account_name: z.string().min(1).nullable().default(null),
    })),
    agent_profiles: z.array(z.object({
      id: z.string().min(1),
      label: z.string().min(1),
      short_label: z.string().min(1),
      description: z.string().min(1),
      model_id: z.string().min(1),
    })),
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
      ...(entity.account_id ? { accountId: entity.account_id } : {}),
      ...(entity.account_name ? { accountName: entity.account_name } : {}),
      id: entity.object_id,
      imagePath: composerEntityImagePath(entity.image_url),
      label: entity.label,
      secondaryLabel: entity.secondary_label,
      type: entity.object_type,
      version: entity.version,
    })),
    models: data.agent_profiles.map((profile) => ({
      description: profile.description,
      id: profile.id,
      label: profile.label,
      shortLabel: profile.short_label,
    })),
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
      // Born untitled; the conversation namer titles it after the first completed turn.
      title: z.string().min(1).nullable(),
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
    description: z.string().default(""),
    brand_id: z.string().min(1),
    product_id: z.string().min(1).nullable(),
    status: z.enum(["draft", "active", "paused", "archived"]),
    pinned: z.boolean().default(false),
    created_at: z.string().min(1),
    updated_at: z.string().min(1).nullable().optional(),
    archived_at: z.string().min(1).nullable().optional(),
    context_entities: ProjectHomeWireSchema.shape.data.shape.context_entities,
    agent_profiles: ProjectHomeWireSchema.shape.data.shape.agent_profiles,
    default_agent_profile_id: z.string().min(1).nullable(),
    composer_capabilities: z.object({
      context_refs: z.boolean(),
      attachments: z.boolean(),
      agent_profile_selection: z.boolean(),
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
  archivedAt: z.string().min(1).nullable().optional(),
  artifacts: z.tuple([]),
  brandId: z.string().min(1),
  composerCapabilities: ProjectComposerCapabilitiesSchema,
  createdAt: z.string().min(1),
  defaultAgentProfileId: z.string().min(1).nullable(),
  description: z.string().default(""),
  entities: z.array(ProjectEntitySchema),
  id: z.string().min(1),
  models: z.array(ProjectModelOptionSchema),
  pinned: z.boolean().default(false),
  productId: z.string().min(1).nullable(),
  status: z.enum(["draft", "active", "paused", "archived"]),
  title: z.string().min(1),
  updatedAt: z.string().min(1).nullable().optional(),
}).strict();

export const ProjectWorkspaceResponseSchema = ProjectWorkspaceWireSchema.transform(
  ({ data }) =>
    ProjectWorkspaceSchema.parse({
      archivedAt: data.archived_at ?? null,
      artifacts: [],
      brandId: data.brand_id,
      composerCapabilities: {
        attachments: data.composer_capabilities.attachments,
        contextRefs: data.composer_capabilities.context_refs,
        agentProfileSelection:
          data.composer_capabilities.agent_profile_selection,
      },
      createdAt: data.created_at,
      defaultAgentProfileId: data.default_agent_profile_id,
      description: data.description,
      entities: data.context_entities.map((entity) => ({
        id: entity.object_id,
        ...(entity.account_id ? { accountId: entity.account_id } : {}),
        ...(entity.account_name ? { accountName: entity.account_name } : {}),
        imagePath: composerEntityImagePath(entity.image_url),
        label: entity.label,
        secondaryLabel: entity.secondary_label,
        type: entity.object_type,
        version: entity.version,
      })),
      id: data.id,
      models: data.agent_profiles.map((profile) => ({
        description: profile.description,
        id: profile.id,
        label: profile.label,
        shortLabel: profile.short_label,
      })),
      pinned: data.pinned,
      productId: data.product_id,
      status: data.status,
      title: data.title,
      updatedAt: data.updated_at ?? null,
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
export type GalleryCollateralType = z.infer<typeof GalleryCollateralTypeSchema>;
export type GallerySizeCategory = z.infer<typeof GallerySizeCategorySchema>;
export type ProjectArtifactSize = z.infer<typeof ProjectArtifactSizeSchema>;
export type ProjectQuestionnaire = z.infer<typeof ProjectQuestionnaireSchema>;
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
