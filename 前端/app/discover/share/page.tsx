import { Suspense } from "react"
import { DiscoveryShareView } from "@/components/views/discovery-share-view"

export default function Page() { return <Suspense fallback={null}><DiscoveryShareView /></Suspense> }
