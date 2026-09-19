import { handleProjectDocuments } from "../../project-documents-handler";

export async function GET(request: Request, { params }: { params: Promise<{ projectId: string }> }) {
  return handleProjectDocuments(request, await params);
}
