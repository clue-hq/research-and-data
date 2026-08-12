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

export const AccountWorkspaceSchema = z.object({
  accountId: z.string().min(1),
  insights: z.array(WorkspaceInsightSchema),
});

export const AccountWorkspaceResponseSchema = z.object({
  data: AccountWorkspaceSchema,
});

export type AccountWorkspace = z.infer<typeof AccountWorkspaceSchema>;
export type WorkspaceInsight = z.infer<typeof WorkspaceInsightSchema>;
