import { Suspense } from "react";
import { PhotoCreateView } from "@/components/views/photo-create-view";
export default function Page() {
  return <Suspense fallback={null}><PhotoCreateView /></Suspense>;
}
