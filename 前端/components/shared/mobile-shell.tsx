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
      <a href="#page-content" className="skip-link">跳到页面内容</a>
      <div id="page-content" tabIndex={-1} className={cn("mobile-shell", className)}>{children}</div>
    </div>
  );
}
