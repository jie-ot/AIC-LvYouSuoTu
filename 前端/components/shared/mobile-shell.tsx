"use client";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
export function MobileShell({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className="device-stage">
      <main className={cn("mobile-shell", className)}>{children}</main>
    </div>
  );
}
