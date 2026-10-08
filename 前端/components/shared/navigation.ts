import { Brain, Compass, FileText, Images, Map, Route } from "lucide-react"

export const navigationItems = [
  { href: "/discover", label: "发现", desktopLabel: "旅行发现", icon: Compass },
  { href: "/", label: "旅行", desktopLabel: "我的旅行", icon: Map },
  { href: "/planning", label: "规划", desktopLabel: "行程规划", icon: Route },
  { href: "/postcards", label: "明信片", desktopLabel: "旅行明信片", icon: Images },
  { href: "/reports", label: "报告", desktopLabel: "旅行人格报告", icon: FileText },
  { href: "/memory", label: "记忆", desktopLabel: "旅行记忆", icon: Brain },
]

export function isNavigationActive(path: string, href: string) {
  if (href === "/") return path === "/" || path.startsWith("/trips/")
  if (href === "/postcards" && path === "/create") return true
  return path === href || path.startsWith(`${href}/`)
}
