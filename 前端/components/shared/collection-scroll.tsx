"use client"

import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react"
import { AccountMenu } from "./account-menu"
import { CollectionHeader, type CollectionHeaderProps } from "./collection-header"

interface CollectionScrollProps extends CollectionHeaderProps {
  children: ReactNode
  contentClassName: string
  header?: ReactNode
  toolbarTools?: ReactNode
  scrollRef?: RefObject<HTMLElement | null>
}

/** Large page headings scroll away; only essential actions stay available. */
export function CollectionScroll({
  children, contentClassName, header, toolbarTools, scrollRef, ...heading
}: CollectionScrollProps) {
  const ownScroll = useRef<HTMLElement>(null)
  const headerRef = useRef<HTMLDivElement>(null)
  const viewport = scrollRef ?? ownScroll
  const [compact, setCompact] = useState(false)

  useEffect(() => {
    const root = viewport.current
    const header = headerRef.current
    if (!root || !header) return
    const target = header.querySelector(".collection-heading") ?? header
    const observer = new IntersectionObserver(([entry]) => {
      setCompact(!entry.isIntersecting && entry.boundingClientRect.bottom <= (entry.rootBounds?.top ?? 0))
    }, { root, threshold: 0, rootMargin: "-56px 0px 0px 0px" })
    observer.observe(target)
    return () => observer.disconnect()
  }, [viewport])

  return <div className="collection-pane">
    <main ref={viewport} className="collection-scroll" aria-label={heading.title}>
      <div ref={headerRef} className="collection-scroll-heading">
        {header ?? <CollectionHeader {...heading} />}
      </div>
      <div className={contentClassName}>{children}</div>
    </main>
    {compact ? <div className="collection-toolbar" role="group" aria-label={`${heading.title}快捷操作`}>
      <button type="button" className="collection-toolbar-title"
        aria-label={`回到${heading.title}顶部`} onClick={() => viewport.current?.scrollTo({ top: 0 })}>
        {heading.title}
      </button>
      <div className="collection-toolbar-actions">
        {toolbarTools}
        <AccountMenu />
        {heading.action}
      </div>
    </div> : null}
  </div>
}
