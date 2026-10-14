import { z } from "zod";
import { ProductNoticeSchema, type ProductNotice } from "../model/product-notice";

const PREFIX = "/api/clue/frontend/v1/projects";

/** The project's undismissed product notices; any failure reads as none, never as an error. */
export async function readProductNotices(projectId: string, clueFetch: typeof fetch = fetch): Promise<ProductNotice[]> {
  try {
    const response = await clueFetch(`${PREFIX}/${encodeURIComponent(projectId)}/product-notices`, {
      cache: "no-store", headers: { Accept: "application/json" },
    });
    if (!response.ok) return [];
    return z.object({ notices: z.array(ProductNoticeSchema) }).parse(await response.json()).notices;
  } catch {
    return [];
  }
}

/** Hide a notice for this person; `false` when the platform did not record it. */
export async function dismissProductNotice(
  projectId: string, changeId: string, clueFetch: typeof fetch = fetch,
): Promise<boolean> {
  try {
    const response = await clueFetch(
      `${PREFIX}/${encodeURIComponent(projectId)}/product-notices/${encodeURIComponent(changeId)}/dismiss`,
      { method: "POST", cache: "no-store" },
    );
    return response.ok;
  } catch {
    return false;
  }
}
