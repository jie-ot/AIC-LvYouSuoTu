"use client";

import { cn } from "@/lib/utils";

export function ProgressLoader({
  label = "正在生成…",
  className,
}: {
  label?: string | null;
  className?: string;
}) {
  return (
    <div className={cn("travel-loader", className)} role="status">
      <div className="loader-track" aria-hidden>
        <i />
        <i />
        <i />
      </div>
      {label && <p>{label}</p>}
    </div>
  );
}

export function SkeletonCard({ ratio = "aspect-[3/4]" }: { ratio?: string }) {
  return (
    <div className="skeleton-card" aria-hidden>
      <div className={cn("skeleton-shimmer", ratio)} />
      <div className="skeleton-line" />
    </div>
  );
}
