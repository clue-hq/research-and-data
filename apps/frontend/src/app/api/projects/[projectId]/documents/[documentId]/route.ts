import { handleProjectDocuments } from "../../../project-documents-handler";

type Context = { params: Promise<{ projectId: string; documentId: string }> };

export async function GET(request: Request, { params }: Context) {
  return handleProjectDocuments(request, await params);
}

export async function PUT(request: Request, { params }: Context) {
  return handleProjectDocuments(request, await params);
}
