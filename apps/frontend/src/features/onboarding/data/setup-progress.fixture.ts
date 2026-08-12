/**
 * Local preview data for the FI-4 setting-up flow.
 *
 * Fixtures are wire-shaped: every frame below is exactly what `GET /api/clue/stage0/setup/current`
 * serves, so the fixture source validates through the same `SetupStatusSchema` the HTTP adapter
 * does. A fixture that skipped validation would let the two drift, which is the failure the
 * repository seam exists to prevent.
 *
 * The script is a **state stream, not a lifecycle model**: the poll tick is transport, the frame
 * is the state. Nothing here advances because time passed — every state the checklist renders
 * comes from a frame, exactly as it does against a live backend.
 *
 * What it replays is the honest slice-3 vocabulary, end to end:
 *
 * 1. `starting` — the submission is durably captured, no recon row is visible yet (no field
 *    events at all, so the checklist shows its warm-up row and claims nothing else).
 * 2. the FAST lane walking the Client-KB baseline fields in budget order, announcing `started`
 *    as it reaches each one and exactly one terminal after (`resolved`, or `empty` — a field no
 *    source could answer is a *correct* outcome, not a failure). This whole walk is still served
 *    as `starting` with a null `recon_run_id`: the fast lane lives inside one transaction, so its
 *    `recon_run` row is invisible until it commits, and the autonomously-committed per-field
 *    events are the only motion there is to show (`platform/api/clue_api/stage0_setup.py`, the
 *    "captured" branch). Overall `running` is therefore NOT part of a healthy fast lane's
 *    vocabulary, and this script does not fabricate it.
 * 3. `complete` — the lane's transaction committed and the fast lane finished; this is the
 *    release-into-the-app signal, and it carries `fact_count` plus a terminal for all eleven
 *    baseline fields. The script **ends here**, where the screen's life ends: the hook releases
 *    on this frame and never polls again.
 *
 * Deliberately NOT scripted: the background lane's second pass. It is not a touch-up of the two
 * tier-3-only fields — it calls `reverse_profile` fresh over EVERY baseline field, and the
 * backend's reduction is last-writer-wins per field *across* lanes ("a lane's own field row wins
 * over an earlier lane's for the same field", `platform/api/clue_api/stage0_setup.py`), so a real
 * post-release poll shows all eleven rows migrating to `lane: "background"` in baseline order.
 * Scripting a partial migration would be a lie about the wire, and scripting the honest full
 * second walk would double the script for frames no consumer can reach.
 */

import type { SetupStatus } from "./setup";

/** The Client-KB baseline field order — the order the recon lane walks (its outer budget order)
 * and the order the backend serves the reduced per-field list in. Mirrors
 * `clue_research.stage0.fields.CLIENT_BASELINE_FIELDS`; the client never re-sorts. */
export const FIXTURE_SETUP_BASELINE_FIELDS = [
  "client.value_prop",
  "client.product",
  "client.differentiator",
  "client.pricing_posture",
  "client.proof_point",
  "client.customer",
  "client.icp_evidence",
  "client.market_reputation",
  "client.delivered_value",
  // Tier-3-only, appended at the end of the budget order on purpose: the fast lane's
  // max_source_tier=2 gate walks past them at zero spend (so: `empty`), and the background lane
  // is where they get a real attempt.
  "client.competitor",
  "client.buyer_profile",
] as const;

const FIXTURE_RECON_RUN_ID = "5c1f0a2e-0000-4000-8000-0000000000f4";
const FIXTURE_COMPANY_WEBSITE = "https://cluehq.ai";

/** How the fast lane's zero-to-tier-2 pass ends for each field. Review surfaces have no tier≤2
 * resolver bound, so they come back empty — the honest outcome, not a failure.
 *
 * Keyed on the baseline union, not `string`: a mistyped or missing key is then a compile error
 * rather than an `undefined` status the schema would quietly degrade to `"started"`. */
const FAST_LANE_OUTCOME: Record<
  (typeof FIXTURE_SETUP_BASELINE_FIELDS)[number],
  "resolved" | "empty"
> = {
  "client.value_prop": "resolved",
  "client.product": "resolved",
  "client.differentiator": "resolved",
  "client.pricing_posture": "resolved",
  "client.proof_point": "resolved",
  "client.customer": "resolved",
  "client.icp_evidence": "resolved",
  "client.market_reputation": "empty",
  "client.delivered_value": "resolved",
  "client.competitor": "empty",
  "client.buyer_profile": "empty",
};

/** One claim per field the fast lane resolved — what the fast Client-KB version carries. */
const FIXTURE_FACT_COUNT = Object.values(FAST_LANE_OUTCOME).filter(
  (outcome) => outcome === "resolved",
).length;

/** Every key the endpoint serves, explicit nulls included — the wire shape, not a partial. */
const EMPTY_FRAME: SetupStatus = {
  status: "none",
  recon_run_id: null,
  fast_status: null,
  background_status: null,
  company_website: null,
  fast_client_kb_version: null,
  fact_count: null,
  fields: [],
  fast_budget_exhausted: null,
  background_budget_exhausted: null,
};

function frame(over: Partial<SetupStatus>): SetupStatus {
  return { ...EMPTY_FRAME, ...over };
}

type FieldFrame = SetupStatus["fields"][number];

function fastField(field_key: string, status: "started" | "resolved" | "empty"): FieldFrame {
  return { field_key, lane: "fast", status };
}

/** The fast lane's per-field state after it has finished `count` fields and started nothing else. */
function fastTerminals(count: number): SetupStatus["fields"] {
  return FIXTURE_SETUP_BASELINE_FIELDS.slice(0, count).map((key) =>
    fastField(key, FAST_LANE_OUTCOME[key]),
  );
}

/** What the "captured, run not yet visible" branch serves: the website and the field events,
 * every lane column still null — it has no recon row to read them from. */
const FAST_LANE_BASE = {
  status: "starting" as const,
  company_website: FIXTURE_COMPANY_WEBSITE,
};

/**
 * The fast lane in flight: one frame per field, each showing the fields already finished plus the
 * one currently being resolved. A real 1.5s poll tick sees about this much motion.
 */
const FAST_LANE_FRAMES: SetupStatus[] = FIXTURE_SETUP_BASELINE_FIELDS.map((key, index) =>
  frame({
    ...FAST_LANE_BASE,
    fields: [...fastTerminals(index), fastField(key, "started")],
  }),
);

/** All eleven attempted, the lane's transaction not committed yet — a real snapshot, briefly. */
const FAST_LANE_SETTLED: SetupStatus = frame({
  ...FAST_LANE_BASE,
  fields: fastTerminals(FIXTURE_SETUP_BASELINE_FIELDS.length),
});

/** The release: the fast lane completed, the background lane picked up behind it. */
const FAST_LANE_COMPLETE: SetupStatus = frame({
  recon_run_id: FIXTURE_RECON_RUN_ID,
  company_website: FIXTURE_COMPANY_WEBSITE,
  status: "complete",
  fast_status: "completed",
  background_status: "running",
  fast_client_kb_version: 1,
  fact_count: FIXTURE_FACT_COUNT,
  fast_budget_exhausted: false,
  fields: fastTerminals(FIXTURE_SETUP_BASELINE_FIELDS.length),
});

/**
 * The default scripted stream. Frame-per-read: the fixture source hands out the next frame on
 * every poll and sticks at the last one — a stream that has run out of states does not invent
 * more. Sticking on the release frame is the honest end: the background lane's own truth is a
 * second full walk this script does not fabricate (see the header).
 */
export const FIXTURE_SETUP_PROGRESS_SCRIPT: readonly SetupStatus[] = [
  // Durably captured, no recon row visible yet — the warm-up state, and a real durable signal.
  frame({ ...FAST_LANE_BASE }),
  ...FAST_LANE_FRAMES,
  FAST_LANE_SETTLED,
  FAST_LANE_COMPLETE,
];
