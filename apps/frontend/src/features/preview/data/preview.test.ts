import assert from "node:assert/strict";
import test from "node:test";
import { isFrontendPreviewMode } from "./preview-mode";
import { createPreviewBackend } from "./preview-backend";
import { ProfileSchema } from "@/features/settings/model/profile";
import { WorkspaceSchema } from "@/features/settings/model/workspace";
import { MembersSchema } from "@/features/settings/model/members";
import { PagesSettingsReadSchema } from "@/features/settings/model/pages";
import { ResearchFieldsSchema } from "@/features/settings/model/research-fields";
import { ProjectDocumentDetailResponseSchema, ProjectDocumentsResponseSchema } from "@/features/projects/model/project-documents";
import { uploadChatFile } from "@/features/projects/data/uploads.repository";
import { getDiscoveryStatus } from "@/features/accounts/data/discovery-status.repository";
import { getResearchProgress } from "@/features/accounts/data/research-progress.repository";
import { fetchRead } from "@/features/accounts/data/frontend-api";
import { readProductNotices } from "@/features/projects/data/product-notices";

const previewEnv = {
  NODE_ENV: "development", CLUE_FRONTEND_PREVIEW_MODE: "true",
  CLUE_AUTH_ENABLED: "false", CLUE_APP_ORIGIN: "http://localhost:5000",
  CLUE_ACCOUNTS_FIXTURE_MODE: "true",
};

test("preview is opt-in and refuses production, authentication or backend connections", () => {
  assert.equal(isFrontendPreviewMode({}), false);
  assert.equal(isFrontendPreviewMode(previewEnv), true);
  for (const override of [
    { NODE_ENV: "production" }, { CLUE_AUTH_ENABLED: "true" },
    { CLUE_API_BASE_URL: "https://api.example.com" },
    { CLUE_PROJECTS_API_BASE_URL: "/api/clue" },
    { LUMEN_API_BASE_URL: "http://localhost:8111" },
    { CLUE_APP_ORIGIN: "https://app.example.com" },
    { CLUE_ACCOUNTS_FIXTURE_MODE: "false" },
  ]) assert.throws(() => isFrontendPreviewMode({ ...previewEnv, ...override }), /preview/i);
});

test("preview serves the real Settings schemas and retains profile edits within its session", async () => {
  const request = createPreviewBackend();
  for (const [path, schema] of [
    ["profile", ProfileSchema], ["workspace", WorkspaceSchema],
    ["members", MembersSchema], ["pages", PagesSettingsReadSchema],
    ["research-fields?entity=accounts", ResearchFieldsSchema],
    ["research-fields?entity=contacts", ResearchFieldsSchema],
  ] as const) schema.parse(await (await request(`/frontend/v1/settings/${path}`)).json());
  const response = await request("/frontend/v1/settings/profile", {
    method: "PATCH", body: JSON.stringify({ display_name: "Demo reviewer" }),
  });
  assert.equal(response.status, 200);
  assert.equal((await (await request("/frontend/v1/settings/profile")).json()).display_name, "Demo reviewer");
  assert.notEqual((await (await createPreviewBackend()("/frontend/v1/settings/profile")).json()).display_name, "Demo reviewer");
});

test("Gallery and document editor share versioned, project-isolated demo documents", async () => {
  const request = createPreviewBackend();
  const path = "/frontend/v1/projects/10m-landing-page-campaign/documents";
  const list = ProjectDocumentsResponseSchema.parse(await (await request(path)).json());
  assert.ok(list.data.documents.length >= 2);
  const documentPath = `${path}/${list.data.documents[0].id}`;
  const detail = ProjectDocumentDetailResponseSchema.parse(await (await request(documentPath)).json()).data;
  const update = { method: "PUT", body: JSON.stringify({ body: "# Updated local plan", expected_revision: detail.version }) };
  const saved = ProjectDocumentDetailResponseSchema.parse(await (await request(documentPath, update)).json()).data;
  assert.equal(saved.version, detail.version + 1);
  assert.equal(saved.markdown, "# Updated local plan");
  assert.equal((await request(documentPath, update)).status, 409);
  assert.equal((await request(documentPath.replace("10m-landing-page-campaign", "custom-reports"))).status, 404);
});

test("preview attachment adapter accepts a file without an external upload", async () => {
  const request = createPreviewBackend();
  const file = new File(["Local sample"], "brief.txt", { type: "text/plain" });
  const upload = await uploadChatFile(file, { fetchImpl: async (_url, init) => request("/frontend/v1/uploads", init) });
  assert.equal(upload.filename, file.name);
  assert.equal(upload.byteCount, file.size);
  assert.match(upload.uploadId, /^preview-/);
  assert.match(upload.sha256, /^[a-f0-9]{64}$/);
});

test("unsupported preview actions fail explicitly instead of forwarding or pretending to send", async () => {
  const request = createPreviewBackend();
  const response = await request("/frontend/v1/settings/members/invitations", { method: "POST" });
  assert.equal(response.status, 501);
  assert.equal((await response.json()).error.code, "PREVIEW_ACTION_UNAVAILABLE");
});

test("project background reads show no live jobs or notices in the isolated preview", async () => {
  const request = createPreviewBackend();
  const read: typeof fetchRead = (path, options) => fetchRead(path, options, request);
  assert.equal(await getDiscoveryStatus("demo", read), null);
  assert.equal(await getResearchProgress("demo", read), null);
  assert.deepEqual(await readProductNotices("demo", async (url, init) => request(String(url).replace("/api/clue", ""), init)), []);
});
