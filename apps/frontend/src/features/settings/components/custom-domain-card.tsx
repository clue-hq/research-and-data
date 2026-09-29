// Built from spec §8.2 pending the co-founder's frames (2026-09-18); re-lift when they land.
"use client";

import { Check } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

import {
  connectionView,
  stepIndex,
  STATUS_STEPS,
  type CustomHostname,
  type HostnameStatus,
} from "../model/pages";
import styles from "./settings.module.css";
import { SectionLead, SettingsCard } from "./settings-primitives";

const STEP_LABELS: Record<(typeof STATUS_STEPS)[number], string> = {
  pending_dns: "Waiting for DNS",
  verifying_ownership: "Verifying ownership",
  issuing_certificate: "Issuing certificate",
  active: "Active",
};

/** Spec §7.5 error lines; an unlisted code falls through to the provider's detail text. */
const ERROR_LINES: Record<string, string> = {
  cname_incorrect: "Your CNAME points somewhere else.",
  txt_missing: "The ownership TXT record hasn't appeared.",
  caa_blocked: "A CAA record blocks certificate issuance.",
  hostname_taken: "This hostname is already connected to a workspace.",
  verification_expired: "Verification expired. Check now to start it again.",
};

function errorLine(error: CustomHostname["error"]): string | null {
  if (!error) return null;
  return ERROR_LINES[error.code] ?? error.detail ?? "The hosting provider refused this hostname.";
}

function DnsRecordTable({ custom }: { custom: CustomHostname }) {
  return (
    <div className={styles.fieldTableFrame}>
      <table className={styles.fieldTable}>
        <thead>
          <tr>
            <th scope="col">Type</th>
            <th scope="col">Name</th>
            <th scope="col">Required value</th>
            <th scope="col">Observed value</th>
            <th scope="col">
              <span className="sr-only">Matches</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {custom.records.map((record) => (
            <tr key={`${record.type}:${record.name}`}>
              <td>{record.type}</td>
              <td>{record.name}</td>
              <td>{record.required}</td>
              <td>{record.observed ?? "—"}</td>
              <td>
                {record.ok ? (
                  <Check aria-label="Matches" size={14} strokeWidth={1.5} />
                ) : (
                  <span aria-label="Does not match yet">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StatusStepper({ status }: { status: HostnameStatus }) {
  const current = stepIndex(status);
  return (
    <ol className="flex flex-wrap gap-4">
      {STATUS_STEPS.map((step, index) => (
        <li
          aria-current={index === current ? "step" : undefined}
          className={index === current ? undefined : styles.mutedText}
          key={step}
        >
          {STEP_LABELS[step]}
        </li>
      ))}
    </ol>
  );
}

function NotConnected({
  canManage,
  busy,
  onConnect,
  refusal,
}: {
  canManage: boolean;
  busy: boolean;
  onConnect: (hostname: string) => void;
  refusal: string | null;
}) {
  const [hostname, setHostname] = useState("");
  if (!canManage) {
    return <p className={styles.mutedText}>No custom domain is connected.</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start gap-2">
        <input
          aria-label="Custom domain"
          className={styles.input}
          onChange={(event) => setHostname(event.target.value)}
          placeholder="go.acme.com"
          value={hostname}
        />
        <Button
          disabled={busy || hostname.trim() === ""}
          onClick={() => onConnect(hostname.trim())}
          size="md"
          variant="secondary"
        >
          Connect
        </Button>
      </div>
      <p className={styles.mutedText}>Use a dedicated subdomain such as go.acme.com</p>
      {refusal ? (
        <p className={styles.mutedText} role="alert">
          {refusal}
        </p>
      ) : null}
    </div>
  );
}

function Provisioning({
  canManage,
  busy,
  custom,
  onCheck,
}: {
  canManage: boolean;
  busy: boolean;
  custom: CustomHostname;
  onCheck: () => void;
}) {
  const line = errorLine(custom.error);
  return (
    <div className="flex flex-col gap-3">
      <DnsRecordTable custom={custom} />
      <StatusStepper status={custom.status} />
      {custom.status === "disconnecting" ? (
        <p className={styles.mutedText}>Removing… Check now retries.</p>
      ) : null}
      {line ? (
        <p className={styles.mutedText} role="alert">
          {line}
        </p>
      ) : null}
      <p className={styles.mutedText}>DNS changes can take up to 48 hours</p>
      {canManage ? (
        <div>
          <Button disabled={busy} onClick={onCheck} size="sm" variant="secondary">
            Check now
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function Active({
  canManage,
  busy,
  custom,
  onRemove,
}: {
  canManage: boolean;
  busy: boolean;
  custom: CustomHostname;
  onRemove: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className={styles.statusDot} />
        <span>{custom.hostname}</span>
      </div>
      <div className="flex items-center gap-2">
        {custom.url ? (
          <a href={custom.url} rel="noreferrer" target="_blank">
            Open
          </a>
        ) : null}
        {canManage && !confirming ? (
          <Button onClick={() => setConfirming(true)} size="sm" variant="secondary">
            Remove
          </Button>
        ) : null}
      </div>
      {confirming ? (
        <div className="flex flex-col gap-2">
          <p className={styles.mutedText}>
            Remove {custom.hostname}? Your Clue address keeps working.
          </p>
          <div className="flex items-center gap-2">
            <Button
              disabled={busy}
              onClick={() => {
                setConfirming(false);
                onRemove();
              }}
              size="sm"
              variant="secondary"
            >
              Confirm
            </Button>
            <Button onClick={() => setConfirming(false)} size="sm" variant="ghost">
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function CustomDomainCard({
  busy,
  canManage,
  custom,
  onCheck,
  onConnect,
  onRemove,
  refusal,
}: {
  busy: boolean;
  canManage: boolean;
  custom: CustomHostname | null;
  onCheck: () => void;
  onConnect: (hostname: string) => void;
  onRemove: () => void;
  refusal: string | null;
}) {
  const view = connectionView(custom);
  return (
    <section className={styles.connectionSection}>
      <SectionLead description="Host your site on your own domain">Custom domain</SectionLead>
      <SettingsCard className="p-4">
        {view === "not_connected" || !custom ? (
          <NotConnected
            busy={busy}
            canManage={canManage}
            onConnect={onConnect}
            refusal={refusal}
          />
        ) : view === "active" ? (
          <Active busy={busy} canManage={canManage} custom={custom} onRemove={onRemove} />
        ) : (
          <Provisioning busy={busy} canManage={canManage} custom={custom} onCheck={onCheck} />
        )}
      </SettingsCard>
    </section>
  );
}
