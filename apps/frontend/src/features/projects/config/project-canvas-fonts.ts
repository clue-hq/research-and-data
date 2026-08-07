export const projectCanvasFontFamilies = {
  Arial: "Arial, sans-serif",
  Inter: '"Inter Variable", Arial, sans-serif',
  Satoshi: '"Satoshi", Arial, sans-serif',
} as const;

export type ProjectCanvasFont = keyof typeof projectCanvasFontFamilies;
