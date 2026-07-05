"use client";

import type { Dimension, Fill } from "@/engine/contracts";

/** Shared inspector field primitives: bound inputs in, callbacks out. */

type EditableDimensionMode = Exclude<Dimension["kind"], "token">;

export function DimensionModeSelect({
  label,
  dimension,
  disabled,
  inline = false,
  onChange
}: {
  label: string;
  dimension: Dimension;
  disabled: boolean;
  /** Label-left / control-right row (moda Details anatomy) for short controls. */
  inline?: boolean;
  onChange: (dimension: Dimension) => void;
}) {
  return (
    <label className={inline ? "field inline" : "field"}>
      <span>{label}</span>
      <select
        value={dimension.kind}
        disabled={disabled}
        onChange={(event) => {
          const mode = event.target.value as Dimension["kind"];
          if (mode === "token") {
            return;
          }
          onChange(dimensionForMode(mode, dimension));
        }}
      >
        <option value="fixed">Fixed</option>
        <option value="hug">Hug</option>
        <option value="fill">Fill</option>
        {dimension.kind === "token" ? <option value="token">Token</option> : null}
      </select>
    </label>
  );
}

function dimensionForMode(mode: EditableDimensionMode, current: Dimension): Dimension {
  switch (mode) {
    case "fixed":
      return {
        kind: "fixed",
        value: fixedDimensionValue(current)
      };
    case "hug":
      return {
        kind: "hug"
      };
    case "fill":
      return {
        kind: "fill",
        value: {
          weight: current.kind === "fill" ? current.value.weight : 1
        }
      };
  }
}

function fixedDimensionValue(dimension: Dimension): number {
  if (dimension.kind === "fixed") {
    return normalizePositiveDimension(dimension.value);
  }
  return 120;
}

export function normalizePositiveDimension(value: number): number {
  return Number.isFinite(value) && value > 0 ? value : 1;
}

export function TokenSelect({
  label,
  value,
  tokens,
  disabled = false,
  inline = false,
  onChange
}: {
  label: string;
  value: string;
  tokens?: string[];
  disabled?: boolean;
  /** Label-left / control-right row (moda Details anatomy) for short controls. */
  inline?: boolean;
  onChange: (token: string) => void;
}) {
  return (
    <label className={inline ? "field inline" : "field"}>
      <span>{label}</span>
      <select value={value} disabled={disabled || !tokens?.length} onChange={(event) => onChange(event.target.value)}>
        <option value="">Concrete value</option>
        {(tokens ?? []).map((token) => (
          <option key={token} value={token}>
            ${token}
          </option>
        ))}
      </select>
    </label>
  );
}

export function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  disabled = false,
  inline = false,
  onCommit
}: {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  /** Label-left / control-right row (moda Details anatomy) for short controls. */
  inline?: boolean;
  onCommit: (value: number) => void;
}) {
  return (
    <label className={inline ? "field inline" : "field"}>
      <span>{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next)) {
            onCommit(clampNumber(next, min, max));
          }
        }}
      />
    </label>
  );
}

function clampNumber(value: number, min?: number, max?: number): number {
  if (min !== undefined && value < min) {
    return min;
  }
  if (max !== undefined && value > max) {
    return max;
  }
  return value;
}

export function tokenFill(ownerId: string, role: string, token: string): Fill {
  return {
    id: `paint_${ownerId}_${role}`,
    paint: {
      kind: "token",
      token
    }
  };
}

export function tokenFromFill(fill: Fill | undefined): string {
  return fill?.paint.kind === "token" ? fill.paint.token : "";
}

export function roundForEditor(value: number): number {
  return Math.round(value * 1000) / 1000;
}
