import { readFile } from "node:fs/promises";
import path from "node:path";
import { MailerSchema } from "@/features/direct-mail/model/direct-mail";
import { isFrontendPreviewMode } from "@/features/preview/data/preview-mode";

/** Optional private, machine-local examples. Never enabled in a production build. */
export async function GET() {
  if (!isFrontendPreviewMode()) return new Response(null, { status: 404 });
  try {
    const text = await readFile(path.join(process.cwd(), ".local/direct-mail-pilot.json"), "utf8");
    const mailers = MailerSchema.array().max(10).parse(JSON.parse(text));
    return Response.json(mailers, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return new Response(null, { status: 204 });
    return Response.json({ error: "The local pilot sample could not be read." }, { status: 500 });
  }
}
