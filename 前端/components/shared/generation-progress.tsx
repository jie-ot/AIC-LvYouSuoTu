"use client"

import { useEffect, useState } from "react"
import type { GenerationProgress as Progress } from "./app-context"
import { TaskProgress, type TaskProgressSnapshot } from "./task-progress"
import { apiClient } from "@/lib/http-client"

export function GenerationProgress({ progress }: { progress: Progress }) {
  const [tracked, setTracked] = useState<{ id: string; snapshot: TaskProgressSnapshot } | null>(null)
  useEffect(() => {
    if (progress.phase !== "creating") return
    let active = true
    let done = false
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    const poll = async () => {
      try {
        const snapshot = await apiClient<TaskProgressSnapshot | null>(`/generate/progress?request_id=${encodeURIComponent(progress.requestId)}`, { signal: controller.signal })
        if (active && snapshot) {
          done = snapshot.done
          setTracked({ id: progress.requestId, snapshot })
        }
      } catch { /* A lost progress response must not interrupt generation. */ }
      finally { if (active && !done) timer = setTimeout(poll, 1500) }
    }
    void poll()
    return () => { active = false; clearTimeout(timer); controller.abort() }
  }, [progress.phase, progress.requestId])
  return <TaskProgress
    snapshot={progress.phase === "creating" && tracked?.id === progress.requestId ? tracked.snapshot : null}
    label={progress.phase === "uploading" ? "正在上传照片" : progress.phase === "preparing" ? "正在准备照片" : "正在准备生成"}
    detail={progress.phase === "uploading" ? `${progress.completed}/${progress.total} 张` : undefined}
    startedAt={progress.startedAt}
    value={progress.phase === "uploading" ? progress.completed / Math.max(1, progress.total) : undefined}
    waiting={progress.phase === "creating"}
  />
}
