"use client";

import {
  bodyPlaceholder,
  budgetRatio,
  layerLabel,
  type ChatInspectorBody,
  type ChatInspectorContext,
  type ChatInspectorPlanView,
  type ChatInspectorRound,
  type ChatInspectorToolsView,
} from "../model/chat-inspector";
import {
  INSPECTOR_TABS,
  type InspectorTab,
  type TurnInspectorController,
} from "../hooks/use-turn-inspector";
import { ProjectIcon } from "./project-icon";
import styles from "./project-flow.module.css";

/**
 * The dev-lens drawer's body — four tabs over one turn's C6 receipts.
 *
 * Presentation only: it receives a typed controller and touches no repository,
 * no transport and no fixture, exactly like every other component in this
 * feature. The reads live in `useTurnInspector`.
 *
 * This module is **only ever reached through `next/dynamic`** (see
 * `chat-turn-inspector.tsx`), so it and its schemas are code-split into a chunk
 * a browser downloads the first time a developer opens the drawer, and never
 * otherwise. In a production deployment the affordance that would open it is not
 * rendered at all — the capability probe 404s, because the routes were never
 * registered — so the chunk is never requested.
 *
 * It renders receipts and nothing else. Where a body is absent it says which of
 * the four reasons applies; where a fact was never made durable it says so
 * rather than filling the space.
 */

const TAB_LABELS: Record<InspectorTab, string> = {
  context: "Context",
  rounds: "Rounds",
  plan: "Plan",
  tools: "Tools",
};

function BodyView({ body }: { body: ChatInspectorBody }) {
  const placeholder = bodyPlaceholder(body);
  return (
    <div className={styles.turnLensBody}>
      {placeholder ? (
        <p className={styles.turnLensNote} role="note">
          {placeholder}
        </p>
      ) : (
        <pre className={styles.turnLensPre}>{body.text}</pre>
      )}
      <p className={styles.turnLensAddress}>{body.artifactKey}</p>
    </div>
  );
}

function ContextTab({ view }: { view: ChatInspectorContext | null }) {
  if (view === null) {
    return (
      <p className={styles.turnLensNote} role="note">
        This turn assembled no context bundle — it failed before L1.
      </p>
    );
  }
  return (
    <div className={styles.turnLensSection}>
      <dl className={styles.turnLensMeta}>
        <dt>Policy</dt>
        <dd>{view.policyVersion}</dd>
        <dt>Token counter</dt>
        <dd>{view.tokenCounterVersion}</dd>
        <dt>Digest</dt>
        <dd className={styles.turnLensAddress}>{view.aggregateSha256}</dd>
      </dl>
      {view.truncated ? (
        <p className={styles.turnLensNote} role="note">
          Some bodies exceeded this response&rsquo;s{" "}
          {view.budgetBytes.toLocaleString()}-byte budget and were withheld whole,
          not shortened.
        </p>
      ) : null}
      {view.layers.map((layer) => (
        <details className={styles.turnLensLayer} key={layer.ordinal}>
          <summary>
            <span>{layerLabel(layer.layer)}</span>
            <span className={styles.turnLensMeter} role="presentation">
              <span
                style={{
                  width: `${Math.round(
                    budgetRatio(layer.tokenCount, layer.tokenBudget) * 100,
                  )}%`,
                }}
              />
            </span>
            <span className={styles.turnLensCount}>
              {layer.tokenCount.toLocaleString()} /{" "}
              {layer.tokenBudget.toLocaleString()} tokens
              {layer.excludedCount > 0 ? ` · ${layer.excludedCount} dropped` : ""}
            </span>
          </summary>
          {layer.refs.length === 0 ? (
            <p className={styles.turnLensNote}>No pointers recorded for this layer.</p>
          ) : (
            layer.refs.map((ref) => (
              <div
                className={styles.turnLensRef}
                data-disposition={ref.disposition}
                key={`${ref.disposition}:${ref.ordinal}`}
              >
                <p className={styles.turnLensRefHead}>
                  {ref.disposition === "included" ? "Included" : "Dropped"}
                  {ref.materializedPath ? ` · ${ref.materializedPath}` : ""}
                  {ref.objectType ? ` · ${ref.objectType}:${ref.objectId}` : ""}
                  {ref.tokenCount !== null ? ` · ${ref.tokenCount} tokens` : ""}
                </p>
                {ref.exclusionReasonCode ? (
                  <p className={styles.turnLensNote}>
                    Dropped by the assembler: {ref.exclusionReasonCode}
                  </p>
                ) : null}
                {ref.body ? <BodyView body={ref.body} /> : null}
              </div>
            ))
          )}
        </details>
      ))}
    </div>
  );
}

function RoundsTab({ rounds }: { rounds: readonly ChatInspectorRound[] }) {
  if (rounds.length === 0) {
    return (
      <p className={styles.turnLensNote} role="note">
        No governed model call was recorded for this turn.
      </p>
    );
  }
  return (
    <div className={styles.turnLensSection}>
      {rounds.map((round) => (
        <div className={styles.turnLensRow} key={round.modelCallId}>
          <p className={styles.turnLensRefHead}>
            Round {round.sequence} · {round.status}
          </p>
          <dl className={styles.turnLensMeta}>
            <dt>Requested</dt>
            <dd>{round.requestedModel}</dd>
            <dt>Answered by</dt>
            {/* The two differ whenever the gateway's fallback fired. Showing one
                only would turn "we asked for X" into "we called X". */}
            <dd>{round.answeringModel ?? "—"}</dd>
            <dt>Tokens</dt>
            <dd>
              {round.inputTokens.toLocaleString()} in ·{" "}
              {round.outputTokens.toLocaleString()} out
            </dd>
            <dt>Cost</dt>
            <dd>{round.costMillicredits.toLocaleString()} millicredits</dd>
            <dt>Latency</dt>
            <dd>{Math.round(round.latencyMs).toLocaleString()} ms</dd>
            {round.errorCode ? (
              <>
                <dt>Error</dt>
                <dd>{round.errorCode}</dd>
              </>
            ) : null}
          </dl>
        </div>
      ))}
    </div>
  );
}

function PlanTab({ view }: { view: ChatInspectorPlanView | null }) {
  if (view === null) return null;
  return (
    <div className={styles.turnLensSection}>
      {view.plans.length === 0 ? (
        <p className={styles.turnLensNote} role="note">
          No plan was validated in this turn.
        </p>
      ) : (
        view.plans.map((plan) => (
          <div className={styles.turnLensRow} key={plan.planId}>
            <p className={styles.turnLensRefHead}>
              {plan.role} · {plan.estimatedCostMillicents.toLocaleString()} of{" "}
              {plan.budgetLimitMillicents.toLocaleString()} millicents
            </p>
            <h4 className={styles.turnLensSubhead}>Authored</h4>
            <BodyView body={plan.proposal} />
            <h4 className={styles.turnLensSubhead}>Admitted</h4>
            <BodyView body={plan.validated} />
            <ul className={styles.turnLensList}>
              {plan.operations.map((operation) => (
                <li key={operation.nodeKey}>
                  {operation.address} · {operation.validation} ·{" "}
                  {operation.estimatedCostMillicents.toLocaleString()} millicents
                </li>
              ))}
            </ul>
            <ul className={styles.turnLensList}>
              {plan.events.map((event, index) => (
                <li key={`${event.status}:${index}`}>
                  {event.status}
                  {event.reasonCode ? ` · ${event.reasonCode}` : ""}
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
      <div className={styles.turnLensRow}>
        <p className={styles.turnLensRefHead}>Turn ledger</p>
        {/* A plan the validator rejects is never journaled, so it has no
            per-operation verdict. Its refusal is here, and saying so is more
            honest than manufacturing a "refused operation" row from it. */}
        <p className={styles.turnLensNote}>
          A plan refused at validation writes no plan row; its refusal appears here.
        </p>
        <ul className={styles.turnLensList}>
          {view.turnEvents.map((event, index) => (
            <li key={`${event.status}:${index}`}>
              {event.status}
              {event.reasonCode ? ` · ${event.reasonCode}` : ""}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function ToolsTab({ view }: { view: ChatInspectorToolsView | null }) {
  if (view === null) return null;
  if (view.calls.length === 0) {
    return (
      <p className={styles.turnLensNote} role="note">
        No governed operation was admitted in this turn.
      </p>
    );
  }
  return (
    <div className={styles.turnLensSection}>
      {view.calls.map((call) => (
        <div className={styles.turnLensRow} key={call.operationId}>
          <p className={styles.turnLensRefHead}>
            {call.address} · {call.nodeKey}
          </p>
          <h4 className={styles.turnLensSubhead}>Arguments</h4>
          <BodyView body={call.arguments} />
          <h4 className={styles.turnLensSubhead}>Receipt</h4>
          {call.result ? (
            <>
              <BodyView body={call.result} />
              <p className={styles.turnLensNote}>
                {call.replayed ? "Replayed" : "Executed"} ·{" "}
                {call.referenceCount ?? 0} reference
                {call.referenceCount === 1 ? "" : "s"}
              </p>
            </>
          ) : (
            <p className={styles.turnLensNote} role="note">
              Admitted, and never completed — no receipt was written.
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

export default function ChatTurnInspectorPanel({
  inspector,
}: {
  inspector: TurnInspectorController;
}) {
  const { data, error, tab, turnId } = inspector;
  if (turnId === null) return null;

  return (
    <aside aria-label="Turn inspector" className={styles.turnLensPanel}>
      <header className={styles.turnLensHeader}>
        <div>
          <p className={styles.turnLensRefHead}>Turn inspector</p>
          <p className={styles.turnLensAddress}>{turnId}</p>
        </div>
        <button aria-label="Close inspector" onClick={inspector.close} type="button">
          <ProjectIcon name="close" size={12} />
        </button>
      </header>
      <nav className={styles.turnLensTabs} role="tablist">
        {INSPECTOR_TABS.map((name) => (
          <button
            aria-selected={name === tab}
            data-active={name === tab || undefined}
            key={name}
            onClick={() => inspector.setTab(name)}
            role="tab"
            type="button"
          >
            {TAB_LABELS[name]}
          </button>
        ))}
      </nav>
      <div className={styles.turnLensContent} role="tabpanel">
        {error ? (
          <p className={styles.turnLensNote} role="note">
            {error}
          </p>
        ) : data === undefined ? (
          <p className={styles.turnLensNote}>Reading receipts…</p>
        ) : tab === "context" ? (
          <ContextTab view={data.context ?? null} />
        ) : tab === "rounds" ? (
          <RoundsTab rounds={data.rounds ?? []} />
        ) : tab === "plan" ? (
          <PlanTab view={data.plan ?? null} />
        ) : (
          <ToolsTab view={data.tools ?? null} />
        )}
      </div>
    </aside>
  );
}
