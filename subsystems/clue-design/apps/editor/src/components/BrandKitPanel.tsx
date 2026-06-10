"use client";

import { BadgeCheck, Palette, ShieldCheck } from "lucide-react";
import type {
  BrandKitSummary,
  BrandTokenCatalog,
  Diagnostic,
  Medium,
  Operation,
  Scene
} from "@/engine/contracts";
import { updateDocumentBrand, updateDocumentMedium } from "@/engine/operations";

interface BrandKitPanelProps {
  scene: Scene;
  availableBrandKits: BrandKitSummary[];
  diagnostics: Diagnostic[];
  onOperation: (operation: Operation) => void;
  onRunBrandGovernance: () => void;
}

const mediumOptions: Medium[] = ["digital", "ad", "email", "print", "direct_mail"];

export function BrandKitPanel({
  scene,
  availableBrandKits,
  diagnostics,
  onOperation,
  onRunBrandGovernance
}: BrandKitPanelProps) {
  const currentRef = scene.meta.brand_kit;
  const selected = currentRef
    ? availableBrandKits.find(
        (brandKit) => brandKit.id === currentRef.id && brandKit.version === currentRef.version
      )
    : null;
  const tokenCatalog = selected?.tokens ?? null;

  return (
    <section className="inspector-section brand-kit-panel">
      <div className="section-heading">
        <Palette aria-hidden size={15} />
        Brand Kit
      </div>
      <div className="brand-current">
        <BadgeCheck aria-hidden size={16} />
        <div>
          <strong>{selected?.name ?? currentRef?.id ?? "No Brand Kit selected"}</strong>
          <span>
            {currentRef ? `${currentRef.id} v${currentRef.version}` : "Attach a stored Brand Kit before final validation."}
          </span>
        </div>
      </div>
      <label className="field">
        <span>Brand Kit</span>
        <select
          aria-label="Brand Kit"
          value={currentRef ? brandKitOptionValue(currentRef.id, currentRef.version) : ""}
          disabled={availableBrandKits.length === 0}
          onChange={(event) => {
            const next = availableBrandKits.find(
              (brandKit) => brandKitOptionValue(brandKit.id, brandKit.version) === event.target.value
            );
            if (next) {
              onOperation(updateDocumentBrand({ id: next.id, version: next.version }, scene.meta.medium));
            }
          }}
        >
          <option value="">Select Brand Kit</option>
          {availableBrandKits.map((brandKit) => (
            <option key={brandKitOptionValue(brandKit.id, brandKit.version)} value={brandKitOptionValue(brandKit.id, brandKit.version)}>
              {brandKit.name} v{brandKit.version}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>Medium</span>
        <select
          aria-label="Brand medium"
          value={scene.meta.medium ?? "digital"}
          onChange={(event) => onOperation(updateDocumentMedium(event.target.value as Medium))}
        >
          {mediumOptions.map((medium) => (
            <option key={medium} value={medium}>
              {mediumLabel(medium)}
            </option>
          ))}
        </select>
      </label>
      <div className="brand-status-row">
        <span className={selected?.product_ready ? "status-pill ready" : "status-pill"}>
          {selected?.product_ready ? "Product-ready" : "Unverified"}
        </span>
        <span className="status-pill">{selected?.approval_status ?? "no approval state"}</span>
      </div>
      {tokenCatalog ? <TokenSummary tokens={tokenCatalog} /> : null}
      <button type="button" className="brand-check-button" onClick={onRunBrandGovernance}>
        <ShieldCheck aria-hidden size={15} />
        Brand check
      </button>
      {diagnostics.length > 0 ? (
        <ul className="diagnostic-list brand-diagnostics">
          {diagnostics.map((diagnostic) => (
            <li key={`${diagnostic.code}-${diagnostic.message}`} className={diagnostic.severity}>
              <strong>{diagnostic.code}</strong>
              <span>{diagnostic.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function TokenSummary({ tokens }: { tokens: BrandTokenCatalog }) {
  const groups = [
    ["Surface", tokens.surface_tokens],
    ["Text", tokens.text_tokens],
    ["Type", tokens.typography_tokens],
    ["Space", tokens.spacing_tokens],
    ["Radius", tokens.radius_tokens]
  ] as const;

  return (
    <div className="token-summary" aria-label="Brand token summary">
      {groups.map(([label, values]) => (
        <div key={label}>
          <span>{label}</span>
          <strong>{values?.length ?? 0}</strong>
        </div>
      ))}
    </div>
  );
}

function brandKitOptionValue(id: string, version: number): string {
  return `${id}@${version}`;
}

function mediumLabel(medium: Medium): string {
  switch (medium) {
    case "direct_mail":
      return "Direct mail";
    case "digital":
      return "Digital";
    case "ad":
      return "Ad";
    case "email":
      return "Email";
    case "print":
      return "Print";
  }
}
