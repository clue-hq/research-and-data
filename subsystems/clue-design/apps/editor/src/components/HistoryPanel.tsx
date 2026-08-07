import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, CircleUserRound, Redo2, RefreshCw, Undo2, X } from "lucide-react";

import {
  fetchHistory,
  redoDocument,
  undoDocument,
  type HistoryEnvelope
} from "../engine/structuredEdits";

/**
 * Version history as a floating dialog (moda's "Version history" window, our
 * skin): committed edit envelopes grouped by day, newest first, with the
 * document-level undo/redo the API actually supports. Renders persisted
 * truth — no client-side restore affordances the server doesn't offer.
 */
export function VersionHistoryDialog({
  apiBaseUrl,
  documentId,
  onClose,
  onDocumentChanged
}: {
  apiBaseUrl: string;
  documentId: string;
  onClose: () => void;
  onDocumentChanged?: () => void;
}) {
  const [envelopes, setEnvelopes] = useState<HistoryEnvelope[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setEnvelopes(await fetchHistory(apiBaseUrl, documentId, 50));
      setError(null);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : String(fetchError));
    }
  }, [apiBaseUrl, documentId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const runHistoryAction = useCallback(
    async (action: (apiBaseUrl: string, documentId: string) => Promise<unknown>) => {
      setBusy(true);
      try {
        await action(apiBaseUrl, documentId);
        await refresh();
        onDocumentChanged?.();
        setError(null);
      } catch (actionError) {
        setError(actionError instanceof Error ? actionError.message : String(actionError));
      } finally {
        setBusy(false);
      }
    },
    [apiBaseUrl, documentId, onDocumentChanged, refresh]
  );

  // Newest first, grouped by calendar day of created_at.
  const dayGroups = useMemo(() => groupByDay(envelopes), [envelopes]);

  return (
    <div className="version-history-overlay" onClick={onClose}>
      <div
        className="version-history-dialog"
        role="dialog"
        aria-label="Version history"
        data-testid="version-history-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="version-history-head">
          <div>
            <h2>Version history</h2>
            <p>Committed edits on this document, newest first.</p>
          </div>
          <button
            type="button"
            className="icon-ghost-button"
            aria-label="Close version history"
            onClick={onClose}
          >
            <X aria-hidden size={16} />
          </button>
        </header>
        <div className="version-history-actions">
          <button
            type="button"
            disabled={busy}
            onClick={() => void runHistoryAction(undoDocument)}
          >
            <Undo2 aria-hidden size={14} />
            Undo last
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void runHistoryAction(redoDocument)}
          >
            <Redo2 aria-hidden size={14} />
            Redo
          </button>
          <button type="button" disabled={busy} onClick={() => void refresh()}>
            <RefreshCw aria-hidden size={14} />
            Refresh
          </button>
        </div>
        <div className="version-history-body">
          {error ? <p className="muted">{error}</p> : null}
          {envelopes.length === 0 && !error ? (
            <p className="muted">No committed edits yet.</p>
          ) : (
            dayGroups.map((group) => (
              <section key={group.day} className="version-history-day">
                <h3>{group.day}</h3>
                <ol>
                  {group.entries.map((envelope, index) => (
                    <li key={envelope.batch_id} className="version-history-row">
                      <span className="version-history-actor" aria-hidden>
                        {envelope.actor?.kind === "agent" ? (
                          <Bot size={15} />
                        ) : (
                          <CircleUserRound size={15} />
                        )}
                      </span>
                      <div className="version-history-detail">
                        <span className="version-history-intent">
                          {envelope.intent ?? "Edit (pre-envelope)"}
                          {group.day === dayGroups[0]?.day && index === 0 ? (
                            <em className="version-history-current">Current</em>
                          ) : null}
                        </span>
                        <span className="version-history-meta">
                          {envelope.actor?.kind ?? "unknown"}
                          {" · "}
                          {timeOfDay(envelope.created_at)}
                          {envelope.checkpoint_label ? (
                            <>
                              {" · "}
                              <code>{envelope.checkpoint_label}</code>
                            </>
                          ) : null}
                          {envelope.inverse_operations ? null : " · not undoable"}
                        </span>
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

interface DayGroup {
  day: string;
  entries: HistoryEnvelope[];
}

function groupByDay(envelopes: HistoryEnvelope[]): DayGroup[] {
  const newestFirst = [...envelopes].sort((a, b) => b.seq - a.seq);
  const groups: DayGroup[] = [];
  for (const envelope of newestFirst) {
    const day = dayLabel(envelope.created_at);
    const last = groups[groups.length - 1];
    if (last && last.day === day) {
      last.entries.push(envelope);
    } else {
      groups.push({ day, entries: [envelope] });
    }
  }
  return groups;
}

function dayLabel(createdAt: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) {
    return "Undated";
  }
  return date.toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric"
  });
}

function timeOfDay(createdAt: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) {
    return "unknown time";
  }
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}
