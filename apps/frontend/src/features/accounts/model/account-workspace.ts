import { z } from "zod";

export const WorkspaceInsightSchema = z
  .object({
    id: z.string().min(1),
    source: z.enum(["link", "linkedin", "x"]),
    title: z.string().min(1),
    sourceLabel: z.string().min(1),
    url: z.string().url(),
    summary: z.string().min(1),
  })
  .superRefine((insight, context) => {
    if (insight.sourceLabel !== insight.url) {
      context.addIssue({
        code: "custom",
        path: ["sourceLabel"],
        message: "sourceLabel must exactly equal url",
      });
    }
  });

export const AccountArtifactSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  type: z.enum(["presentation", "document", "web"]),
  thumbnailPath: z.string().startsWith("/"),
  lastEditedLabel: z.string().min(1),
});

export const WorkspaceActivitySchema = z.object({
  id: z.string().min(1),
  kind: z.enum(["contacts", "summary", "created"]),
  text: z.string().min(1),
  timeLabel: z.string().min(1),
});

export const AccountWorkspaceSchema = z.object({
  accountId: z.string().min(1),
  insights: z.array(WorkspaceInsightSchema),
  artifacts: z.array(AccountArtifactSchema),
  activity: z.array(WorkspaceActivitySchema),
});

export const AccountWorkspaceResponseSchema = z.object({
  data: AccountWorkspaceSchema,
});

export type AccountArtifact = z.infer<typeof AccountArtifactSchema>;
export type AccountWorkspace = z.infer<typeof AccountWorkspaceSchema>;
export type WorkspaceInsight = z.infer<typeof WorkspaceInsightSchema>;
