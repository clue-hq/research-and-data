export type AccountFlowIconName =
  | "account"
  | "activity"
  | "artifacts"
  | "contacts"
  | "influence"
  | "insights"
  | "linkedin"
  | "overview"
  | "recent"
  | "role"
  | "x";

type IconLayer = {
  height: number;
  left: number;
  src: string;
  top: number;
  width: number;
};

const assetVersion = "account-flow-20260730";

const contactsLayers: IconLayer[] = [
  {
    height: 3.66667,
    left: 2,
    src: "/icons/detail/tab-contacts-1.svg",
    top: 2.333,
    width: 3.66667,
  },
  {
    height: 4.44378,
    left: 0.243,
    src: "/icons/detail/tab-contacts-2.svg",
    top: 6.612,
    width: 7.18391,
  },
  {
    height: 3.77778,
    left: 6.112,
    src: "/icons/detail/tab-contacts-3.svg",
    top: 0.611,
    width: 3.77778,
  },
  {
    height: 4.40168,
    left: 5.905,
    src: "/icons/detail/tab-contacts-4.svg",
    top: 4.945,
    width: 5.68573,
  },
];

const simpleAssets: Record<
  Exclude<AccountFlowIconName, "contacts">,
  { canvas: number; height: number; src: string; width: number }
> = {
  account: {
    canvas: 11,
    height: 11,
    src: "/icons/building.svg",
    width: 11,
  },
  activity: {
    canvas: 12,
    height: 10,
    src: "/icons/detail/tab-activity.svg",
    width: 10,
  },
  artifacts: {
    canvas: 12,
    height: 11,
    src: "/icons/detail/tab-artifacts.svg",
    width: 11,
  },
  influence: {
    canvas: 13.4444,
    height: 13,
    src: "/icons/project.svg",
    width: 13.4444,
  },
  insights: {
    canvas: 12,
    height: 11.0502,
    src: "/icons/detail/tab-insights.svg",
    width: 11.0247,
  },
  linkedin: {
    canvas: 16,
    height: 16,
    src: "/logos/linkedin.svg",
    width: 16,
  },
  overview: {
    canvas: 12,
    height: 6.94995,
    src: "/icons/detail/tab-overview.svg",
    width: 10,
  },
  recent: {
    canvas: 11.0502,
    height: 11.0502,
    src: "/icons/detail/tab-insights.svg",
    width: 11.0247,
  },
  role: {
    canvas: 14.3333,
    height: 14.3333,
    src: "/icons/artifacts.svg",
    width: 13.3296,
  },
  x: {
    canvas: 17.6552,
    height: 15.9586,
    src: "/logos/x.svg",
    width: 17.6552,
  },
};

function versionedAsset(src: string) {
  return `${src}?v=${assetVersion}`;
}

export function AccountFlowIcon({
  active = false,
  className = "",
  name,
  size = 16,
}: {
  active?: boolean;
  className?: string;
  name: AccountFlowIconName;
  size?: number;
}) {
  if (name === "contacts") {
    const scale = size / 12;

    return (
      <span
        aria-hidden="true"
        className={`relative block shrink-0 ${className}`}
        style={{ height: size, width: size }}
      >
        {contactsLayers.map((layer) => (
          // Figma exports this compound glyph as four vector leaves.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            alt=""
            className={`absolute block max-w-none ${
              active ? "brightness-0" : ""
            }`}
            height={layer.height * scale}
            key={layer.src}
            src={versionedAsset(layer.src)}
            style={{
              left: layer.left * scale,
              top: layer.top * scale,
            }}
            width={layer.width * scale}
          />
        ))}
      </span>
    );
  }

  const asset = simpleAssets[name];
  const scale = size / asset.canvas;

  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center ${className}`}
      style={{ height: size, width: size }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        alt=""
        className={`block max-w-none object-contain ${
          active ? "brightness-0" : ""
        }`}
        height={asset.height * scale}
        src={versionedAsset(asset.src)}
        width={asset.width * scale}
      />
    </span>
  );
}
