"use client"

import { useId, type ReactNode } from "react"
import { Modal } from "./modal"
import { cn } from "@/lib/utils"

export interface DialogAction {
  label: string
  onClick: () => void
  variant?: "primary" | "danger" | "ghost"
}

/** 通用确认/多选弹窗（保存确认、草稿保存/丢弃/取消等）。 */
export function ConfirmDialog({
  open,
  title,
  description,
  actions,
  onClose,
  icon,
}: {
  open: boolean
  title: string
  description?: string
  actions: DialogAction[]
  onClose: () => void
  icon?: ReactNode
}) {
  const titleId = useId()
  const descriptionId = useId()
  const safeAction = actions.findIndex((action) => action.variant !== "danger")

  return (
    <Modal open={open} onClose={onClose} labelledBy={titleId} describedBy={description ? descriptionId : undefined} className="confirm-modal">
      <div
        className="ui-material-in w-full max-w-xs overflow-hidden rounded-xl border border-border bg-card p-6 text-center shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        {icon && <div className="mb-3 flex justify-center">{icon}</div>}
        <h2 id={titleId} className="font-display text-lg font-bold tracking-[-0.01em] text-foreground text-balance">{title}</h2>
        {description ? <p id={descriptionId} className="mt-2 font-editorial text-sm font-medium leading-relaxed text-muted-foreground text-pretty">{description}</p> : null}
        <div className="mt-6 flex flex-col gap-2.5">
          {actions.map((a, index) => (
            <button
              key={a.label}
              autoFocus={index === safeAction}
              type="button"
              onClick={a.onClick}
              className={cn(
              "ui-pressable min-h-12 rounded-lg text-sm font-semibold",
                a.variant === "danger" && "bg-destructive text-white",
                a.variant === "ghost" && "bg-secondary text-secondary-foreground",
                (!a.variant || a.variant === "primary") && "bg-primary text-primary-foreground",
              )}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>
    </Modal>
  )
}
