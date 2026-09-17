import { z } from "zod";
import { AccountActivitySchema } from "./account-detail";
import {
  HttpUrlSchema,
  ResearchDisplayBlockSchema,
  ResearchEvidenceSchema,
} from "./research-display";

export const WorkspaceInsightSchema = z.object({
  id: z.string().min(1),
  source: z.enum(["link", "linkedin", "x"]),
  title: z.string().min(1),
  sourceLabel: z.string().min(1),
  url: HttpUrlSchema,
  summary: z.string().min(1),
});

export const AccountArtifactSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  type: z.enum(["presentation", "document", "web", "ad", "email"]),
  accountId: z.string().min(1).optional(),
  projectName: z.string().min(1).optional(),
  updatedAt: z.string().datetime().optional(),
  thumbnailPath: z.string().startsWith("/"),
  lastEditedLabel: z.string().min(1),
});

export const WorkspaceActivitySchema = AccountActivitySchema;

export const AccountWorkspaceSchema = z.object({
  accountId: z.string().min(1),
  insights: z.array(WorkspaceInsightSchema),
  insightSummary: z.array(z.string().min(1)).default([]),
  researchEvidence: z.array(ResearchEvidenceSchema).default([]),
  insightsDisplay: ResearchDisplayBlockSchema.optional(),
  artifacts: z.array(AccountArtifactSchema),
  activity: z.array(WorkspaceActivitySchema),
});

export const AccountWorkspaceResponseSchema = z.object({
  data: AccountWorkspaceSchema,
});

export type AccountArtifact = z.infer<typeof AccountArtifactSchema>;
export type AccountWorkspace = z.infer<typeof AccountWorkspaceSchema>;
export type WorkspaceInsight = z.infer<typeof WorkspaceInsightSchema>;
