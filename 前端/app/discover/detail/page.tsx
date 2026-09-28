import { Suspense } from "react"
import { DiscoveryDetailView } from "@/components/views/discovery-detail-view"

export default function Page() { return <Suspense fallback={null}><DiscoveryDetailView /></Suspense> }
