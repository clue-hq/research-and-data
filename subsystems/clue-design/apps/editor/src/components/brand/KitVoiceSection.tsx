import React from "react";

import { readIngestionRules, readStringList, type IngestionRule } from "./kitJson";

function RulesetList({
  label,
  items
}: {
  label: string;
  items: string[];
}): React.ReactElement | null {
  if (items.length === 0) return null;
  return (
    <div className="kit-ruleset">
      <p className="eyebrow">{label}</p>
      <ul className="hairline-list">
        {items.map((item, index) => (
          <li key={`${label}-${index}`}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function IngestionRuleRow({ rule }: { rule: IngestionRule }): React.ReactElement {
  const isDont = rule.kind.toLowerCase().includes("dont") || rule.kind.toLowerCase() === "don't";
  return (
    <li>
      {isDont ? (
        <span className="diag-code kit-dont-chip">don&apos;t</span>
      ) : (
        <span className="chip">{rule.kind}</span>
      )}
      <span>{rule.text}</span>
    </li>
  );
}

/** Section 6 — tone chips, constraint lists (accessibility/imagery/print), and
 * the ingestion rules (don'ts get a leading "don't" chip). */
export function KitVoiceSection({
  kitJson,
  ingestionReport
}: {
  kitJson: any;
  ingestionReport: Record<string, any> | null;
}): React.ReactElement | null {
  const constraints =
    kitJson && typeof kitJson.constraints === "object" ? kitJson.constraints : {};
  const tone = readStringList(constraints.tone);
  const accessibility = readStringList(constraints.accessibility_notes);
  const imagery = readStringList(constraints.imagery);
  const print = readStringList(constraints.print_constraints);
  const rules = readIngestionRules(ingestionReport);

  const empty =
    tone.length === 0 &&
    accessibility.length === 0 &&
    imagery.length === 0 &&
    print.length === 0 &&
    rules.length === 0;
  if (empty) return null;

  return (
    <section className="brand-section" aria-label="Voice and rules">
      <div className="brand-section-head">
        <span className="title">Voice &amp; rules</span>
      </div>
      {tone.length > 0 ? (
        <div className="kit-tone-chips">
          {tone.map((item, index) => (
            <span className="chip" key={`tone-${index}`}>
              {item}
            </span>
          ))}
        </div>
      ) : null}
      <RulesetList label="Accessibility" items={accessibility} />
      <RulesetList label="Imagery" items={imagery} />
      <RulesetList label="Print" items={print} />
      {rules.length > 0 ? (
        <div className="kit-ruleset">
          <p className="eyebrow">Rules</p>
          <ul className="hairline-list kit-rule-list">
            {rules.map((rule, index) => (
              <IngestionRuleRow key={`rule-${index}`} rule={rule} />
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
