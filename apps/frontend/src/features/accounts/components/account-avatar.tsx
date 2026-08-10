/**
 * An account's mark.
 *
 * `logoUrl` is always `null` today — no logo pipeline exists, and the field is
 * on the wire so it can start returning values without a schema change (the
 * cheapest real fix is a `core.company_logo_url` field plus a materializer).
 * Until then the initials mark IS the rendering, not a failure state.
 */
export function AccountAvatar({
  className = "",
  logoUrl = null,
  name,
  rounded = "full",
  size,
}: {
  className?: string;
  logoUrl?: string | null;
  name: string;
  rounded?: "full" | "lg";
  size: number;
}) {
  const radius = rounded === "lg" ? "rounded-lg" : "rounded-full";

  if (logoUrl) {
    return (
      // A backend logo may live on any CDN; a native image keeps that contract
      // independent of Next.js remotePatterns.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        alt=""
        aria-hidden="true"
        className={`shrink-0 object-contain ${radius} ${className}`}
        height={size}
        src={logoUrl}
        width={size}
      />
    );
  }

  const initials =
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase() || "?";

  return (
    <span
      aria-hidden="true"
      className={`inline-flex shrink-0 items-center justify-center bg-[#eef1e9] text-[#567644] ${radius} ${className}`}
      style={{ height: size, width: size }}
    >
      <span style={{ fontSize: Math.max(8, Math.round(size * 0.4)) }}>
        {initials}
      </span>
    </span>
  );
}
