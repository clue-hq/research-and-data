import { useCallback, useEffect, useState } from "react";
import { History } from "lucide-react";

import {
  fetchHistory,
  redoDocument,
  undoDocument,
  type HistoryEnvelope
} from "../engine/structuredEdits";

/**
 * Committed document history: renders persisted edit envelopes (intent,
 * checkpoint label, actor, invertibility) and drives the append-only
 * document-level undo/redo API. The local optimistic gesture stack stays in
 * OperationHistoryPanel; this panel is the durable, server-side truth.
 */
export function HistoryPanel({
  apiBaseUrl,
  documentId,
  onDocumentChanged
}: {
  apiBaseUrl: string;
  documentId: string;
  onDocumentChanged?: () => void;
}) {
  const [envelopes, setEnvelopes] = useState<HistoryEnvelope[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setEnvelopes(await fetchHistory(apiBaseUrl, documentId, 12));
      setError(null);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : String(fetchError));
    }
  }, [apiBaseUrl, documentId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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

  return (
    <section className="inspector-section" data-testid="history-panel">
      <div className="section-heading">
        <History aria-hidden size={15} />
        Document history
      </div>
      <div className="history-actions">
        <button
          type="button"
          disabled={busy}
          onClick={() => void runHistoryAction(undoDocument)}
        >
          Undo
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void runHistoryAction(redoDocument)}
        >
          Redo
        </button>
        <button type="button" disabled={busy} onClick={() => void refresh()}>
          Refresh
        </button>
      </div>
      {error ? <p className="muted">{error}</p> : null}
      {envelopes.length === 0 && !error ? (
        <p className="muted">No committed edits yet.</p>
      ) : (
        <ol className="operation-history-list">
          {envelopes.map((envelope) => (
            <li key={envelope.batch_id}>
              <span>{envelope.seq}</span>
              <code>
                {envelope.intent ?? "(pre-envelope)"}
                {envelope.checkpoint_label ? ` · ${envelope.checkpoint_label}` : ""}
              </code>
              <small>
                {envelope.actor?.kind ?? "unknown"}
                {envelope.inverse_operations ? "" : " · not undoable"}
              </small>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
