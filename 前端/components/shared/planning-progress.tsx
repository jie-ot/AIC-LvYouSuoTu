"use client"

import type { PlanningProgressSnapshot } from "@/types"
import { TaskProgress } from "./task-progress"

export function PlanningProgress({ snapshot }: { snapshot: PlanningProgressSnapshot | null }) {
  return <TaskProgress snapshot={snapshot ? { ...snapshot, detail: null } : null} label="正在准备规划任务" />
}
