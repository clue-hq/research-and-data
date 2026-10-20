import type { ChatToolPart } from "./chat-parts";

/**
 * The normal chat surface is for campaign operators, not backend diagnostics.
 *
 * Tool receipts deliberately contain operation ids, artifact addresses,
 * hashes, object refs, schema versions and other provenance needed by the
 * platform. None of that is display copy. This module is an allowlist: known
 * operations project a few business facts, while an unknown operation exposes
 * only a humanized activity name and state. The raw receipt remains available
 * in the developer turn inspector.
 */

export interface ToolDisplayRow {
  label: string;
  value: string;
}

export interface ToolPresentation {
  label: string;
  rows: readonly ToolDisplayRow[];
  failureMessage: string | null;
}

const TOOL_LABELS: Readonly<Record<string, string>> = {
  submit_onboarding_input: "Save onboarding details",
  start_recon: "Review the company website",
  confirm_project_product: "Confirm the product",
  record_interview_answer: "Save your answer",
  evaluate_stage0_readiness: "Check profile readiness",
  override_stage0_readiness: "Record the readiness decision",
  inspect_readiness_history: "Review profile readiness",
  synthesize_icps: "Create an ideal customer profile proposal",
  author_icp_document: "Draft an ideal customer profile",
  request_persona_synthesis: "Write the buyer personas",
  write_project_document: "Write the project plan",
  open_icp_confirmation_gate: "Prepare the profile for your review",
  start_confirmed_project_run: "Start the project",
  draft_account_research_directive: "Prepare the research plan",
  launch_account_research: "Start account research",
  read_project_accounts: "Review the project's accounts",
  read_account_research: "Review an account's research",
  read_discovery_run: "Review the discovery run",
  read_claims: "Query the claims",
  read_artifact: "Open an artifact",
  web_search: "Search the web",
  manage_products: "Update the product list",
  connect_crm: "Connect your CRM",
  find_crm_actions: "Look up CRM actions",
  run_crm_action: "Read from your CRM",
  write_brand_document: "Update brand context",
};

const FIELD_LABELS: Readonly<Record<string, string>> = {
  "client.customer": "target customers",
  "client.delivered_value": "customer outcomes",
  "client.differentiator": "what makes the product different",
  "client.icp_evidence": "customer-fit evidence",
  "client.market_reputation": "market reputation",
  "client.pricing_posture": "pricing approach",
  "client.product": "product details",
  "client.proof_point": "proof points",
  "client.value_prop": "value proposition",
};

const REASON_COPY: Readonly<Record<string, string>> = {
  product_not_confirmed: "Product details still need confirmation.",
  client_not_bound: "Company details are not connected to this project yet.",
  coverage_below_floor: "More company information is needed.",
};

const OPAQUE_VALUE =
  /^(?:[0-9a-f]{32,}|[0-9a-f]{8}-[0-9a-f-]{27,}|(?:ws|prj|usr|prd|thr|agent-gate)[_:.-])/i;

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function positiveVersion(value: unknown): number | null {
  const number = finiteNumber(value);
  return number !== null && Number.isInteger(number) && number > 0 ? number : null;
}

function titleCase(value: string): string {
  return value
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\p{L}/gu, (letter) => letter.toLocaleUpperCase());
}

export function profileDisplayName(value: unknown): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    value.length > 100 ||
    OPAQUE_VALUE.test(value)
  ) {
    return "Ideal customer profile";
  }
  const label = titleCase(value);
  return label || "Ideal customer profile";
}

export function toolDisplayLabel(toolName: string): string {
  return TOOL_LABELS[toolName] ?? "Complete a project step";
}

function outputValues(part: ChatToolPart): Record<string, unknown> {
  const output = part.output ?? {};
  return record(output.reference_values) ?? output;
}

function readinessRows(values: Record<string, unknown>): ToolDisplayRow[] {
  const rows: ToolDisplayRow[] = [];
  const verdict = values.verdict ?? values.effective_verdict;
  if (verdict === "ready") {
    rows.push({ label: "Result", value: "Ready to create a profile" });
  } else if (verdict === "not_ready") {
    rows.push({ label: "Result", value: "More information needed" });
  }

  const coverage = finiteNumber(values.coverage_ratio);
  if (coverage !== null && coverage >= 0 && coverage <= 1) {
    rows.push({
      label: "Information available",
      value: `${Math.round(coverage * 100)}%`,
    });
  }

  const verified = finiteNumber(values.verified_claims);
  if (verified !== null && verified >= 0 && Number.isInteger(verified)) {
    rows.push({ label: "Verified facts", value: String(verified) });
  }

  if (Array.isArray(values.available_field_keys)) {
    const fields = values.available_field_keys
      .map((key) => (typeof key === "string" ? FIELD_LABELS[key] : undefined))
      .filter((label): label is string => label !== undefined);
    if (fields.length > 0) {
      rows.push({ label: "Known details", value: fields.join(", ") });
    }
  }

  if (Array.isArray(values.reason_codes)) {
    const reasons = values.reason_codes
      .map((reason) => (typeof reason === "string" ? REASON_COPY[reason] : undefined))
      .filter((reason): reason is string => reason !== undefined);
    if (reasons.length > 0) {
      rows.push({ label: "What is missing", value: reasons.join(" ") });
    }
  }
  return rows;
}

function profileRow(value: unknown): ToolDisplayRow | null {
  const spec = record(value);
  if (spec === null) return null;
  const name = profileDisplayName(spec.icp_key);
  const version = positiveVersion(spec.icp_version ?? spec.version);
  return {
    label: "Proposal",
    value: version === null ? name : `${name} · Version ${version}`,
  };
}

function synthesisRows(values: Record<string, unknown>): ToolDisplayRow[] {
  if (!Array.isArray(values.icp_specs)) return [];
  return values.icp_specs
    .map(profileRow)
    .filter((row): row is ToolDisplayRow => row !== null)
    .slice(0, 3);
}

function gateRows(values: Record<string, unknown>): ToolDisplayRow[] {
  const proposal = profileRow(values.subject_ref);
  return proposal === null
    ? [{ label: "Status", value: "Ready for your review" }]
    : [proposal, { label: "Status", value: "Ready for your review" }];
}

function historyRows(values: Record<string, unknown>): ToolDisplayRow[] {
  const rows: ToolDisplayRow[] = [];
  const returned = finiteNumber(values.returned);
  if (returned !== null && returned >= 0 && Number.isInteger(returned)) {
    rows.push({ label: "Checks reviewed", value: String(returned) });
  }
  if (Array.isArray(values.decisions) && values.decisions.length > 0) {
    const latest = record(values.decisions[0]);
    if (latest !== null) {
      rows.push(
        ...readinessRows({ ...(record(latest.metrics) ?? {}), ...latest }).slice(0, 2),
      );
    }
  }
  return rows;
}

function researchPlanRows(part: ChatToolPart): ToolDisplayRow[] {
  const values = outputValues(part);
  const count = finiteNumber(
    values.accounts ?? values.account_count ?? part.input?.account_count,
  );
  return count !== null && count >= 0 && Number.isInteger(count)
    ? [{ label: "Accounts", value: String(count) }]
    : [];
}

function rowsFor(part: ChatToolPart): ToolDisplayRow[] {
  const values = outputValues(part);
  switch (part.toolName) {
    case "evaluate_stage0_readiness":
      return readinessRows(values);
    case "inspect_readiness_history":
      return historyRows(values);
    case "synthesize_icps":
      return synthesisRows(values);
    case "open_icp_confirmation_gate":
      return gateRows(values);
    case "draft_account_research_directive":
      return researchPlanRows(part);
    default:
      // Fail closed: a future tool cannot leak a raw receipt merely because no
      // display adapter was added for it yet.
      return [];
  }
}

export function toolPresentation(part: ChatToolPart): ToolPresentation {
  const failed = part.state === "output-denied" || part.state === "output-error";
  return {
    label: toolDisplayLabel(part.toolName),
    rows: failed ? [] : rowsFor(part),
    failureMessage: failed
      ? "This step could not be completed. Ask the assistant to try again."
      : null,
  };
}
