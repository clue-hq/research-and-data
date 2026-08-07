"use client";

import React, { useCallback, useEffect, useState } from "react";

import { editorApiBaseUrl } from "@/engine/editorConfig";
import { assetThumbnailUrl } from "@/engine/assetLibrary";
import {
  createWebAccount,
  deleteWebAccount,
  listWebAccounts,
  resumeWebBatch,
  startWebBatch,
  suggestSlugBase,
  updateWebAccount,
  webBatchIsUnfinished,
  type WebAccount,
  type WebAccountInput,
  type WebBatchManifestRow,
  type WebBatchResult
} from "@/engine/webDocuments";
import { WebAssetDrawer } from "@/components/web/WebAssetDrawer";
import type { AssetRecord } from "@/engine/contracts";

/**
 * The "Generate for accounts…" modal (template docs only). Accounts management
 * (list / create / edit / delete) lives here — there is no standalone route in
 * v0. The setup face multi-selects accounts + toggles publish + a slug base,
 * then Run derives (and optionally publishes) one page per account and swaps to
 * a manifest of the outcomes; an interrupted batch offers Resume.
 *
 * Mirrors WebPublishDialog: this modal composes the webDocuments.ts fetch
 * wrappers directly and owns its own busy/error state (the same self-contained
 * pattern the publish dialog uses).
 */

interface WebBatchDialogProps {
  /** The template document the batch derives from. */
  documentId: string;
  /** The template title — prefills the slug base. */
  title: string;
  onClose: () => void;
}

function errorMessage(cause: unknown): string {
  return cause instanceof Error ? cause.message : "Something went wrong.";
}

/** The per-account status chip's variant class — reusing the shared status-pill
 * vocabulary (published = success, failed = error, derived = neutral). */
function statusPillClass(status: WebBatchManifestRow["status"]): string {
  if (status === "published") {
    return "status-pill is-approved";
  }
  if (status === "failed") {
    return "status-pill is-error";
  }
  return "status-pill";
}

export function WebBatchDialog({
  documentId,
  title,
  onClose
}: WebBatchDialogProps): React.ReactElement {
  const apiBaseUrl = editorApiBaseUrl();
  const [accounts, setAccounts] = useState<WebAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // The account mini-form: closed, creating, or editing a specific account.
  const [form, setForm] = useState<{ mode: "new" } | { mode: "edit"; account: WebAccount } | null>(
    null
  );
  const [publish, setPublish] = useState(true);
  const [slugBase, setSlugBase] = useState(() => suggestSlugBase(title));
  const [batch, setBatch] = useState<WebBatchResult | null>(null);

  const loadAccounts = useCallback(() => {
    setLoading(true);
    setError(null);
    return listWebAccounts({ apiBaseUrl })
      .then((next) => setAccounts(next))
      .catch((cause: unknown) => setError(errorMessage(cause)))
      .finally(() => setLoading(false));
  }, [apiBaseUrl]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listWebAccounts({ apiBaseUrl })
      .then((next) => {
        if (!cancelled) setAccounts(next);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(errorMessage(cause));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  // Close on Escape (unless the account form or the asset drawer own the moment;
  // those manage their own affordances, so a top-level Escape still closes).
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const toggleSelected = useCallback((accountId: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(accountId)) {
        next.delete(accountId);
      } else {
        next.add(accountId);
      }
      return next;
    });
  }, []);

  const handleCreate = useCallback(
    async (input: WebAccountInput) => {
      setBusy(true);
      setError(null);
      try {
        const created = await createWebAccount({ apiBaseUrl }, input);
        setForm(null);
        setSelected((current) => new Set(current).add(created.accountId));
        await loadAccounts();
      } catch (cause) {
        setError(errorMessage(cause));
      } finally {
        setBusy(false);
      }
    },
    [apiBaseUrl, loadAccounts]
  );

  const handleUpdate = useCallback(
    async (accountId: string, patch: WebAccountInput) => {
      setBusy(true);
      setError(null);
      try {
        await updateWebAccount({ apiBaseUrl }, accountId, patch);
        setForm(null);
        await loadAccounts();
      } catch (cause) {
        setError(errorMessage(cause));
      } finally {
        setBusy(false);
      }
    },
    [apiBaseUrl, loadAccounts]
  );

  const handleDelete = useCallback(
    async (accountId: string) => {
      setBusy(true);
      setError(null);
      try {
        await deleteWebAccount({ apiBaseUrl }, accountId);
        setSelected((current) => {
          const next = new Set(current);
          next.delete(accountId);
          return next;
        });
        await loadAccounts();
      } catch (cause) {
        setError(errorMessage(cause));
      } finally {
        setBusy(false);
      }
    },
    [apiBaseUrl, loadAccounts]
  );

  const handleRun = useCallback(async () => {
    if (selected.size === 0) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await startWebBatch({ apiBaseUrl }, documentId, {
        accountIds: [...selected],
        publish,
        slugBase: slugBase.trim()
      });
      setBatch(result);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl, documentId, selected, publish, slugBase]);

  const handleResume = useCallback(async () => {
    if (!batch) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await resumeWebBatch({ apiBaseUrl }, batch.batchId);
      setBatch(result);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl, batch]);

  const runLabel =
    selected.size > 0
      ? `Generate ${selected.size} page${selected.size === 1 ? "" : "s"}`
      : "Generate pages";

  const renderSetup = (): React.ReactElement => (
    <div className="web-modal-body">
      <div className="web-batch-section">
        <div className="web-batch-section-head">
          <span className="web-modal-field-label">Accounts</span>
          {form == null ? (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={busy}
              onClick={() => setForm({ mode: "new" })}
            >
              New account
            </button>
          ) : null}
        </div>

        {form?.mode === "new" ? (
          <AccountForm
            account={null}
            busy={busy}
            apiBaseUrl={apiBaseUrl}
            onSubmit={handleCreate}
            onCancel={() => setForm(null)}
          />
        ) : null}

        {loading ? (
          <p className="web-empty-hint">Loading accounts…</p>
        ) : accounts.length === 0 && form == null ? (
          <p className="web-empty-hint">No accounts yet — add one to generate a page for it.</p>
        ) : (
          <ul className="web-account-list">
            {accounts.map((account) =>
              form?.mode === "edit" && form.account.accountId === account.accountId ? (
                <li key={account.accountId}>
                  <AccountForm
                    account={account}
                    busy={busy}
                    apiBaseUrl={apiBaseUrl}
                    onSubmit={(patch) => handleUpdate(account.accountId, patch)}
                    onCancel={() => setForm(null)}
                  />
                </li>
              ) : (
                <li key={account.accountId} className="web-account-row">
                  <label className="web-account-row-main">
                    <input
                      type="checkbox"
                      checked={selected.has(account.accountId)}
                      disabled={busy}
                      onChange={() => toggleSelected(account.accountId)}
                    />
                    <span className="web-account-name">{account.name}</span>
                    {account.domain ? (
                      <span className="web-account-domain">{account.domain}</span>
                    ) : null}
                  </label>
                  <div className="web-account-actions">
                    <button
                      type="button"
                      className="web-insp-action"
                      aria-label={`Edit ${account.name}`}
                      title="Edit"
                      disabled={busy}
                      onClick={() => setForm({ mode: "edit", account })}
                    >
                      ✎
                    </button>
                    <button
                      type="button"
                      className="web-insp-action is-danger"
                      aria-label={`Delete ${account.name}`}
                      title="Delete"
                      disabled={busy}
                      onClick={() => handleDelete(account.accountId)}
                    >
                      🗑
                    </button>
                  </div>
                </li>
              )
            )}
          </ul>
        )}
      </div>

      <label className="web-insp-checkbox">
        <input
          type="checkbox"
          checked={publish}
          disabled={busy}
          onChange={(event) => setPublish(event.target.checked)}
        />
        Publish each generated page
      </label>

      {publish ? (
        <label className="web-modal-field">
          <span className="web-modal-field-label">Slug base</span>
          <input
            type="text"
            value={slugBase}
            disabled={busy}
            onChange={(event) => setSlugBase(event.target.value)}
            placeholder="my-site"
            spellCheck={false}
          />
          <span className="web-modal-hint">
            Each page publishes at <code>{slugBase.trim() || "my-site"}</code>-&lt;account&gt;.
          </span>
        </label>
      ) : null}

      <div className="web-modal-actions">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={busy || selected.size === 0}
          onClick={handleRun}
        >
          {busy ? "Generating…" : runLabel}
        </button>
      </div>
    </div>
  );

  const renderResult = (result: WebBatchResult): React.ReactElement => (
    <div className="web-modal-body">
      <div className="web-batch-counts">
        <span className="status-pill">{result.counts.total} total</span>
        <span className="status-pill">{result.counts.derived} derived</span>
        {result.counts.published > 0 ? (
          <span className="status-pill is-approved">{result.counts.published} published</span>
        ) : null}
        {result.counts.failed > 0 ? (
          <span className="status-pill is-error">{result.counts.failed} failed</span>
        ) : null}
      </div>

      <ul className="web-manifest">
        {result.manifest.map((row) => {
          const absoluteUrl = row.url ? new URL(row.url, apiBaseUrl).toString() : null;
          return (
            <li key={row.accountId} className="web-manifest-row">
              <span className="web-manifest-name">{row.accountName}</span>
              <span className={statusPillClass(row.status)}>{row.status}</span>
              {row.unbound.length > 0 ? (
                <span
                  className="web-manifest-unbound"
                  title={`Unbound: ${row.unbound.join(", ")}`}
                >
                  {row.unbound.length} unbound
                </span>
              ) : null}
              <span className="web-manifest-links">
                {absoluteUrl ? (
                  <a
                    className="web-publish-url"
                    href={absoluteUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {row.slug ?? "View"}
                  </a>
                ) : null}
                {row.documentId ? (
                  <a
                    className="web-manifest-open"
                    href={`/web/${encodeURIComponent(row.documentId)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Open
                  </a>
                ) : null}
              </span>
              {row.error ? <span className="web-manifest-error">{row.error}</span> : null}
            </li>
          );
        })}
      </ul>

      <div className="web-modal-actions">
        {webBatchIsUnfinished(result) ? (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy}
            onClick={handleResume}
          >
            {busy ? "Resuming…" : "Resume"}
          </button>
        ) : null}
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={busy}
          onClick={() => setBatch(null)}
        >
          Back to accounts
        </button>
      </div>
    </div>
  );

  return (
    <div className="web-modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="web-modal web-batch-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Generate for accounts"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="web-modal-head">
          <span className="web-modal-title">Generate for accounts</span>
          <button type="button" className="web-modal-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        {batch ? renderResult(batch) : renderSetup()}
        {error ? (
          <p className="web-modal-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}

// ── account mini-form ─────────────────────────────────────────────────────────

interface AccountFormValues {
  name: string;
  domain: string;
  logoAssetId: string | null;
  data: { key: string; value: string }[];
  notes: string;
}

function toFormValues(account: WebAccount | null): AccountFormValues {
  if (!account) {
    return { name: "", domain: "", logoAssetId: null, data: [], notes: "" };
  }
  return {
    name: account.name,
    domain: account.domain ?? "",
    logoAssetId: account.logoAssetId,
    data: Object.entries(account.data).map(([key, value]) => ({ key, value })),
    notes: account.notes ?? ""
  };
}

/** The inline create/edit form. Local field state; the logo is picked through
 * the shared WebAssetDrawer (image library + upload). On save it shapes the
 * data rows into a `{key: value}` map (blank keys dropped) and hands a typed
 * {@link WebAccountInput} up. */
function AccountForm({
  account,
  busy,
  apiBaseUrl,
  onSubmit,
  onCancel
}: {
  account: WebAccount | null;
  busy: boolean;
  apiBaseUrl: string;
  onSubmit: (input: WebAccountInput) => void;
  onCancel: () => void;
}): React.ReactElement {
  const [values, setValues] = useState<AccountFormValues>(() => toFormValues(account));
  const [logoOpen, setLogoOpen] = useState(false);

  const setField = <K extends keyof AccountFormValues>(key: K, value: AccountFormValues[K]) =>
    setValues((current) => ({ ...current, [key]: value }));

  const setDataRow = (index: number, patch: Partial<{ key: string; value: string }>) =>
    setValues((current) => ({
      ...current,
      data: current.data.map((row, i) => (i === index ? { ...row, ...patch } : row))
    }));

  const addDataRow = () =>
    setValues((current) => ({ ...current, data: [...current.data, { key: "", value: "" }] }));

  const removeDataRow = (index: number) =>
    setValues((current) => ({ ...current, data: current.data.filter((_, i) => i !== index) }));

  const onLogoPick = (record: AssetRecord) => {
    setLogoOpen(false);
    setField("logoAssetId", record.id);
  };

  const submit = () => {
    const data: Record<string, string> = {};
    for (const row of values.data) {
      const key = row.key.trim();
      if (key) {
        data[key] = row.value;
      }
    }
    onSubmit({
      name: values.name.trim(),
      domain: values.domain.trim() ? values.domain.trim() : null,
      logoAssetId: values.logoAssetId,
      data,
      notes: values.notes.trim() ? values.notes.trim() : null
    });
  };

  return (
    <div className="web-account-form">
      <label className="web-modal-field">
        <span className="web-modal-field-label">Name</span>
        <input
          type="text"
          value={values.name}
          disabled={busy}
          onChange={(event) => setField("name", event.target.value)}
          placeholder="Acme Health"
          autoFocus
        />
      </label>
      <label className="web-modal-field">
        <span className="web-modal-field-label">Domain</span>
        <input
          type="text"
          value={values.domain}
          disabled={busy}
          onChange={(event) => setField("domain", event.target.value)}
          placeholder="acme.com"
          spellCheck={false}
        />
      </label>

      <div className="web-modal-field">
        <span className="web-modal-field-label">Logo</span>
        <div className="web-logo-field">
          {values.logoAssetId ? (
            <img
              className="web-logo-thumb"
              src={assetThumbnailUrl(apiBaseUrl, values.logoAssetId)}
              alt="Account logo"
            />
          ) : null}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={busy}
            onClick={() => setLogoOpen(true)}
          >
            {values.logoAssetId ? "Change logo" : "Choose logo"}
          </button>
          {values.logoAssetId ? (
            <button
              type="button"
              className="btn btn-quiet btn-sm"
              disabled={busy}
              onClick={() => setField("logoAssetId", null)}
            >
              Remove
            </button>
          ) : null}
        </div>
        {logoOpen ? (
          <WebAssetDrawer mode="insert" onPick={onLogoPick} onClose={() => setLogoOpen(false)} />
        ) : null}
      </div>

      <div className="web-modal-field">
        <span className="web-modal-field-label">Data fields</span>
        {values.data.map((row, index) => (
          <div key={index} className="web-data-row">
            <input
              type="text"
              value={row.key}
              disabled={busy}
              onChange={(event) => setDataRow(index, { key: event.target.value })}
              placeholder="plan"
              spellCheck={false}
              aria-label="Field key"
            />
            <input
              type="text"
              value={row.value}
              disabled={busy}
              onChange={(event) => setDataRow(index, { value: event.target.value })}
              placeholder="Enterprise"
              aria-label="Field value"
            />
            <button
              type="button"
              className="web-insp-action"
              aria-label="Remove field"
              title="Remove"
              disabled={busy}
              onClick={() => removeDataRow(index)}
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy}
          onClick={addDataRow}
        >
          Add field
        </button>
        <span className="web-modal-hint">
          Each field becomes an <code>account.&lt;key&gt;</code> binding.
        </span>
      </div>

      <label className="web-modal-field">
        <span className="web-modal-field-label">Notes</span>
        <textarea
          className="web-insp-classes"
          value={values.notes}
          disabled={busy}
          rows={2}
          onChange={(event) => setField("notes", event.target.value)}
          placeholder="Agent context only — never substituted into the page."
        />
      </label>

      <div className="web-modal-actions">
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={busy || values.name.trim().length === 0}
          onClick={submit}
        >
          {account ? "Save" : "Add account"}
        </button>
        <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
