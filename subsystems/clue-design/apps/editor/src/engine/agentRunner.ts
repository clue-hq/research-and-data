import type { Diagnostic, NodeId, Operation, PageId, Scene } from "./contracts";
import { diagnosticSeverity, diagnosticSubject, isRecord } from "./brandDiagnostics";

export interface EditorAgentRequest {
  prompt: string;
  scene: Scene;
  documentId?: string;
  activePageId: PageId | null;
  selectedNodeId: NodeId | null;
  diagnostics: Diagnostic[];
}

export interface EditorAgentTrace {
  run_id: string | null;
  trace_dir: string | null;
  preview_paths: string[];
}

export interface EditorAgentArtifactRef {
  format: string | null;
  page_id: PageId | null;
  filename: string | null;
  path: string | null;
  data_url: string | null;
  mime_type: string | null;
}

export interface EditorAgentResult {
  status: "proposed" | "failed";
  summary: string;
  dsl_blocks: string[];
  operations: Operation[];
  draft_scene: Scene | null;
  stop_reason: string | null;
  /** Phase 0b/0c: "edit" = the requested edit was verified applied and the
   * whole-design critique rides along as advisory; "design" = the reviewer
   * accepted the full design. */
  acceptance_scope: "edit" | "design" | null;
  diagnostics: Diagnostic[];
  trace: EditorAgentTrace;
  artifacts: EditorAgentArtifactRef[];
}

export type EditorAgentRunner = (
  request: EditorAgentRequest
) => EditorAgentResult | Promise<EditorAgentResult>;

export interface ApiAgentRunnerOptions {
  apiBaseUrl: string;
}

export function createApiAgentRunner({ apiBaseUrl }: ApiAgentRunnerOptions): EditorAgentRunner {
  return async ({ prompt, scene, documentId, activePageId, selectedNodeId, diagnostics }) => {
    const response = await fetch(new URL("/agent/turn-preview", apiBaseUrl), {
      method: "POST",
      headers: {
        "content-type": "application/json"
      },
      body: JSON.stringify({
        prompt,
        scene,
        document_id: documentId ?? null,
        active_page_id: activePageId,
        selected_node_id: selectedNodeId,
        diagnostics
      })
    });

    if (!response.ok) {
      throw new Error(`Agent request failed with HTTP ${response.status}`);
    }

    return agentResultFromUnknown(await response.json());
  };
}

export function agentResultFromUnknown(payload: unknown): EditorAgentResult {
  if (!isRecord(payload)) {
    return failedAgentResult("EDITOR_AGENT_INVALID_RESPONSE", "Agent API returned a non-object response.");
  }

  const diagnostics = diagnosticsFromUnknown(payload);
  const operations = Array.isArray(payload.operations)
    ? (payload.operations.filter(isRecord) as unknown as Operation[])
    : [];
  const dslBlocks = dslBlocksFromUnknown(payload);
  const summary = summaryFromUnknown(payload, operations, diagnostics);

  return {
    status: agentStatus(payload, operations, diagnostics),
    summary,
    dsl_blocks: dslBlocks,
    operations,
    draft_scene: sceneFromUnknown(payload.draft_scene),
    stop_reason: typeof payload.stop_reason === "string" ? payload.stop_reason : null,
    acceptance_scope:
      payload.acceptance_scope === "edit" || payload.acceptance_scope === "design"
        ? payload.acceptance_scope
        : null,
    diagnostics,
    trace: traceFromUnknown(payload),
    artifacts: artifactsFromUnknown(payload)
  };
}

function agentStatus(
  payload: Record<string, unknown>,
  operations: Operation[],
  diagnostics: Diagnostic[]
): EditorAgentResult["status"] {
  if (payload.status === "failed" || payload.status === "error") {
    return "failed";
  }
  if (operations.length > 0) {
    return "proposed";
  }
  if (diagnostics.some((diagnostic) => diagnostic.severity === "error")) {
    return "failed";
  }
  return payload.status === "proposed" || payload.status === "accepted" || payload.status === "ok"
    ? "proposed"
    : "failed";
}

function summaryFromUnknown(
  payload: Record<string, unknown>,
  operations: Operation[],
  diagnostics: Diagnostic[]
): string {
  if (typeof payload.summary === "string" && payload.summary.trim()) {
    return payload.summary.trim();
  }
  if (operations.length > 0) {
    return `Agent proposed ${operations.length} canonical operation${operations.length === 1 ? "" : "s"}.`;
  }
  if (diagnostics.length > 0) {
    return diagnostics[0].message;
  }
  return "Agent finished without returning a proposal.";
}

function dslBlocksFromUnknown(payload: Record<string, unknown>): string[] {
  if (Array.isArray(payload.dsl_blocks)) {
    return payload.dsl_blocks.filter((value): value is string => typeof value === "string" && value.trim().length > 0);
  }
  if (typeof payload.dsl === "string" && payload.dsl.trim()) {
    return [payload.dsl.trim()];
  }
  return [];
}

function traceFromUnknown(payload: Record<string, unknown>): EditorAgentTrace {
  const trace = isRecord(payload.trace) ? payload.trace : {};
  const previewPaths = Array.isArray(payload.preview_paths)
    ? payload.preview_paths.filter((value): value is string => typeof value === "string")
    : Array.isArray(trace.preview_paths)
      ? trace.preview_paths.filter((value): value is string => typeof value === "string")
      : [];
  return {
    run_id:
      typeof payload.run_id === "string"
        ? payload.run_id
        : typeof trace.run_id === "string"
          ? trace.run_id
          : null,
    trace_dir:
      typeof payload.trace_dir === "string"
        ? payload.trace_dir
        : typeof trace.trace_dir === "string"
          ? trace.trace_dir
          : null,
    preview_paths: previewPaths
  };
}

function artifactsFromUnknown(payload: Record<string, unknown>): EditorAgentArtifactRef[] {
  const artifacts = Array.isArray(payload.artifacts) ? payload.artifacts : [];
  const directArtifacts = artifacts.flatMap(artifactFromUnknown);
  const pathArtifacts = (Array.isArray(payload.preview_paths) ? payload.preview_paths : [])
    .filter((value): value is string => typeof value === "string")
    .map((path) => ({
      format: formatFromPath(path),
      page_id: null,
      filename: filenameFromPath(path),
      path,
      data_url: null,
      mime_type: null
    }));
  return [...directArtifacts, ...pathArtifacts];
}

function sceneFromUnknown(value: unknown): Scene | null {
  if (!isRecord(value)) {
    return null;
  }
  if (!isRecord(value.meta) || !isRecord(value.pages) || !isRecord(value.nodes)) {
    return null;
  }
  return value as unknown as Scene;
}

function artifactFromUnknown(value: unknown): EditorAgentArtifactRef[] {
  if (!isRecord(value)) {
    return [];
  }
  return [
    {
      format: typeof value.format === "string" ? value.format : null,
      page_id: typeof value.page_id === "string" ? value.page_id : null,
      filename: typeof value.filename === "string" ? value.filename : filenameFromPath(value.path),
      path: typeof value.path === "string" ? value.path : null,
      data_url: typeof value.data_url === "string" ? value.data_url : null,
      mime_type: typeof value.mime_type === "string" ? value.mime_type : null
    }
  ];
}

function filenameFromPath(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) {
    return null;
  }
  return value.split("/").filter(Boolean).at(-1) ?? null;
}

function formatFromPath(path: string): string | null {
  const extension = path.split(".").at(-1)?.toLowerCase();
  if (!extension) {
    return null;
  }
  return extension;
}

function diagnosticsFromUnknown(payload: Record<string, unknown>): Diagnostic[] {
  const directDiagnostics = Array.isArray(payload.diagnostics) ? payload.diagnostics : [];
  return directDiagnostics.flatMap(diagnosticFromUnknown);
}

function diagnosticFromUnknown(value: unknown): Diagnostic[] {
  if (!isRecord(value)) {
    return [];
  }
  return [
    {
      severity: diagnosticSeverity(value.severity),
      phase: diagnosticPhase(value.phase),
      code: typeof value.code === "string" ? value.code : "EDITOR_AGENT_DIAGNOSTIC",
      message: typeof value.message === "string" ? value.message : "Agent returned a diagnostic without a message.",
      subject: diagnosticSubject(value.subject),
      hint: typeof value.hint === "string" ? value.hint : null
    }
  ];
}

function diagnosticPhase(value: unknown): Diagnostic["phase"] {
  switch (value) {
    case "contract":
    case "operation":
    case "validation":
    case "brand":
    case "dsl":
    case "layout":
    case "export":
      return value;
    default:
      return "validation";
  }
}

function failedAgentResult(code: string, message: string): EditorAgentResult {
  return {
    status: "failed",
    summary: message,
    dsl_blocks: [],
    operations: [],
    draft_scene: null,
    stop_reason: null,
    acceptance_scope: null,
    diagnostics: [
      {
        severity: "error",
        phase: "validation",
        code,
        message,
        subject: { kind: "document" },
        hint: null
      }
    ],
    trace: {
      run_id: null,
      trace_dir: null,
      preview_paths: []
    },
    artifacts: []
  };
}
