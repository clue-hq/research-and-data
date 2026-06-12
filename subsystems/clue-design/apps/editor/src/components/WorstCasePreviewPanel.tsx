import { useCallback, useState } from "react";
import { AlertTriangle } from "lucide-react";

import type { Scene } from "../engine/contracts";
import {
  buildWorstCaseBindingSet,
  fetchInstancePreview,
  type InstancePreviewResult
} from "../engine/instancePreview";

/**
 * Worst-case instance preview (Phase G slice G9): render the template
 * with every slot at its declared worst-case fixture, repeaters at
 * max_items, and the QR chain live — exactly what the personalization
 * runtime will derive for the heaviest recipient. Strictly read-only:
 * instances are derived artifacts, repairs happen on the template.
 */
export function WorstCasePreviewPanel({
  apiBaseUrl,
  scene
}: {
  apiBaseUrl: string;
  scene: Scene;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InstancePreviewResult | null>(null);

  const renderPreview = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const bindingSet = buildWorstCaseBindingSet(scene);
      setResult(await fetchInstancePreview(apiBaseUrl, scene, bindingSet, "svg"));
    } catch (previewError) {
      setResult(null);
      setError(
        previewError instanceof Error ? previewError.message : String(previewError)
      );
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl, scene]);

  const fitSlots = result?.fit_report.slots ?? [];
  const issues = fitSlots.filter((entry) => entry.verdict.kind !== "fits");

  return (
    <section className="inspector-section" data-testid="worst-case-preview-panel">
      <div className="section-heading">
        <AlertTriangle aria-hidden size={15} />
        Worst-case preview
      </div>
      <p className="muted">
        Derives this template with every slot at its worst-case content.
        Read-only: fixes belong on the template, never on instances.
      </p>
      <button type="button" disabled={busy} onClick={() => void renderPreview()}>
        {busy ? "Deriving…" : "Render worst case"}
      </button>
      {error ? <p className="muted worst-case-error">{error}</p> : null}
      {result ? (
        <div className="worst-case-result">
          <p data-testid="worst-case-fit-status">
            Fit: <strong>{result.fit_report.status ?? "unknown"}</strong>
            {result.status === "failed" ? " — instance would fail" : null}
          </p>
          {issues.length > 0 ? (
            <ul className="worst-case-issues">
              {issues.map((entry) => (
                <li key={`${entry.slot_key}`}>
                  <code>{entry.slot_key}</code>: {entry.verdict.kind}
                  {entry.verdict.kind === "fits_with_policy" &&
                  entry.verdict.adjusted_font_size !== undefined
                    ? ` (font → ${entry.verdict.adjusted_font_size})`
                    : null}
                  {entry.verdict.reason ? ` — ${entry.verdict.reason}` : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Every slot fits at worst case.</p>
          )}
          {result.artifact?.format === "svg" && result.artifact.content ? (
            <div
              className="worst-case-render"
              data-testid="worst-case-render"
              aria-label="Worst-case derived instance (read-only)"
              // Read-only render of the server-derived SVG artifact.
              dangerouslySetInnerHTML={{ __html: result.artifact.content }}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
