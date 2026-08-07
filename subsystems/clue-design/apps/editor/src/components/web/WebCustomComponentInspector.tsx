"use client";

import React, { useEffect, useState } from "react";

import type {
  CustomComponentArtifact,
  CustomComponentPropSchema,
  CustomComponentPropValue,
  WebNode
} from "@/engine/webDocuments";
import type { WebCustomComponentRuntimeState } from "@/engine/webBridge";

export type CustomComponentArtifactStatus = "idle" | "loading" | "ready" | "error";

interface WebCustomComponentInspectorProps {
  node: WebNode;
  artifact: CustomComponentArtifact | null;
  artifactStatus: CustomComponentArtifactStatus;
  artifactError: string | null;
  runtime: WebCustomComponentRuntimeState | null;
  republishRequired: boolean;
  busy: boolean;
  applyProps: (props: Record<string, CustomComponentPropValue>) => void;
  onEditWithAI: () => void;
  onRepublish: () => void;
}

function statusLabel(
  artifactStatus: CustomComponentArtifactStatus,
  runtime: WebCustomComponentRuntimeState | null
): string {
  if (artifactStatus === "loading") return "Loading artifact";
  if (artifactStatus === "error") return "Artifact unavailable";
  if (artifactStatus !== "ready") return "Waiting for artifact";
  if (!runtime) return "Waiting for runtime";
  if (runtime.state === "ready" || runtime.state === "height") return "Runtime ready";
  if (runtime.state === "recoverable-error") return "Runtime recovered from an error";
  return "Runtime error";
}

function CustomPropControl({
  name,
  schema,
  value,
  required,
  disabled,
  onCommit
}: {
  name: string;
  schema: CustomComponentPropSchema;
  value: CustomComponentPropValue | undefined;
  required: boolean;
  disabled: boolean;
  onCommit: (value: CustomComponentPropValue) => void;
}): React.ReactElement {
  const inputId = `custom-component-prop-${name.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const label = name
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ");
  const [draft, setDraft] = useState(value == null ? "" : String(value));

  useEffect(() => {
    setDraft(value == null ? "" : String(value));
  }, [value]);

  if (schema.type === "boolean") {
    return (
      <label className="web-insp-checkbox web-custom-prop-toggle" htmlFor={inputId}>
        <input
          id={inputId}
          type="checkbox"
          checked={value === true}
          disabled={disabled}
          aria-label={`${label} custom component prop`}
          aria-required={required}
          onChange={(event) => onCommit(event.target.checked)}
        />
        <span>
          {label}
          {required ? " *" : ""}
        </span>
      </label>
    );
  }

  if (schema.type === "string" && schema.enum && schema.enum.length > 0) {
    return (
      <label className="field web-insp-field" htmlFor={inputId}>
        <span>
          {label}
          {required ? " *" : ""}
        </span>
        <select
          id={inputId}
          value={typeof value === "string" ? value : ""}
          disabled={disabled}
          required={required}
          aria-label={`${label} custom component prop`}
          onChange={(event) => onCommit(event.target.value)}
        >
          {!required && value == null ? <option value="">Default</option> : null}
          {schema.enum.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
    );
  }

  const commitDraft = () => {
    if (schema.type === "number") {
      const parsed = Number(draft);
      if (draft.trim() !== "" && Number.isFinite(parsed) && parsed !== value) {
        onCommit(parsed);
      } else if (draft.trim() === "" || !Number.isFinite(parsed)) {
        setDraft(value == null ? "" : String(value));
      }
      return;
    }
    if (draft !== value) onCommit(draft);
  };

  return (
    <label className="field web-insp-field" htmlFor={inputId}>
      <span>
        {label}
        {required ? " *" : ""}
      </span>
      <input
        id={inputId}
        type={schema.type === "number" ? "number" : "text"}
        step={schema.type === "number" ? "any" : undefined}
        value={draft}
        disabled={disabled}
        required={required}
        aria-label={`${label} custom component prop`}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commitDraft}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commitDraft();
            event.currentTarget.blur();
          } else if (event.key === "Escape") {
            setDraft(value == null ? "" : String(value));
            event.currentTarget.blur();
          }
        }}
      />
    </label>
  );
}

export function WebCustomComponentInspector({
  node,
  artifact,
  artifactStatus,
  artifactError,
  runtime,
  republishRequired,
  busy,
  applyProps,
  onEditWithAI,
  onRepublish
}: WebCustomComponentInspectorProps): React.ReactElement {
  const props = node.props ?? {};
  const required = new Set(artifact?.manifest.props_schema.required ?? []);
  const warnings = artifact?.manifest.warnings ?? [];
  const runtimeMessage =
    runtime?.state === "error" || runtime?.state === "recoverable-error"
      ? runtime.message
      : null;
  const currentStatus = statusLabel(artifactStatus, runtime);

  return (
    <>
      <section
        className="brand-card web-insp-card"
        aria-labelledby="custom-component-title"
        aria-busy={artifactStatus === "loading"}
      >
        <div className="web-custom-component-heading">
          <div>
            <h3 id="custom-component-title" className="web-insp-card-title">
              {artifact?.manifest.meta.name ?? "Custom component"}
            </h3>
            {artifact?.manifest.meta.description ? (
              <p className="web-insp-hint">{artifact.manifest.meta.description}</p>
            ) : null}
          </div>
          <span
            className={`web-custom-component-status is-${currentStatus
              .toLowerCase()
              .replaceAll(" ", "-")}`}
            role={runtime?.state === "error" || artifactStatus === "error" ? "alert" : "status"}
            aria-label={`Custom component status: ${currentStatus}`}
          >
            {currentStatus}
          </span>
        </div>

        <dl className="web-insp-metrics">
          <div className="is-wide">
            <dt>Slug</dt>
            <dd>{node.slug ?? "—"}</dd>
          </div>
          <div className="is-wide">
            <dt>Artifact pin</dt>
            <dd title={node.artifact_id}>{node.artifact_id ?? "—"}</dd>
          </div>
          <div>
            <dt>Source version</dt>
            <dd>{artifact?.provenance.source_version ?? "—"}</dd>
          </div>
          <div>
            <dt>Compile warnings</dt>
            <dd>{warnings.length}</dd>
          </div>
        </dl>

        {artifactError ? (
          <p className="web-insp-error" role="alert">
            {artifactError}
          </p>
        ) : null}
        {runtimeMessage ? (
          <p className="web-insp-error" role="alert">
            {runtimeMessage}
          </p>
        ) : null}
        {warnings.length > 0 ? (
          <details className="web-custom-component-warnings">
            <summary>
              {warnings.length} compile warning{warnings.length === 1 ? "" : "s"}
            </summary>
            <ul>
              {warnings.map((warning, index) => (
                <li key={`${warning.code ?? "warning"}-${index}`}>
                  {warning.code ? <code>{warning.code}</code> : null}
                  {warning.message ?? "Compiler warning"}
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        {republishRequired ? (
          <div className="web-custom-component-republish" role="status">
            <span>Republish to update the live website.</span>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onRepublish}>
              Republish
            </button>
          </div>
        ) : null}

        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={onEditWithAI}
          disabled={busy}
          aria-label={`Edit ${artifact?.manifest.meta.name ?? node.slug ?? "custom component"} with AI`}
        >
          Edit with AI
        </button>
      </section>

      {artifact ? (
        <section className="brand-card web-insp-card" aria-labelledby="custom-component-props">
          <h3 id="custom-component-props" className="web-insp-card-title">
            Component properties
          </h3>
          {Object.keys(artifact.manifest.props_schema.properties).length === 0 ? (
            <p className="web-insp-hint">This component has no editable properties.</p>
          ) : (
            Object.entries(artifact.manifest.props_schema.properties).map(
              ([name, schema]) => (
                <CustomPropControl
                  key={name}
                  name={name}
                  schema={schema}
                  value={props[name]}
                  required={required.has(name)}
                  disabled={busy}
                  onCommit={(value) =>
                    applyProps({
                      ...props,
                      [name]: value
                    })
                  }
                />
              )
            )
          )}
          <p className="web-insp-hint">* Required by the pinned artifact schema.</p>
        </section>
      ) : null}
    </>
  );
}
