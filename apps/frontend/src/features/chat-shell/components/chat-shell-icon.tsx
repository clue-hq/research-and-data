import Image from "next/image";

const CHAT_SHELL_ICON_ROOT = "/icons/chat-shell";

export type ChatShellIconName =
  | "ad-canvas"
  | "arrow-up"
  | "chevron-down"
  | "chevrons-up-down"
  | "ellipsis"
  | "laptop"
  | "layout-grid"
  | "maximize"
  | "canvas-panel-close"
  | "canvas-panel-open"
  | "pen-tool"
  | "pencil-ruler"
  | "pencil-ruler-knockout"
  | "web-output"
  | "x";

const CHAT_SHELL_ICON_GEOMETRY: Record<
  ChatShellIconName,
  { height: number; width: number }
> = {
  "ad-canvas": { height: 10.333, width: 10.333 },
  "arrow-up": { height: 10.333, width: 10.333 },
  "chevron-down": { height: 4, width: 7 },
  "chevrons-up-down": { height: 3, width: 5 },
  ellipsis: { height: 2.167, width: 10.333 },
  laptop: { height: 12.25, width: 15.081 },
  "layout-grid": { height: 10, width: 10 },
  maximize: { height: 11.5, width: 11.5 },
  "canvas-panel-close": { height: 10, width: 10 },
  "canvas-panel-open": { height: 10, width: 10 },
  "pen-tool": { height: 9.5, width: 10 },
  "pencil-ruler": { height: 12.671, width: 12.671 },
  "pencil-ruler-knockout": { height: 12.671, width: 12.671 },
  x: { height: 9, width: 9 },
  "web-output": { height: 12, width: 12 },
};

export function ChatShellIcon({
  className,
  name,
  size = 14,
}: {
  className?: string;
  name: ChatShellIconName;
  size?: number;
}) {
  const geometry = CHAT_SHELL_ICON_GEOMETRY[name];

  return (
    <span
      aria-hidden="true"
      className={className}
      style={{
        alignItems: "center",
        display: "inline-flex",
        flex: "0 0 auto",
        height: size,
        justifyContent: "center",
        width: size,
      }}
    >
      <Image
        alt=""
        height={geometry.height}
        src={`${CHAT_SHELL_ICON_ROOT}/${name}.svg`}
        width={geometry.width}
      />
    </span>
  );
}
