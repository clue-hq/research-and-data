const brandContextIconSources = {
  assets: "/icons/brand-context/album.svg",
  check: "/icons/projects/check.svg",
  chevron: "/icons/brand-context/assets/chevron-down.svg",
  close: "/icons/detail/x.svg",
  colors: "/icons/brand-context/swatch-book.svg",
  code: "/icons/brand-context/code-xml.svg",
  document: "/icons/brand-context/file-text.svg",
  edit: "/icons/projects/sidebar-new-chat.svg",
  eye: "/icons/brand-context/eye.svg",
  filter: "/icons/filter.svg",
  folderClosed: "/icons/brand-context/folder-closed.svg",
  folderOpen: "/icons/projects/sidebar-folder-open.svg",
  folderPlus: "/icons/brand-context/folder-plus.svg",
  grid: "/icons/brand-context/assets/layout-grid.svg",
  link: "/icons/brand-context/assets/link.svg",
  list: "/icons/brand-context/assets/list.svg",
  more: "/icons/brand-context/assets/ellipsis.svg",
  sort: "/icons/brand-context/assets/arrow-up-down.svg",
  sortActive: "/icons/brand-context/assets/move-down.svg",
  moon: "/icons/brand-context/moon.svg",
  plus: "/icons/brand-context/plus.svg",
  rename: "/icons/projects/sidebar-new-chat.svg",
  search: "/icons/brand-context/assets/search.svg",
  slash: "/icons/detail/breadcrumb-slash.svg",
  sun: "/icons/brand-context/sun.svg",
  settings: "/icons/settings.svg",
  trash: "/icons/filters/trash.svg",
  typography: "/icons/brand-context/type.svg",
  upload: "/icons/brand-context/plus.svg",
} as const;

export type BrandContextIconName = keyof typeof brandContextIconSources;

export function BrandContextIcon({
  className = "",
  name,
  size = 16,
}: {
  className?: string;
  name: BrandContextIconName;
  size?: number;
}) {
  return (
    <span
      aria-hidden="true"
      className={className}
      style={{ alignItems: "center", display: "inline-flex", height: size, justifyContent: "center", width: size }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        src={brandContextIconSources[name]}
        style={{ display: "block", maxHeight: "100%", maxWidth: "100%" }}
      />
    </span>
  );
}
