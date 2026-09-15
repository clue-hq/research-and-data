import { z } from "zod";

/**
 * A document's kind is the word its own front matter says (founder ruling 2026-09-14: the agent
 * writes any document under `project/` and names it; the backend serves that word as is). An open
 * string, never a closed list — an enum here hid every document in the Gallery the first time the
 * agent wrote a `campaign-plan`.
 */
export const ProjectDocumentKindSchema = z.string().min(1);

const KNOWN_KIND_LABELS: Readonly<Record<string, string>> = {
  "project-plan": "Plan",
  "icp-definition": "Ideal customer profile",
  "audience-persona": "Personas",
};

/** The card's small label: the platform's wording for the kinds it knows, else the kind's own words. */
export function documentKindLabel(kind: string): string {
  const known = KNOWN_KIND_LABELS[kind];
  if (known) return known;
  const words = kind.replace(/[-_]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const ProjectDocumentSummarySchema = z.object({
  id: z.string().min(1),
  path: z.string().min(1),
  kind: ProjectDocumentKindSchema,
  title: z.string().min(1),
  version: z.number().int().positive(),
  status: z.string().min(1),
  updated_at: z.iso.datetime({ offset: true }),
  icp_key: z.string().nullable(),
});

export const ProjectDocumentDetailSchema = ProjectDocumentSummarySchema.extend({
  markdown: z.string(),
  front_matter: z.record(z.string(), z.unknown()),
});

export const ProjectDocumentsResponseSchema = z.object({
  data: z.object({ documents: z.array(ProjectDocumentSummarySchema) }),
});
export const ProjectDocumentDetailResponseSchema = z.object({ data: ProjectDocumentDetailSchema });

/** Only body text and the loaded version are writable; front matter belongs to the backend. */
export const ProjectDocumentSaveSchema = z.strictObject({
  body: z.string().max(1_000_000).refine((body) => body.trim().length > 0),
  expectedRevision: z.number().int().positive(),
});

type DocumentWire = z.infer<typeof ProjectDocumentSummarySchema>;
export interface ProjectDocument extends Omit<DocumentWire, "updated_at" | "icp_key"> {
  updatedAt: string;
  icpKey: string | null;
}
export interface ProjectDocumentDetail extends ProjectDocument {
  markdown: string;
  frontMatter: Record<string, unknown>;
}

export function toProjectDocument(wire: DocumentWire): ProjectDocument {
  return {
    id: wire.id, path: wire.path, kind: wire.kind, title: wire.title,
    version: wire.version, status: wire.status, updatedAt: wire.updated_at, icpKey: wire.icp_key,
  };
}

export function toProjectDocumentDetail(wire: z.infer<typeof ProjectDocumentDetailSchema>): ProjectDocumentDetail {
  return { ...toProjectDocument(wire), markdown: wire.markdown, frontMatter: wire.front_matter };
}

export function selectedProjectDocument(documents: readonly ProjectDocument[], path?: string): ProjectDocument | null {
  return path ? documents.find((document) => document.path === path) ?? null : planDocumentOf(documents);
}

export function planDocumentOf(documents: readonly ProjectDocument[]): ProjectDocument | null {
  return documents.find((document) => document.path === "project/plan.md") ?? null;
}

/** Relative to the supplied clock, displayed in the viewer's local timezone. */
export function documentEditedLabel(updatedAt: string, now: Date): string {
  const edited = new Date(updatedAt);
  const minutes = Math.max(0, Math.floor((now.getTime() - edited.getTime()) / 60_000));
  if (minutes < 1) return "Edited just now";
  if (minutes < 60) return `Edited ${minutes} min ago`;
  if (edited.toDateString() === now.toDateString()) {
    const hour = String(edited.getHours()).padStart(2, "0");
    const minute = String(edited.getMinutes()).padStart(2, "0");
    return `Edited today at ${hour}:${minute}`;
  }
  const month = new Intl.DateTimeFormat("en-US", { month: "short" }).format(edited);
  return `Edited ${edited.getDate()} ${month}`;
}
