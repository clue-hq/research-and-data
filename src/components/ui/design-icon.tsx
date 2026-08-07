interface DesignIconProps {
  alt?: string;
  className?: string;
  name: string;
  size?: number;
}

const intrinsicIconSizes: Record<string, [number, number]> = {
  artifacts: [13.33, 14.33],
  "arrow-up-right": [6, 6],
  brand: [12.11, 13.33],
  building: [11, 11],
  "chevron-down": [7, 4],
  "circle-chevron-down": [11, 11],
  "clue-mark": [12.84, 11.78],
  filter: [11, 10],
  hash: [9, 10],
  home: [13, 13.67],
  "progress-75": [13, 13],
  project: [13.44, 13],
  research: [10, 7.5],
  search: [10, 10],
  settings: [9, 9],
  "sidebar-toggle": [10, 10],
  sort: [10, 7],
  spinner: [11, 11],
  templates: [12.57, 12.57],
};

export function DesignIcon({
  alt = "",
  className = "",
  name,
  size = 12,
}: DesignIconProps) {
  const [width, height] = intrinsicIconSizes[name] ?? [size, size];

  return (
    <span
      aria-hidden={alt ? undefined : true}
      aria-label={alt || undefined}
      className={`inline-flex shrink-0 items-center justify-center ${className}`}
      role={alt ? "img" : undefined}
      style={{ height: size, width: size }}
    >
      {/* Figma exports are the visible leaf vectors, centered in a larger icon
          frame. Preserving both sizes avoids inflating small glyphs. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        aria-hidden="true"
        className="block max-w-none object-contain"
        height={height}
        src={`/icons/${name}.svg`}
        width={width}
      />
    </span>
  );
}
