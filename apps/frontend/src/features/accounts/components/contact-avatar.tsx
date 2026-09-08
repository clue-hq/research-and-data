"use client";

import { useContactAvatarController } from "../hooks/use-contact-avatar-controller";

export function ContactAvatar({
  className = "",
  name,
  priority = false,
  size,
  src,
}: {
  className?: string;
  name: string;
  priority?: boolean;
  size: number;
  src?: string;
}) {
  const controller = useContactAvatarController(name);

  if (controller.failed || !src) {
    return (
      <span
        aria-label={name}
        className={`inline-flex shrink-0 items-center justify-center rounded-full bg-[var(--clue-ds-color-badge-bg-neutral)] text-[var(--clue-ds-color-badge-content-neutral)] ${className}`}
        role="img"
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
      alt={name}
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
