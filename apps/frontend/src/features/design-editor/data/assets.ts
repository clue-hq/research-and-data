import type { AssetRecord } from "../engine/asset-types";
import { DESIGN_API_BFF_PREFIX } from "./design-bff";

/**
 * W4.2 (mapping contract §1 row 12, lane B): the asset-store upload behind the
 * inspector's Replace-image control.
 *
 * The design API's `POST /assets` speaks workspace-header auth and never faces
 * a browser directly, so this client posts to the BFF mount instead — the
 * proxy forwards the content-type + raw body and stamps the workspace header
 * server-side. The FormData body deliberately carries NO hand-set
 * `Content-Type`: the browser writes the multipart boundary, and setting the
 * header ourselves would strip it and make the body unparseable upstream.
 *
 * Placement stays canonical: this client only mints the record; the document
 * change is the caller's `upsert_asset` + `replace_asset` batch (see
 * `hooks/use-replace-image.ts`), exactly like the upstream editor.
 */

/** A typed refusal from the asset upload seam (design `detail` code + status). */
export class WebAssetUploadError extends Error {
  readonly code: string | null;
  readonly status: number;

  constructor(message: string, options: { code?: string | null; status: number }) {
    super(message);
    this.name = "WebAssetUploadError";
    this.code = options.code ?? null;
    this.status = options.status;
  }
}

interface AssetUploadPayload {
  asset?: AssetRecord;
  deduplicated?: boolean;
  /** FastAPI's refusal body: an object for the ingest errors, a bare string
   * for the plain `HTTPException(detail="…")` cases (413 size, 400 license). */
  detail?: { code?: string; message?: string } | string;
}

export async function uploadWebAsset(
  file: File,
  { fetchImpl }: { fetchImpl?: typeof fetch } = {},
): Promise<AssetRecord> {
  const doFetch: typeof fetch = fetchImpl ?? ((input, init) => fetch(input, init));
  const form = new FormData();
  form.append("file", file);
  form.append("label", file.name);
  const response = await doFetch(`${DESIGN_API_BFF_PREFIX}/assets`, {
    method: "POST",
    body: form,
  });

  let payload: AssetUploadPayload = {};
  try {
    payload = (await response.json()) as AssetUploadPayload;
  } catch {
    // A non-JSON refusal (or an empty body) keeps the status-shaped message.
  }

  if (!response.ok || !payload.asset) {
    const detail = payload.detail;
    const message =
      typeof detail === "string"
        ? detail
        : (detail?.message ??
          detail?.code ??
          `Image upload failed with status ${response.status}`);
    throw new WebAssetUploadError(message, {
      code: typeof detail === "string" ? null : (detail?.code ?? null),
      status: response.status,
    });
  }
  return payload.asset;
}
