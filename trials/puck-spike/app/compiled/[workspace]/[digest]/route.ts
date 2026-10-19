// D2 spike (Task 4): serve a compiled agent section, per workspace.
//
// GET /compiled/<workspace>/<sha256>.mjs returns data/compiled/<workspace>/<sha256>.mjs, and 404
// for anything else: a digest stored under another workspace, a malformed id, a path trick. This
// is the spike's whole tenant-isolation check; the workspace comes from the URL, so in production
// it must come from the signed-in session instead (see RUNTIME-SECTIONS.md, question 6).
import fs from "node:fs";
import path from "node:path";

const WORKSPACE = /^[a-z0-9][a-z0-9-]{0,62}$/;
const DIGEST = /^[0-9a-f]{64}$/;

export async function GET(_request: Request, { params }: { params: Promise<{ workspace: string; digest: string }> }) {
  const { workspace, digest } = await params;
  const sha = digest.endsWith(".mjs") ? digest.slice(0, -4) : digest;
  const notFound = () => new Response("not found", { status: 404, headers: { "content-type": "text/plain" } });
  if (!WORKSPACE.test(workspace) || !DIGEST.test(sha)) return notFound();
  const file = path.join(process.cwd(), "data", "compiled", workspace, `${sha}.mjs`);
  if (!fs.existsSync(file)) return notFound();
  return new Response(fs.readFileSync(file), {
    headers: {
      "content-type": "text/javascript; charset=utf-8",
      "x-content-type-options": "nosniff",
      // Content-addressed, so it never changes; private because the URL names a tenant.
      "cache-control": "private, max-age=31536000, immutable",
    },
  });
}

export const dynamic = "force-dynamic";
