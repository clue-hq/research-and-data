interface SidebarFigmaIconProps {
  className?: string;
  name: string;
  size?: 12 | 16;
}

export function SidebarFigmaIcon({
  className = "",
  name,
  size = 16,
}: SidebarFigmaIconProps) {
  return (
    // Exact SVG exported from the approved isolated Figma sidebar file.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      alt=""
      aria-hidden="true"
      className={`block shrink-0 ${className}`}
      height={size}
      src={`/icons/projects/${name}.svg`}
      width={size}
    />
  );
}
