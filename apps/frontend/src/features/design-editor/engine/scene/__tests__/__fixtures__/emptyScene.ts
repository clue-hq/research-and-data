import type { Scene } from "../../contracts";

/**
 * The editor's default document: a genuinely EMPTY scene — no demo page, no
 * placeholder content. The user (or the agent) creates the first artboard.
 *
 * This is also what makes a fresh session's first agent turn take the proven
 * generation path: the API treats an empty document as unseeded (no user work
 * to preserve), so the agent authors a new design instead of being forced into
 * continuation mode against leftover demo content.
 */
export const emptyScene: Scene = {
  schema_version: 1,
  meta: {
    id: "doc_untitled",
    title: "Untitled design",
    artifact_type: null,
    medium: "digital",
    brand_kit: null,
    status: { kind: "draft" }
  },
  pages: {},
  nodes: {},
  slots: {},
  assets: {},
  export_profiles: []
} as unknown as Scene;
