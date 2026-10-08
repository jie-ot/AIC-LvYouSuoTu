"use client"

import { useEffect, useRef, useState } from "react"
import { LoaderCircle } from "lucide-react"

export interface TaskProgressSnapshot {
  stageLabel: string
  detail?: string | null
  elapsedMs: number
  estimatedRemainingMs: number | null
  done: boolean
}

function duration(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`
}

function remaining(ms: number | null) {
  if (ms === null) return "剩余时间估算中"
  if (ms <= 0) return "耗时比预计稍久"
  if (ms < 60_000) return "预计还需不到 1 分钟"
  const minutes = ms / 60_000
  const low = Math.max(1, Math.floor(minutes * .75))
  const high = Math.ceil(minutes * 1.35)
  return `预计还需约 ${low}–${high} 分钟`
}

export function TaskProgress({ snapshot, label, detail, startedAt, value, waiting = true }: {
  snapshot: TaskProgressSnapshot | null; label: string; detail?: string
  startedAt?: number; value?: number; waiting?: boolean
}) {
  const anchor = useRef<{ at: number; value: TaskProgressSnapshot } | null>(null)
  const [clock, setClock] = useState({ elapsed: 0, remaining: null as number | null, stale: false })
  useEffect(() => {
    if (snapshot) anchor.current = { at: Date.now(), value: snapshot }
  }, [snapshot])
  useEffect(() => {
    const mounted = Date.now()
    const tick = () => {
      const now = Date.now()
      const current = anchor.current
      const since = current ? now - current.at : now - mounted
      setClock({
        elapsed: current?.value.done
          ? startedAt ? current.at - startedAt : current.value.elapsedMs
          : startedAt ? now - startedAt : current ? current.value.elapsedMs + since : now - mounted,
        remaining: current?.value.estimatedRemainingMs == null ? null : current.value.estimatedRemainingMs - since,
        stale: waiting && !current?.value.done && since > 20_000,
      })
    }
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [startedAt, waiting])

  return <section className="task-progress" aria-label="任务进度">
    <div className="task-progress-heading">{!snapshot?.done && <LoaderCircle size={17} aria-hidden />}<h2 role="status" aria-live="polite">{snapshot?.stageLabel ?? label}</h2></div>
    {(snapshot?.detail || detail) ? <p className="task-progress-detail">{snapshot?.detail || detail}</p> : null}
    {value !== undefined ? <progress value={value} max={1} aria-label="照片上传进度" /> : null}
    <div className="task-progress-time" aria-live="off"><span>已用 <time>{duration(clock.elapsed)}</time></span><span>{snapshot?.done ? "已结束" : remaining(clock.remaining)}</span></div>
    {clock.stale ? <p className="task-progress-connection" role="status">暂时无法更新进度，正在重新连接</p> : null}
  </section>
}
