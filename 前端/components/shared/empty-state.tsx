"use client";
import type { ReactNode } from "react";
export function EmptyState({
  icon,
  title,
  description,
  children,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <section className="empty-state">
      <div className="empty-mark">{icon}</div>
      <h3>{title}</h3>
      {description ? <p>{description}</p> : null}
      {children && <div className="empty-actions">{children}</div>}
    </section>
  );
}
