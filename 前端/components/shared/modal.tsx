"use client"

import { useEffect, useRef, type ReactNode } from "react"
import { useApp } from "./app-context"
import { cn } from "@/lib/utils"

export function Modal({ open, onClose, children, className, label, labelledBy, describedBy }: {
  open: boolean; onClose: () => void; children: ReactNode; className?: string
  label?: string; labelledBy?: string; describedBy?: string
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const { registerBackHandler } = useApp()
  useEffect(() => {
    const dialog = ref.current
    if (!open || !dialog) return
    const previousFocus = document.activeElement as HTMLElement | null
    dialog.showModal()
    return () => {
      dialog.close()
      if (previousFocus?.isConnected) previousFocus.focus()
    }
  }, [open])
  useEffect(() => {
    if (open) return registerBackHandler(onClose)
  }, [open, onClose, registerBackHandler])

  return open ? <dialog ref={ref} className={cn("app-dialog", className)}
    aria-label={label} aria-labelledby={labelledBy} aria-describedby={describedBy}
    onCancel={(event) => { event.preventDefault(); onClose() }}
    onKeyDown={(event) => {
      if (event.key !== "Tab") return
      const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
        'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
      )).filter((element) => element.getClientRects().length > 0)
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (!first) { event.preventDefault(); return }
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus()
      }
    }}
    onClick={(event) => {
      if (event.target !== event.currentTarget) return
      const rect = event.currentTarget.getBoundingClientRect()
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose()
    }}>
    {children}
  </dialog> : null
}
