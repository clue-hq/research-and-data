import React, { useState } from "react";

import type { WebFragmentSlotValue, WebNode, WebNodeProps } from "@/engine/webDocuments";
import type { FragmentCard, FragmentSlotSpec } from "@/engine/webFragmentCards";

/**
 * The cloned-section (fragment) inspector — F3.2, and the four founder rulings it serves.
 *
 * A fragment node pins ONE immutable harvested artifact and carries flat slot values. What a
 * human may change here is therefore narrower than for any other node, and deliberately so:
 *
 * * **D-F3 / R1 — slot VALUES only.** Text, an asset, a link target, a visibility toggle. Never
 *   the fragment's internals: that markup is somebody else's section, it is content-addressed,
 *   and editing it would produce a different fragment wearing this one's name. The card has no
 *   control that could try.
 * * **D-F6 — the lineage is visible.** A degraded original shows its marker and what the reason
 *   MEANS; a repair says which clone it repairs and why; and a repair can be retired (R17-2),
 *   which is the only way out of a lineage holding two released repairs. The harvested original
 *   is never retirable (R17-3) — it is the evidence the repair is judged against.
 * * **D-F8 — a hidden-on-source section is shown as one**, with the evidence that said so, and
 *   is activated only by a human, only with a usable preview in front of them. A section the
 *   site hides was never rendered, so the picture is an ISOLATION RENDER of the section's own
 *   harvested bytes (ruling P-7) — generated on demand, and labelled as what it is.
 *
 * Presentation only, per docs/frontend-practices.md rule 2: every control builds ONE operation
 * and fires `applyProps`, and the three durable actions are callbacks the shell owns.
 */

export type FragmentCardStatus = "idle" | "loading" | "ready" | "error";

export interface FragmentAssetOption {
  id: string;
  label: string;
}

interface WebFragmentInspectorProps {
  node: WebNode;
  card: FragmentCard | null;
  cardStatus: FragmentCardStatus;
  cardError: string | null;
  /** The document's own asset records — an asset slot resolves through `doc.assets` or it does
   * not resolve at all (F1 ruling #9 / LUMW0035), so the picker offers exactly these. */
  documentAssets: FragmentAssetOption[];
  busy: boolean;
  applyProps: (props: WebNodeProps, intent: string) => void;
  onGeneratePreview: (fragmentId: string) => void;
  onActivate: (fragmentId: string) => void;
  onRetire: (fragmentId: string) => void;
  /** In-flight state and the last refusal for the three durable actions. */
  actionBusy: boolean;
  actionError: string | null;
}

export function WebFragmentInspector({
  node,
  card,
  cardStatus,
  cardError,
  documentAssets,
  busy,
  applyProps,
  onGeneratePreview,
  onActivate,
  onRetire,
  actionBusy,
  actionError
}: WebFragmentInspectorProps): React.ReactElement {
  const fragmentId = node.fragment_id ?? "";
  return (
    <>
      <FragmentIdentityCard
        fragmentId={fragmentId}
        card={card}
        cardStatus={cardStatus}
        cardError={cardError}
      />
      {card?.degraded || card?.derivedFrom || (card?.repairs.length ?? 0) > 0 ? (
        <FragmentLineageCard
          card={card as FragmentCard}
          busy={actionBusy}
          error={actionError}
          onGeneratePreview={onGeneratePreview}
          onRetire={onRetire}
        />
      ) : null}
      <FragmentSlotsCard
        node={node}
        slots={card?.slots ?? []}
        documentAssets={documentAssets}
        busy={busy}
        applyProps={applyProps}
      />
      {card?.hiddenOnSource ? (
        <FragmentDormancyCard
          card={card}
          busy={actionBusy}
          error={actionError}
          onGeneratePreview={onGeneratePreview}
          onActivate={onActivate}
        />
      ) : null}
    </>
  );
}

/**
 * The list of sections the source site HIDES (D-F8).
 *
 * A dormant section is on no page, which is what dormant means — so nothing can select one, and
 * the inspector needs its own way to reach them. Rendered beside the fragment card because D-F8
 * is explicit that the inspector is the ONE place a human sees and activates a hidden section:
 * the agent never offers them.
 */
export function WebDormantSectionsCard({
  sections,
  busy,
  error,
  onGeneratePreview,
  onActivate
}: {
  sections: FragmentCard[];
  busy: boolean;
  error: string | null;
  onGeneratePreview: (fragmentId: string) => void;
  onActivate: (fragmentId: string) => void;
}): React.ReactElement | null {
  if (sections.length === 0) {
    return null;
  }
  return (
    <section className="brand-card web-insp-card">
      <h3 className="web-insp-card-title">Hidden on source site</h3>
      <p className="web-insp-hint">
        {sections.length === 1 ? "One section is" : `${sections.length} sections are`} kept from
        this capture but hidden on the site itself. They never appear on a page and are never
        offered to the agent. Activating one is your call.
      </p>
      {sections.map((section) => (
        <FragmentDormancyCard
          key={section.fragmentId}
          card={section}
          busy={busy}
          error={error}
          onGeneratePreview={onGeneratePreview}
          onActivate={onActivate}
          nested
        />
      ))}
    </section>
  );
}

// ── the cards ────────────────────────────────────────────────────────────────

function FragmentIdentityCard({
  fragmentId,
  card,
  cardStatus,
  cardError
}: {
  fragmentId: string;
  card: FragmentCard | null;
  cardStatus: FragmentCardStatus;
  cardError: string | null;
}): React.ReactElement {
  return (
    <section className="brand-card web-insp-card">
      <h3 className="web-insp-card-title">Cloned section</h3>
      {cardStatus === "loading" ? (
        <p className="web-insp-hint">Reading the cloned section…</p>
      ) : null}
      {cardStatus === "error" ? (
        <p className="web-insp-error" role="alert">
          {cardError ?? "The cloned section could not be loaded."}
        </p>
      ) : null}
      {card?.previewPath ? (
        <figure className="web-insp-frag-preview">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={card.previewPath} alt={card.label ?? "Cloned section preview"} />
          {card.previewBasis === "isolation_render" ? (
            <figcaption className="web-insp-hint">
              Isolation render — our engine drawing this section&rsquo;s own harvested bytes, not
              a photo of the live site.
            </figcaption>
          ) : null}
        </figure>
      ) : null}
      <dl className="web-insp-metrics">
        <div className="is-wide">
          <dt>Section</dt>
          <dd>{card?.label ?? fragmentId}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd>{card?.sectionRole ?? "—"}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{card?.status ?? "—"}</dd>
        </div>
        <div>
          <dt>Artifact</dt>
          <dd>{fragmentId || "—"}</dd>
        </div>
        <div>
          {/* Document order across the visible AND hidden sections — a sort key, never an
              offset into a list (F3.0 M3). */}
          <dt>Position on page</dt>
          <dd>{card?.sectionIndex ?? "—"}</dd>
        </div>
        {card?.pageUrl ? (
          <div className="is-wide">
            <dt>Cloned from</dt>
            <dd>{card.pageUrl}</dd>
          </div>
        ) : null}
      </dl>
      <p className="web-insp-hint">
        A cloned section is frozen: you can move it up or down the page and change what its slots
        hold. Its markup, proportions and internal layout stay as the site had them.
      </p>
    </section>
  );
}

function FragmentSlotsCard({
  node,
  slots,
  documentAssets,
  busy,
  applyProps
}: {
  node: WebNode;
  slots: FragmentSlotSpec[];
  documentAssets: FragmentAssetOption[];
  busy: boolean;
  applyProps: (props: WebNodeProps, intent: string) => void;
}): React.ReactElement {
  const values = node.slots ?? {};
  const write = (key: string, value: WebFragmentSlotValue | null, intent: string) => {
    const next: Record<string, WebFragmentSlotValue> = { ...values };
    if (value === null) {
      delete next[key];
    } else {
      next[key] = value;
    }
    applyProps(
      { kind: "fragment", fragment_id: node.fragment_id ?? "", slots: next },
      intent
    );
  };

  return (
    <section className="brand-card web-insp-card">
      <h3 className="web-insp-card-title">Section content</h3>
      {slots.length === 0 ? (
        <p className="web-insp-hint">
          This cloned section declares no editable slots — it renders exactly as captured.
        </p>
      ) : null}
      {slots.map((slot) => (
        <SlotControl
          key={slot.key}
          slot={slot}
          value={values[slot.key] ?? null}
          documentAssets={documentAssets}
          busy={busy}
          onWrite={write}
        />
      ))}
    </section>
  );
}

function SlotControl({
  slot,
  value,
  documentAssets,
  busy,
  onWrite
}: {
  slot: FragmentSlotSpec;
  value: WebFragmentSlotValue | null;
  documentAssets: FragmentAssetOption[];
  busy: boolean;
  onWrite: (key: string, value: WebFragmentSlotValue | null, intent: string) => void;
}): React.ReactElement {
  const placeholder =
    typeof slot.fallback === "string" && slot.fallback.length > 0
      ? slot.fallback
      : "As captured";

  if (slot.kind === "visibility") {
    // Absent means "as the section had it" — the toggle reflects the stored override only.
    const checked = value && "visible" in value ? value.visible : true;
    return (
      <label className="field web-insp-field">
        <span className="field-label">{slot.key}</span>
        <input
          type="checkbox"
          checked={checked}
          disabled={busy}
          onChange={(event) =>
            onWrite(slot.key, { visible: event.target.checked }, "set_fragment_slot_visibility")
          }
        />
      </label>
    );
  }

  if (slot.kind === "image") {
    // A select, not a free field: an asset slot resolves through `doc.assets` or the write is
    // refused (LUMW0035), so offering anything else would be offering a refusal.
    const current = value && "asset" in value ? value.asset : "";
    return (
      <label className="field web-insp-field">
        <span className="field-label">{slot.key}</span>
        <select
          value={current}
          disabled={busy}
          onChange={(event) =>
            onWrite(
              slot.key,
              event.target.value === "" ? null : { asset: event.target.value },
              "set_fragment_slot_asset"
            )
          }
        >
          <option value="">As captured</option>
          {documentAssets.map((asset) => (
            <option key={asset.id} value={asset.id}>
              {asset.label}
            </option>
          ))}
        </select>
      </label>
    );
  }

  // `text` and `href` both ride the node's text tag; the MANIFEST is what remembers which is a
  // link target, so the two differ in their label and their input type, not in their write.
  return (
    <SlotTextField
      slot={slot}
      placeholder={placeholder}
      value={value && "text" in value ? value.text : ""}
      busy={busy}
      onWrite={onWrite}
    />
  );
}

function SlotTextField({
  slot,
  placeholder,
  value,
  busy,
  onWrite
}: {
  slot: FragmentSlotSpec;
  placeholder: string;
  value: string;
  busy: boolean;
  onWrite: (key: string, value: WebFragmentSlotValue | null, intent: string) => void;
}): React.ReactElement {
  const [draft, setDraft] = useState(value);
  const commit = () => {
    if (draft === value) {
      return;
    }
    onWrite(
      slot.key,
      draft.trim() === "" ? null : { text: draft },
      slot.kind === "href" ? "set_fragment_slot_href" : "set_fragment_slot_text"
    );
  };
  return (
    <label className="field web-insp-field">
      <span className="field-label">
        {slot.key}
        {slot.kind === "href" ? " (link)" : ""}
      </span>
      <input
        type={slot.kind === "href" ? "url" : "text"}
        value={draft}
        placeholder={placeholder}
        disabled={busy}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.currentTarget.blur();
          }
        }}
      />
    </label>
  );
}

function FragmentLineageCard({
  card,
  busy,
  error,
  onGeneratePreview,
  onRetire
}: {
  card: FragmentCard;
  busy: boolean;
  error: string | null;
  onGeneratePreview: (fragmentId: string) => void;
  onRetire: (fragmentId: string) => void;
}): React.ReactElement {
  return (
    <section className="brand-card web-insp-card">
      <h3 className="web-insp-card-title">Condition &amp; repairs</h3>
      {card.degraded ? (
        <p className="web-insp-error" role="status">
          <strong>Broken clone{card.degradedReason ? ` — ${card.degradedReason}` : ""}.</strong>{" "}
          {card.degradedNote}
        </p>
      ) : null}
      {card.repairsWhat ? (
        <p className="web-insp-hint">
          Repairs <strong>{card.repairsWhat.label ?? card.repairsWhat.fragmentId}</strong>
          {card.derivedReason ? ` — ${card.derivedReason}` : ""}
        </p>
      ) : null}
      {card.supersededBy ? (
        <p className="web-insp-hint">
          A released repair ({card.supersededBy}) now stands in for this section on new pages.
          The original stays here as the evidence it was judged against.
        </p>
      ) : null}
      {card.lineageAmbiguous.length > 1 ? (
        <p className="web-insp-error" role="status">
          Two released repairs of this section exist and neither replaces the other, so a page
          cannot choose between them. Retire the one you do not want.
        </p>
      ) : null}
      {card.repairs.length > 0 ? (
        <ul className="web-insp-frag-lineage">
          {card.repairs.map((repair) => (
            <li key={repair.fragmentId}>
              <span className="web-insp-frag-lineage-head">
                {repair.label ?? repair.fragmentId} · {repair.status}
                {repair.degraded ? " · broken" : ""}
              </span>
              {repair.derivedReason ? (
                <span className="web-insp-hint">{repair.derivedReason}</span>
              ) : null}
              <span className="web-insp-frag-actions">
                {repair.previewPath ? null : (
                  <button
                    type="button"
                    className="web-insp-action"
                    disabled={busy}
                    onClick={() => onGeneratePreview(repair.fragmentId)}
                  >
                    Render preview
                  </button>
                )}
                {repair.status === "deprecated" ? null : (
                  <button
                    type="button"
                    className="web-insp-action is-danger"
                    disabled={busy}
                    onClick={() => onRetire(repair.fragmentId)}
                  >
                    Retire repair
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <p className="web-insp-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

function FragmentDormancyCard({
  card,
  busy,
  error,
  onGeneratePreview,
  onActivate,
  nested = false
}: {
  card: FragmentCard;
  busy: boolean;
  error: string | null;
  onGeneratePreview: (fragmentId: string) => void;
  onActivate: (fragmentId: string) => void;
  nested?: boolean;
}): React.ReactElement {
  const body = (
    <>
      {nested ? (
        <p className="web-insp-frag-lineage-head">{card.label ?? card.fragmentId}</p>
      ) : null}
      <p className="web-insp-hint">
        The source site hides this section
        {card.sectionIndex === null ? "" : ` (position ${card.sectionIndex} on the page)`}. It is
        kept, never released automatically, and never offered to the agent.
      </p>
      {card.hiddenOnSource && card.hiddenOnSource.evidence.length > 0 ? (
        <ul className="web-insp-frag-evidence">
          {card.hiddenOnSource.evidence.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
      {card.previewPath ? (
        <figure className="web-insp-frag-preview">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={card.previewPath} alt={card.label ?? "Hidden section preview"} />
          <figcaption className="web-insp-hint">
            Isolation render — this section&rsquo;s own harvested bytes, drawn by our engine. The
            site never showed it, so there is no photograph of it to crop.
          </figcaption>
        </figure>
      ) : (
        <p className="web-insp-hint">{card.activation.message}</p>
      )}
      <span className="web-insp-frag-actions">
        {card.previewPath ? null : (
          <button
            type="button"
            className="web-insp-action"
            disabled={busy}
            onClick={() => onGeneratePreview(card.fragmentId)}
          >
            Render preview
          </button>
        )}
        <button
          type="button"
          className="web-insp-action"
          disabled={busy || !card.activation.allowed}
          title={card.activation.message ?? undefined}
          onClick={() => onActivate(card.fragmentId)}
        >
          Activate section
        </button>
      </span>
      {error ? (
        <p className="web-insp-error" role="alert">
          {error}
        </p>
      ) : null}
    </>
  );
  if (nested) {
    return <div className="web-insp-frag-dormant">{body}</div>;
  }
  return (
    <section className="brand-card web-insp-card">
      <h3 className="web-insp-card-title">Hidden on source site</h3>
      {body}
    </section>
  );
}
