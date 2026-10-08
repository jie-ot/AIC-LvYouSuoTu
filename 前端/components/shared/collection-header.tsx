import type { ReactNode } from "react"

export function CollectionHeader({
  section,
  title,
  description,
  action,
  count,
}: {
  section: string
  title: string
  description?: string
  action?: ReactNode
  count?: string
}) {
  return (
    <header className="collection-header">
      <div className="collection-heading">
        <div>
          <div className="brand-mark">旅有所图 / {section}</div>
          <h1>{title}</h1>
        </div>
        {action}
      </div>
      {description || count ? <div className="collection-caption">
        {description ? <p>{description}</p> : null}
        {count ? <span className="collection-count">{count}</span> : null}
      </div> : null}
    </header>
  )
}
