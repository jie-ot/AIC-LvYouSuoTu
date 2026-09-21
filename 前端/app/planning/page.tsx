import { Suspense } from "react"
import { PlanningView } from "@/components/views/planning-view"

export default function Page() {
  return <Suspense fallback={null}><PlanningView /></Suspense>
}
