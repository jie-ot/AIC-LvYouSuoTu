"use client"

import { useEffect, useRef, useState } from "react"
import { ChevronDown, LogOut, UserRound } from "lucide-react"
import { useAuth } from "./auth-context"
import { useApp } from "./app-context"
import { ConfirmDialog } from "./confirm-dialog"

export function AccountMenu() {
  const { user, logout } = useAuth()
  const { hasUnsavedDraft } = useApp()
  const [open, setOpen] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false) }
    document.addEventListener("pointerdown", outside)
    document.addEventListener("keydown", escape)
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape) }
  }, [open])
  async function leave() {
    setBusy(true)
    try { await logout() } catch { /* The local session is already cleared. */ }
  }
  if (!user) return null
  return <div className="account-menu" ref={root}>
    <button type="button" className="account-trigger" onClick={() => setOpen((old) => !old)} aria-expanded={open} aria-label={`账号：${user.username}`}><UserRound size={15} aria-hidden /><span>{user.username}</span>{user.readOnly ? <small>只读</small> : null}<ChevronDown size={13} aria-hidden /></button>
    {open ? <div className="account-popover"><strong>{user.username}</strong><p>{user.readOnly ? "只读演示，可浏览现有资料" : user.isDemo ? "演示资料维护账号" : "个人账号"}</p><button type="button" disabled={busy} onClick={() => { if (hasUnsavedDraft) setConfirm(true); else void leave() }}><LogOut size={16} aria-hidden />退出登录 / 切换账号</button></div> : null}
    <ConfirmDialog open={confirm} title="退出当前账号？" description="未保存的行程草稿会清除，已保存的旅行资料会保留。" onClose={() => setConfirm(false)} actions={[{ label: "继续整理", variant: "ghost", onClick: () => setConfirm(false) }, { label: "退出登录", variant: "danger", onClick: () => { void leave() } }]} />
  </div>
}
