import { fetchRead } from "@/features/accounts/data/frontend-api";
import { resolveChatTransport } from "@/features/projects/data/chat-api";
import {
  ArtifactListResponseSchema,
  toLibraryArtifact,
  type ArtifactLibraryData,
} from "../model/artifact-library";

const PAGE_SIZE = 200;
/** Ruling: the whole library is server-rendered by walking the cursor. The ceiling only stops a
 * cursor that never terminates; 50 × 200 rows is far beyond any workspace today. */
const MAX_PAGES = 50;

export async function getArtifactLibrary(read: typeof fetchRead = fetchRead): Promise<ArtifactLibraryData> {
  if (resolveChatTransport().mode === "fixture") return { artifacts: [] };
  const artifacts: ArtifactLibraryData["artifacts"] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const body = ArtifactListResponseSchema.parse(
      await read("/artifacts", { searchParams: { cursor, limit: PAGE_SIZE } }),
    );
    for (const row of body.data.artifacts) artifacts.push(toLibraryArtifact(row));
    if (!body.meta.next_cursor) return { artifacts };
    cursor = body.meta.next_cursor;
  }
  throw new Error("The artifacts library did not finish paging.");
}
