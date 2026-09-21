import { Suspense } from "react"
import { TripDetailView } from "@/components/views/trip-detail-view"

export default function Page() {
  return <Suspense fallback={null}><TripDetailView /></Suspense>
}
