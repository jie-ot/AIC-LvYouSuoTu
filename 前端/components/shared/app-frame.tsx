"use client"

import type { ReactNode } from "react"
import { useApp } from "@/components/shared/app-context"
import { ProgressLoader } from "@/components/shared/progress-loader"
import { ToastHost } from "@/components/shared/toast-host"

export function AppFrame({ children }: { children: ReactNode }) {
  const { initLoading } = useApp()

  return (
    <>
      {initLoading ? (
        <div className="app-loading-overlay absolute inset-0 z-50 flex items-center justify-center bg-background/95">
          <ProgressLoader label="正在读取旅行记录…" />
        </div>
      ) : null}
      {children}
      <ToastHost />
    </>
  )
}
