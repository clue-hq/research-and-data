import React from "react";

import { WebEditorApp } from "@/components/web/WebEditorApp";

/**
 * /web/[documentId] — the website-mode editor shell. A thin server segment that
 * hands the id to the client shell; all fetching/rendering lives in
 * WebEditorApp so this route never pulls in scene/canvas code.
 */
export default async function WebEditorPage({
  params
}: {
  params: Promise<{ documentId: string }>;
}): Promise<React.ReactElement> {
  const { documentId } = await params;
  return <WebEditorApp documentId={documentId} />;
}
