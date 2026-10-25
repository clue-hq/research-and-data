"use client";

import Image from "next/image";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import {
  CLUE_FIELDS_SETUP_KIND,
  allowLabel,
  answeredLine,
  countsLine,
  crmWriteAnswer,
  crmWriteCardView,
  crmWriteGroupOutcome,
  crmWriteRecordsCaption,
  groupTickState,
  initialSelection,
  pausedCaption,
  selectedCount,
  sendingTitle,
  toggleGroup,
  toggleRecord,
  type CrmProposalProgress,
  type CrmWriteCardModel,
  type CrmWriteGroup,
  type CrmWriteSelection,
} from "@/features/integrations/model/crm-write";
import type { GateCardModel, GateDecisionInput } from "../model/chat-gate";
import { useCrmProposalProgress } from "../hooks/use-crm-proposal-progress";
import { ProjectIcon } from "./project-icon";
import frame from "./crm-connect-card.module.css";
import styles from "./crm-write-permission-card.module.css";

/**
 * The CRM write permission card (CRM integration Phase 2; card spec
 * docs/superpowers/specs/crm-integration/2026-10-22-crm-write-permission-card-design.md).
 *
 * Drawn from the durable gate (what was proposed, whether and how it was answered, whether a newer
 * card replaced it) and, once answered, from the proposal's progress, which it re-reads every
 * 2 s while the CRM is being written to. Six states: asking, sending, done, not allowed, replaced
 * (or closed by a reconnect), and paused. Any member of the workspace can answer (R-6.8);
 * "Don't allow" sends nothing to the CRM.
 */

const PROVIDER_LOGOS = {
  hubspot: { src: "/icons/crm/hubspot.svg", width: 20, height: 20 },
  salesforce: { src: "/icons/crm/salesforce.svg", width: 20, height: 14 },
} as const;

const FILTER_FROM = 20;

export function CrmWritePermissionCard({
  busy,
  card,
  onDecide,
  wake = 0,
}: {
  busy: boolean;
  card: GateCardModel;
  onDecide: (card: GateCardModel, input: GateDecisionInput) => void;
  /** The chat's count of "changes finished" wake-ups: the card re-reads when it moves (R-12.18). */
  wake?: number;
}) {
  const write = card.crmWrite;
  const answeredOrClosed = card.state !== "requested";
  const progress = useCrmProposalProgress(card.crmProposalId, answeredOrClosed, wake);
  if (write === null) return null;
  const gateState =
    card.state === "responded" || card.state === "denied" || card.state === "withdrawn"
      ? card.state
      : "requested";
  const view = crmWriteCardView(gateState, progress);

  switch (view) {
    case "asking":
      return <AskingCard busy={busy} card={card} write={write} onDecide={onDecide} />;
    case "sending":
      return <SendingCard progress={progress} write={write} />;
    case "done":
      return <DoneCard progress={progress} write={write} />;
    case "paused":
      return <PausedCard progress={progress} write={write} />;
    case "declined":
      return (
        <ClosedCard
          label="You didn't allow these changes"
          state="declined"
          detail={answeredLine("Declined", progress?.answeredByName ?? null, progress?.answeredAt ?? card.answeredAt)}
          write={write}
        />
      );
    case "replaced":
      return <ClosedCard label="Replaced by a newer proposal" state="replaced" detail={null} write={write} />;
    case "closed":
      return (
        <ClosedCard
          label="These changes were not sent"
          state="closed"
          detail={`${write.providerName} was reconnected or switched first. Clue will propose them again.`}
          write={write}
        />
      );
  }
}

// --- A. asking ------------------------------------------------------------

function AskingCard({
  busy,
  card,
  write,
  onDecide,
}: {
  busy: boolean;
  card: GateCardModel;
  write: CrmWriteCardModel;
  onDecide: (card: GateCardModel, input: GateDecisionInput) => void;
}) {
  const [selection, setSelection] = useState<CrmWriteSelection>(() => initialSelection(write));
  const [alwaysAllow, setAlwaysAllow] = useState<ReadonlySet<string>>(() => new Set());
  const count = selectedCount(selection);
  const canAllow = card.permittedDecisions.includes("approved");
  const canDecline = card.permittedDecisions.includes("rejected");
  // Setting up Clue's own fields is one change: "Allow", never "Allow 1".
  const setup = write.groups.some((group) => group.kind === CLUE_FIELDS_SETUP_KIND);

  function toggleAlwaysAllow(scopeKey: string) {
    setAlwaysAllow((current) => {
      const next = new Set(current);
      if (next.has(scopeKey)) next.delete(scopeKey);
      else next.add(scopeKey);
      return next;
    });
  }

  return (
    <section className={frame.card} data-crm-write-state="asking" aria-label={write.title}>
      <Header title={write.title} description={write.description} icon={<ProviderLogo write={write} />} />
      {write.groups.map((group, index) =>
        group.kind === CLUE_FIELDS_SETUP_KIND ? (
          <SetupGroup group={group} key={`setup:${index}`} />
        ) : (
          <GroupLine
            disabled={busy}
            group={group}
            key={`${group.alwaysAllowPhrase}:${index}`}
            selection={selection}
            onToggleGroup={() => setSelection((current) => toggleGroup(current, group))}
            onToggleRecord={(writeId) => setSelection((current) => toggleRecord(current, writeId))}
          />
        ),
      )}
      {write.overwritesHeading ? (
        <div className={styles.section}>
          <p className={styles.warning}>
            <span aria-hidden="true">⚠ </span>
            {write.overwritesHeading}
          </p>
          {write.overwrites.map((item) => (
            <label className={styles.row} key={item.writeId}>
              <input
                checked={selection.has(item.writeId)}
                disabled={busy}
                onChange={() => setSelection((current) => toggleRecord(current, item.writeId))}
                type="checkbox"
              />
              <span className={styles.rowBody}>
                <span className={styles.rowText}>{item.line}</span>
                <span className={frame.caption}>{item.setByText}</span>
                {item.reason ? <Reason text={item.reason} /> : null}
              </span>
            </label>
          ))}
        </div>
      ) : null}
      {write.standingPermissions.length > 0 ? (
        <div className={styles.section}>
          {write.standingPermissions.map((permission) => (
            <label className={styles.row} key={permission.scopeKey}>
              <input
                checked={alwaysAllow.has(permission.scopeKey)}
                disabled={busy}
                onChange={() => toggleAlwaysAllow(permission.scopeKey)}
                type="checkbox"
              />
              <span className={styles.rowText}>{permission.label}</span>
            </label>
          ))}
        </div>
      ) : null}
      <div className={frame.guidance}>
        {card.problem ? (
          <p className={`${frame.caption} ${frame.note} ${frame.alert}`} role="alert">
            {card.problem}
          </p>
        ) : null}
        <div className={frame.actions}>
          <p className={frame.caption}>{write.caption}</p>
          <div className={styles.row}>
            {canDecline ? (
              <Button
                size="md"
                variant="transparent"
                disabled={busy}
                onClick={() => onDecide(card, { kind: "decision", decision: "rejected" })}
              >
                Don&apos;t allow
              </Button>
            ) : null}
            {canAllow ? (
              <Button
                size="md"
                variant="primary"
                disabled={busy || count === 0}
                onClick={() =>
                  onDecide(card, {
                    kind: "crm_write",
                    decision: "approved",
                    answer: crmWriteAnswer(write, selection, alwaysAllow),
                  })
                }
              >
                {setup ? "Allow" : allowLabel(count)}
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}

function GroupLine({
  disabled,
  group,
  selection,
  onToggleGroup,
  onToggleRecord,
}: {
  disabled: boolean;
  group: CrmWriteGroup;
  selection: CrmWriteSelection;
  onToggleGroup: () => void;
  onToggleRecord: (writeId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const tick = groupTickState(group, selection);
  return (
    <div className={styles.group}>
      <div className={styles.row}>
        <input
          aria-checked={tick === "some" ? "mixed" : tick === "all"}
          checked={tick === "all"}
          disabled={disabled}
          onChange={onToggleGroup}
          ref={(input) => {
            if (input) input.indeterminate = tick === "some";
          }}
          type="checkbox"
          aria-label={group.title}
        />
        <div className={styles.rowBody}>
          <p className={styles.rowTitle}>{group.title}</p>
          {group.valueSummary ? <p className={frame.caption}>{group.valueSummary}</p> : null}
          {group.reason ? <Reason text={group.reason} /> : null}
        </div>
        <Chevron open={open} label={group.title} onToggle={() => setOpen((value) => !value)} />
      </div>
      {open ? (
        <Records group={group}>
          {(record) => (
            <label className={styles.row}>
              <input
                checked={selection.has(record.writeId)}
                disabled={disabled}
                onChange={() => onToggleRecord(record.writeId)}
                type="checkbox"
              />
              <span className={styles.rowBody}>
                <span className={styles.rowText}>{record.name}</span>
                {record.change ? <span className={frame.caption}>{record.change}</span> : null}
              </span>
            </label>
          )}
        </Records>
      ) : null}
    </div>
  );
}

/**
 * Setting up Clue's own fields (Phase 4): every field it creates and what else changes in the CRM,
 * always shown; there is one change, so nothing to tick or open.
 */
function SetupGroup({ group }: { group: CrmWriteGroup }) {
  return (
    <div className={styles.group}>
      <div className={styles.rowBody}>
        <p className={styles.rowTitle}>{group.title}</p>
        <ul className={styles.recordList}>
          {group.setupFields.map((field) => (
            <li className={styles.rowText} key={`${field.object}:${field.label}`}>
              {`${field.object} · ${field.label}`}
              <span className={frame.caption}>{` (${field.type})`}</span>
            </li>
          ))}
        </ul>
        {group.setupNotes.map((note) => (
          <p className={frame.caption} key={note}>
            {note}
          </p>
        ))}
        {group.reason ? <Reason text={group.reason} /> : null}
      </div>
    </div>
  );
}

/** An opened group's records: a caption, a filter past 20 records, a list that scrolls. */
function Records({
  group,
  children,
}: {
  group: CrmWriteGroup;
  children: (record: CrmWriteGroup["records"][number]) => ReactNode;
}) {
  const [filter, setFilter] = useState("");
  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? group.records.filter((record) => record.name.toLowerCase().includes(needle))
    : group.records;
  return (
    <div className={styles.records}>
      <p className={frame.caption}>{crmWriteRecordsCaption(group)}</p>
      {group.records.length > FILTER_FROM ? (
        <input
          aria-label="Filter records"
          className={styles.filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter"
          type="search"
          value={filter}
        />
      ) : null}
      <ul className={styles.recordList}>
        {shown.map((record) => (
          <li key={record.writeId}>{children(record)}</li>
        ))}
      </ul>
    </div>
  );
}

function Reason({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const long = text.length > 140;
  return (
    <>
      <p className={`${frame.caption} ${styles.reason}`} data-expanded={expanded || undefined}>
        Why: {text}
      </p>
      {long && !expanded ? (
        <button className={styles.linkButton} onClick={() => setExpanded(true)} type="button">
          more
        </button>
      ) : null}
    </>
  );
}

function Chevron({ open, label, onToggle }: { open: boolean; label: string; onToggle: () => void }) {
  return (
    <button
      aria-expanded={open}
      aria-label={open ? `Hide the records of: ${label}` : `Show the records of: ${label}`}
      className={styles.chevron}
      onClick={onToggle}
      type="button"
    >
      <ProjectIcon name="chevron-right" size={14} />
    </button>
  );
}

// --- B. sending -----------------------------------------------------------

function totalOf(progress: CrmProposalProgress | null): number {
  if (progress === null) return 0;
  const { done, failed, skipped, pending } = progress.counts;
  return done + failed + skipped + pending;
}

function answeredOf(progress: CrmProposalProgress | null): number {
  if (progress === null) return 0;
  const { done, failed, skipped } = progress.counts;
  return done + failed + skipped;
}

function SendingCard({ progress, write }: { progress: CrmProposalProgress | null; write: CrmWriteCardModel }) {
  const total = totalOf(progress);
  const answered = answeredOf(progress);
  const title = total > 0 ? sendingTitle(write.provider, total) : `Sending changes to ${write.providerName}`;
  return (
    <section className={frame.card} data-crm-write-state="sending" aria-label={title}>
      <Header
        title={title}
        description={answeredLine("Allowed", progress?.answeredByName ?? null, progress?.answeredAt ?? null)}
        icon={
          <Image alt="" aria-hidden="true" className={frame.spinning} height={20} src="/icons/crm/spinner.svg" width={20} />
        }
      />
      {total > 0 ? (
        <div className={styles.progress} role="status">
          <div
            aria-label={`${answered} of ${total}`}
            aria-valuemax={total}
            aria-valuemin={0}
            aria-valuenow={answered}
            className={styles.progressBar}
            role="progressbar"
          >
            <div className={styles.progressFill} style={{ width: `${(answered / total) * 100}%` }} />
          </div>
          <span className={frame.caption}>{`${answered} of ${total}`}</span>
        </div>
      ) : null}
      <p className={frame.caption}>Clue carries on in this chat when it&apos;s done.</p>
    </section>
  );
}

// --- C. done --------------------------------------------------------------

function DoneCard({ progress, write }: { progress: CrmProposalProgress | null; write: CrmWriteCardModel }) {
  const counts = progress?.counts ?? { done: 0, failed: 0, skipped: 0, pending: 0 };
  const anyFailed = counts.failed > 0;
  const title = `Changes sent to ${write.providerName}`;
  const skippedByReason = new Map<string, number>();
  for (const item of progress?.skipped ?? []) {
    const reason = item.reason ?? "not sent";
    skippedByReason.set(reason, (skippedByReason.get(reason) ?? 0) + 1);
  }
  return (
    <section className={frame.card} data-crm-write-state="done" aria-label={title}>
      <Header
        title={title}
        description={answeredLine("Allowed", progress?.answeredByName ?? null, progress?.answeredAt ?? null)}
        icon={anyFailed ? <WarningGlyph /> : <Image alt="" aria-hidden="true" height={20} src="/icons/crm/check-header.svg" width={20} />}
        tile={anyFailed ? "warning" : "brand"}
      />
      <p className={styles.rowText}>{countsLine(counts)}</p>
      <ul className={styles.outcome}>
        {write.groups.map((group, index) => {
          const tally = progress?.groups[index];
          if (!tally || tally.chosen === 0) return null;
          const outcome = crmWriteGroupOutcome(write.provider, group, tally);
          return (
            <OutcomeGroup
              group={group}
              key={`${group.alwaysAllowPhrase}:${index}`}
              line={outcome.line}
              mark={outcome.mark}
            />
          );
        })}
        {anyFailed ? (
          <li className={styles.row}>
            <Mark kind="failed" />
            <div className={styles.rowBody}>
              <p className={styles.rowText}>{`${counts.failed} failed`}</p>
              {(progress?.failed ?? []).map((item) => (
                <p className={frame.caption} key={item.writeId}>
                  {`${item.label ?? "A record"}${item.field ? ` · ${item.field}` : ""}`}
                  {item.crmMessage ? ` — ${write.providerName}: "${item.crmMessage}"` : ""}
                </p>
              ))}
            </div>
          </li>
        ) : null}
        {[...skippedByReason].map(([reason, count]) => (
          <li className={styles.row} key={reason}>
            <Mark kind="skipped" />
            <p className={styles.rowText}>{`${count} skipped: ${reason}`}</p>
          </li>
        ))}
      </ul>
      {anyFailed ? <p className={frame.caption}>Clue will fix the failed ones with you in this chat.</p> : null}
    </section>
  );
}

function OutcomeGroup({
  group,
  line,
  mark,
}: {
  group: CrmWriteGroup;
  line: string;
  mark: "done" | "failed";
}) {
  const [open, setOpen] = useState(false);
  return (
    <li className={styles.group}>
      <div className={styles.row}>
        <Mark kind={mark} />
        <p className={`${styles.rowText} ${styles.rowBody}`}>{line}</p>
        <Chevron open={open} label={line} onToggle={() => setOpen((value) => !value)} />
      </div>
      {open ? (
        <Records group={group}>
          {(record) => <span className={styles.rowText}>{record.name}</span>}
        </Records>
      ) : null}
    </li>
  );
}

function Mark({ kind }: { kind: "done" | "failed" | "skipped" }) {
  return (
    <span aria-hidden="true" className={styles.mark} data-mark={kind}>
      {kind === "done" ? "✓" : kind === "failed" ? "✕" : "–"}
    </span>
  );
}

// --- F. paused ------------------------------------------------------------

function PausedCard({ progress, write }: { progress: CrmProposalProgress | null; write: CrmWriteCardModel }) {
  const title = `Paused — ${write.providerName} needs to be reconnected`;
  return (
    <section className={frame.card} data-crm-write-state="paused" aria-label={title}>
      <Header
        title={title}
        description={answeredLine("Allowed", progress?.answeredByName ?? null, progress?.answeredAt ?? null)}
        icon={<WarningGlyph />}
        tile="warning"
      />
      {progress ? <p className={styles.rowText}>{`${countsLine(progress.counts)} so far`}</p> : null}
      <div className={frame.actions}>
        <p className={frame.caption}>{pausedCaption(write.providerName)}</p>
        <Link className={styles.linkButton} href="/settings/integrations">
          Reconnect {write.providerName}
        </Link>
      </div>
    </section>
  );
}

// --- D/E. not allowed, replaced, closed -----------------------------------

function ClosedCard({
  label,
  state,
  detail,
  write,
}: {
  label: string;
  state: "declined" | "replaced" | "closed";
  detail: string | null;
  write: CrmWriteCardModel;
}) {
  return (
    <section className={frame.card} data-crm-write-state={state} aria-label={label}>
      <Header title={label} description={detail} icon={<ProjectIcon name="close" size={20} />} tile="muted" />
      {state === "declined" ? (
        <ul className={styles.outcome}>
          {write.groups.map((group, index) => (
            <OutcomeProposed group={group} key={`${group.alwaysAllowPhrase}:${index}`} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/** A declined card's groups can still be opened to see what was proposed. */
function OutcomeProposed({ group }: { group: CrmWriteGroup }) {
  const [open, setOpen] = useState(false);
  return (
    <li className={styles.group}>
      <div className={styles.row}>
        <p className={`${styles.rowText} ${styles.rowBody}`}>{group.title}</p>
        <Chevron open={open} label={group.title} onToggle={() => setOpen((value) => !value)} />
      </div>
      {open ? (
        <Records group={group}>
          {(record) => <span className={styles.rowText}>{record.name}</span>}
        </Records>
      ) : null}
    </li>
  );
}

// --- shared parts -----------------------------------------------------------

function Header({
  title,
  description,
  icon,
  tile = "brand",
}: {
  title: string;
  description: string | null;
  icon: ReactNode;
  tile?: "brand" | "muted" | "warning";
}) {
  const tileClass =
    tile === "muted" ? styles.symbolMuted : tile === "warning" ? styles.symbolWarning : "";
  return (
    <div className={frame.header}>
      <div className={`${frame.symbol} ${tileClass}`}>{icon}</div>
      <div className={frame.heading}>
        <h3 className={frame.title}>{title}</h3>
        {description ? <p className={frame.description}>{description}</p> : null}
      </div>
    </div>
  );
}

function ProviderLogo({ write }: { write: CrmWriteCardModel }) {
  const logo = PROVIDER_LOGOS[write.provider];
  return <Image alt="" aria-hidden="true" height={logo.height} src={logo.src} width={logo.width} />;
}

function WarningGlyph() {
  return <span aria-hidden="true">⚠</span>;
}
