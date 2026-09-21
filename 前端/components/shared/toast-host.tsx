"use client"

import { AlertCircle, CheckCircle2, Info } from "lucide-react"
import { useApp } from "@/components/shared/app-context"
import { cn } from "@/lib/utils"

const ICONS = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
}

const STYLES = {
  success: "text-primary",
  error: "text-destructive",
  info: "text-accent",
}

/** 全局 Toast 展示区（模拟 code=1001/1002/1003/1004 的友好提示）。 */
export function ToastHost() {
  const { toasts } = useApp()

  return (
    <div className="pointer-events-none fixed inset-x-0 top-[max(1rem,env(safe-area-inset-top))] z-[60] flex flex-col items-center gap-2 px-4">
      {toasts.map((t) => {
        const Icon = ICONS[t.variant]
        return (
          <div
            key={t.id}
            className="ui-toast-in pointer-events-auto flex min-h-12 w-full max-w-sm items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 text-sm font-medium text-foreground shadow-lg"
            role={t.variant === "error" ? "alert" : "status"}
          >
            <Icon className={cn("size-5 shrink-0", STYLES[t.variant])} aria-hidden />
            <span className="leading-snug">{t.message}</span>
          </div>
        )
      })}
    </div>
  )
}
