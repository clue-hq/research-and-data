import type { Diagnostic, NodeId, Operation, PageId, Scene } from "./contracts";
import { diagnosticSeverity, diagnosticSubject, isRecord } from "./brandDiagnostics";

/** One progress event streamed from an async agent run (2b show-work). The
 * server persists these to a durable store; the editor renders a curated
 * subset as the Moda plan checklist and keeps the rest behind "Show work". */
export interface AgentRunEvent {
  seq: number;
  type: string;
  data: {
    actor?: string;
    iteration?: number;
    input_summary?: string | null;
    output_summary?: string | null;
    diagnostic_count?: number;
    run_id?: string;
    [key: string]: unknown;
  };
}

export interface EditorAgentRequest {
  prompt: string;
  scene: Scene;
  documentId?: string;
  activePageId: PageId | null;
  /** 2c: the chipped edit targets. Sent as target_node_ids; the server scopes
   * the compensating edit to them and keeps every other node byte-identical. */
  targetNodeIds?: NodeId[];
  /** RC: the library asset ids the user attached as visual references for THIS
   * turn. Sent as reference_asset_ids; the server resolves them into the run's
   * reference manifest by value. Per-turn context — cleared after each send. */
  referenceAssetIds?: string[];
  /** 2e: the document's standing instructions, folded into every turn. */
  agentInstructions?: string | null;
  /** Model override for this turn (runtime id, e.g. "openai:anthropic/...").
   * null/undefined = the runtime's configured default. */
  model?: string | null;
  diagnostics: Diagnostic[];
  /** 2b: live run events (checklist ticks) are pushed here as they stream. */
  onEvent?: (event: AgentRunEvent) => void;
}

/** The minimal EventSource surface we depend on — injectable so jsdom tests
 * (no global EventSource) drive the stream with a fake, and so the browser
 * API is never stored bare (docs/frontend-practices.md rule 8). */
export interface EventSourceLike {
  addEventListener(type: string, listener: (event: { data: string }) => void): void;
  close(): void;
  onerror: ((event: unknown) => void) | null;
}

export type EventSourceFactory = (url: string) => EventSourceLike;

function defaultEventSourceFactory(url: string): EventSourceLike {
  if (typeof EventSource === "undefined") {
    throw new Error("EventSource is unavailable in this environment.");
  }
  return new EventSource(url) as unknown as EventSourceLike;
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
  return async ({
    prompt,
    scene,
    documentId,
    activePageId,
    targetNodeIds,
    referenceAssetIds,
    agentInstructions,
    model,
    diagnostics
  }) => {
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
        target_node_ids: targetNodeIds ?? [],
        reference_asset_ids: referenceAssetIds ?? [],
        agent_instructions: agentInstructions ?? null,
        model: model ?? null,
        diagnostics
      })
    });

    if (!response.ok) {
      throw new Error(`Agent request failed with HTTP ${response.status}`);
    }

    return agentResultFromUnknown(await response.json());
  };
}

export interface StreamingAgentRunnerOptions {
  apiBaseUrl: string;
  eventSourceFactory?: EventSourceFactory;
}

/**
 * 2b async turn: POST /agent/turns returns a run_id immediately; the run
 * executes server-side and streams progress over SSE. Live events flow to
 * `request.onEvent` for the checklist; the promise resolves with the final
 * EditorAgentResult carried on the stream's terminal `done` frame — so the
 * caller's Accept/Reject flow is identical to the synchronous runner.
 */
export function createStreamingAgentRunner({
  apiBaseUrl,
  eventSourceFactory = defaultEventSourceFactory
}: StreamingAgentRunnerOptions): EditorAgentRunner {
  return async ({
    prompt,
    scene,
    documentId,
    activePageId,
    targetNodeIds,
    referenceAssetIds,
    agentInstructions,
    model,
    diagnostics,
    onEvent
  }) => {
    const response = await fetch(new URL("/agent/turns", apiBaseUrl), {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        prompt,
        scene,
        document_id: documentId ?? null,
        active_page_id: activePageId,
        target_node_ids: targetNodeIds ?? [],
        reference_asset_ids: referenceAssetIds ?? [],
        agent_instructions: agentInstructions ?? null,
        model: model ?? null,
        diagnostics
      })
    });
    if (!response.ok) {
      throw new Error(`Agent request failed with HTTP ${response.status}`);
    }
    const started = (await response.json()) as { run_id?: unknown };
    const runId = typeof started.run_id === "string" ? started.run_id : null;
    if (!runId) {
      throw new Error("Agent turn did not return a run id.");
    }
    // Surface the run id through the event channel so the caller can persist
    // it and rejoin the stream after a tab reload (resume-on-mount).
    onEvent?.({ seq: 0, type: "run_started", data: { run_id: runId } });
    return subscribeToAgentRun({ apiBaseUrl, runId, onEvent, eventSourceFactory });
  };
}

export interface SubscribeToAgentRunOptions {
  apiBaseUrl: string;
  runId: string;
  onEvent?: (event: AgentRunEvent) => void;
  eventSourceFactory?: EventSourceFactory;
}

/**
 * Open the SSE stream for a run and resolve with its final result. On first
 * connect the server replays every event from seq 0, so this doubles as the
 * resume path: rejoining an in-flight (or already-finished) run after a tab
 * reload replays the checklist and then either streams live ticks or resolves
 * immediately from the stored result. EventSource auto-reconnects on transient
 * drops, re-requesting via Last-Event-ID — we never reject on a stream error.
 */
export function subscribeToAgentRun({
  apiBaseUrl,
  runId,
  onEvent,
  eventSourceFactory = defaultEventSourceFactory
}: SubscribeToAgentRunOptions): Promise<EditorAgentResult> {
  return new Promise((resolve, reject) => {
    let source: EventSourceLike;
    try {
      source = eventSourceFactory(new URL(`/agent/runs/${runId}/events`, apiBaseUrl).toString());
    } catch (error) {
      reject(error instanceof Error ? error : new Error(String(error)));
      return;
    }
    source.addEventListener("progress", (event) => {
      const parsed = runEventFromUnknown(event.data);
      if (parsed) {
        onEvent?.(parsed);
      }
    });
    source.addEventListener("done", (event) => {
      let result: EditorAgentResult;
      try {
        result = agentResultFromUnknown(JSON.parse(event.data));
      } catch {
        result = failedAgentResult(
          "EDITOR_AGENT_STREAM_INVALID",
          "The agent run finished but its result could not be read."
        );
      }
      source.close();
      resolve(result);
    });
    // Transient errors are handled by EventSource's own reconnect (Last-Event-ID
    // replays missed events); a terminal run always ends with a `done` frame.
  });
}

function runEventFromUnknown(raw: string): AgentRunEvent | null {
  try {
    const parsed = JSON.parse(raw);
    if (!isRecord(parsed) || typeof parsed.seq !== "number" || typeof parsed.type !== "string") {
      return null;
    }
    return {
      seq: parsed.seq,
      type: parsed.type,
      data: isRecord(parsed.data) ? (parsed.data as AgentRunEvent["data"]) : {}
    };
  } catch {
    return null;
  }
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
