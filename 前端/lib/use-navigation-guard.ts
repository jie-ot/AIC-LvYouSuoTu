"use client"

import { useEffect } from "react"
import { useRouter } from "next/navigation"

/** Cover sidebar/mobile links and reload without replacing the current history. */
export function useNavigationGuard(enabled: boolean, onLeave: (proceed: () => void) => void) {
  const router = useRouter()
  useEffect(() => {
    if (!enabled) return
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = "" }
    const click = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null
      if (!link || link.hasAttribute("download") || (link.target && link.target !== "_self")) return
      const url = new URL(link.href, location.href)
      if (url.origin !== location.origin || (url.pathname === location.pathname && url.search === location.search)) return
      event.preventDefault()
      event.stopPropagation()
      onLeave(() => router.push(url.pathname + url.search + url.hash))
    }
    document.addEventListener("click", click, true)
    window.addEventListener("beforeunload", beforeUnload)
    return () => {
      document.removeEventListener("click", click, true)
      window.removeEventListener("beforeunload", beforeUnload)
    }
  }, [enabled, onLeave, router])
}
