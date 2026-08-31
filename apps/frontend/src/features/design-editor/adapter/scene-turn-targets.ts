export interface SceneTurnTargetSnapshot {
  documentId: string;
  documentVersion: number | null;
  targetNodeIds: string[];
}

/**
 * Freeze selection synchronously, then wait for any optimistic writes so the
 * version stamped on the turn is the version the server has actually accepted.
 */
export async function snapshotSceneTurnTargets({
  awaitWritesSettled,
  documentId,
  loadedVersion,
  persistedVersion,
  selectedIds,
}: {
  awaitWritesSettled: (documentId: string) => Promise<void>;
  documentId: string;
  loadedVersion: number | null;
  persistedVersion: (documentId: string) => number | null;
  selectedIds: readonly string[];
}): Promise<SceneTurnTargetSnapshot> {
  const targetNodeIds = [...selectedIds];
  await awaitWritesSettled(documentId);
  return {
    documentId,
    documentVersion: persistedVersion(documentId) ?? loadedVersion,
    targetNodeIds,
  };
}
