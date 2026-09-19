import { z } from "zod";

/**
 * The chat-attachment upload seam: one file in, one durable upload record out.
 *
 * The backend's `POST /frontend/v1/uploads` speaks workspace-header auth and
 * never faces a browser directly, so this client posts to the same-origin BFF
 * mount, which forwards the raw multipart body and stamps the workspace header
 * server-side. The FormData body deliberately carries NO hand-set
 * `Content-Type`: the browser writes the multipart boundary, and setting the
 * header ourselves would strip it and make the body unparseable upstream.
 *
 * Refusals arrive as the FI-1 error envelope (413 `UPLOAD_TOO_LARGE`, 415
 * `UPLOAD_UNSUPPORTED_TYPE`, 422 for the rest); the message is what the
 * composer shows on the failed chip, so it is read from the envelope rather
 * than invented here.
 */
const UPLOADS_URL = "/api/clue/frontend/v1/uploads";

const UploadResponseSchema = z.object({
  data: z.object({
    artifact_key: z.string().min(1),
    byte_count: z.number().int().nonnegative(),
    filename: z.string().min(1),
    media_type: z.string().min(1),
    sha256: z.string().regex(/^[0-9a-f]{64}$/),
    upload_id: z.string().min(1),
  }),
});

const ErrorEnvelopeSchema = z.object({
  error: z.object({
    code: z.string().min(1),
    message: z.string().min(1),
  }),
});

export interface ChatUpload {
  artifactKey: string;
  byteCount: number;
  filename: string;
  mediaType: string;
  sha256: string;
  uploadId: string;
}

export async function uploadChatFile(
  file: File,
  { fetchImpl }: { fetchImpl?: typeof fetch } = {},
): Promise<ChatUpload> {
  const doFetch: typeof fetch =
    fetchImpl ?? ((input, init) => fetch(input, init));
  const form = new FormData();
  form.append("file", file);
  const response = await doFetch(UPLOADS_URL, { method: "POST", body: form });

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // A proxy error page or an empty body is not an envelope; the status-shaped
    // message below stands in for it.
  }

  if (!response.ok) {
    const envelope = ErrorEnvelopeSchema.safeParse(payload);
    throw new Error(
      envelope.success
        ? envelope.data.error.message
        : `Upload failed (${response.status}).`,
    );
  }

  const parsed = UploadResponseSchema.safeParse(payload);
  if (!parsed.success) {
    throw new Error("The upload did not return a usable upload record.");
  }
  const data = parsed.data.data;
  return {
    artifactKey: data.artifact_key,
    byteCount: data.byte_count,
    filename: data.filename,
    mediaType: data.media_type,
    sha256: data.sha256,
    uploadId: data.upload_id,
  };
}
