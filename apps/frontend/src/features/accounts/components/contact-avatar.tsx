"use client";

import { useContactAvatarController } from "../hooks/use-contact-avatar-controller";

/**
 * A contact's avatar.
 *
 * `src` is nullable and, on this slice, always absent: there is no avatar
 * pipeline and the browser does not scrape LinkedIn (G1). Initials are the
 * rendering, not a degraded state — the image branch stays only so a governed
 * avatar source can be plugged in later without touching callers.
 */
export function ContactAvatar({
  className = "",
  decorative = false,
  name,
  priority = false,
  size,
  src = null,
}: {
  className?: string;
  decorative?: boolean;
  name: string | null;
  priority?: boolean;
  size: number;
  src?: string | null;
}) {
  const controller = useContactAvatarController(name);

  if (controller.failed || !src) {
    return (
      <span
        aria-hidden={decorative || undefined}
        aria-label={decorative ? undefined : name ?? "Unnamed contact"}
        className={`inline-flex shrink-0 items-center justify-center rounded-full bg-[#e7eae2] text-[#44483f] ${className}`}
        role={decorative ? undefined : "img"}
        style={{ height: size, width: size }}
      >
        <span style={{ fontSize: Math.max(9, Math.round(size * 0.32)) }}>
          {controller.initials}
        </span>
      </span>
    );
  }

  return (
    // The API may return a signed URL from any enrichment CDN. A native image
    // keeps that contract independent of Next.js remotePatterns.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      alt={decorative ? "" : name ?? "Unnamed contact"}
      aria-hidden={decorative || undefined}
      className={`shrink-0 rounded-full object-cover ${className}`}
      decoding="async"
      fetchPriority={priority ? "high" : "auto"}
      height={size}
      onError={controller.markFailed}
      src={src}
      width={size}
    />
  );
}
