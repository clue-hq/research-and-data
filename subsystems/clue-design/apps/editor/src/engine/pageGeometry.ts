import type { Orientation, PagePreset, PageSize, Unit } from "./contracts";

const POINTS_PER_INCH = 72;
const MM_PER_INCH = 25.4;

export interface PageSizeInput {
  width: number;
  height: number;
  unit: Unit;
  preset?: PagePreset | null;
}

export function normalizePageSize(input: PageSizeInput): PageSize {
  const width = normalizePositiveDimension(input.width);
  const height = normalizePositiveDimension(input.height);
  const unit = input.unit;
  const output = outputForSource(width, height, unit);
  return {
    width: unitToPoints(width, unit),
    height: unitToPoints(height, unit),
    unit: "pt",
    preset: input.preset ?? "custom",
    orientation: orientationForDimensions(width, height),
    source: {
      width,
      height,
      unit
    },
    ...(output ? { output } : {})
  };
}

export function unitToPoints(value: number, unit: Unit): number {
  switch (unit) {
    case "pt":
    case "px":
      return value;
    case "mm":
      return (value * POINTS_PER_INCH) / MM_PER_INCH;
    case "in":
      return value * POINTS_PER_INCH;
  }
}

export function physicalToInches(value: number, unit: "mm" | "in"): number {
  switch (unit) {
    case "mm":
      return value / MM_PER_INCH;
    case "in":
      return value;
  }
}

export function unitToInches(value: number, unit: Unit, dpi: number): number {
  switch (unit) {
    case "pt":
      return value / POINTS_PER_INCH;
    case "px":
      return value / dpi;
    case "mm":
      return value / MM_PER_INCH;
    case "in":
      return value;
  }
}

export function orientationForDimensions(width: number, height: number): Orientation {
  return width > height ? "landscape" : "portrait";
}

function outputForSource(width: number, height: number, unit: Unit): PageSize["output"] | null {
  switch (unit) {
    case "pt":
      return null;
    case "px":
      return {
        raster: {
          width_px: Math.max(1, Math.round(width)),
          height_px: Math.max(1, Math.round(height))
        }
      };
    case "mm":
    case "in":
      return {
        physical: {
          width,
          height,
          unit
        }
      };
  }
}

function normalizePositiveDimension(value: number): number {
  return Number.isFinite(value) && value > 0 ? Math.round(value * 1000) / 1000 : 1;
}
