import { z } from "zod";

/** A product change that moved this project's products (spec 2026-10-15 product management §7). */
export const ProductNoticeSchema = z.object({
  changeId: z.string(),
  createdAt: z.string(),
  outcome: z.string(),
  text: z.string(),
});

export type ProductNotice = z.infer<typeof ProductNoticeSchema>;
