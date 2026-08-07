"use client";

import { cn } from "@/lib/utils";
import { motion } from "motion/react";
import type { CSSProperties } from "react";
import { memo, useMemo } from "react";

export interface TextShimmerProps {
  children: string;
  className?: string;
  duration?: number;
  spread?: number;
}

const ShimmerComponent = ({
  children,
  className,
  duration = 2,
  spread = 2,
}: TextShimmerProps) => {
  const dynamicSpread = useMemo(
    () => (children?.length ?? 0) * spread,
    [children, spread]
  );

  return (
    <motion.span
      animate={{
        backgroundPosition: [
          "200% center, 0% center",
          "-200% center, 0% center",
        ],
      }}
      className={cn(
        "relative inline-block bg-clip-text text-transparent",
        className
      )}
      style={
        {
          "--spread": `${dynamicSpread}px`,
          backgroundImage:
            "linear-gradient(90deg, transparent calc(50% - var(--spread)), var(--color-foreground) 50%, transparent calc(50% + var(--spread))), linear-gradient(var(--color-muted-foreground), var(--color-muted-foreground))",
          backgroundRepeat: "no-repeat",
          backgroundSize: "250% 100%, 100% 100%",
        } as CSSProperties
      }
      transition={{
        duration: Math.max(duration, 1.8),
        ease: "linear",
        repeat: Number.POSITIVE_INFINITY,
        repeatType: "loop",
      }}
    >
      {children}
    </motion.span>
  );
};

export const Shimmer = memo(ShimmerComponent);
