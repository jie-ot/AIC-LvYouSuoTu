"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brain, FileText, Images, Map, Route } from "lucide-react";
export function BottomNav() {
  const path = usePathname();
  const items = [
    {
      href: "/",
      label: "旅行",
      icon: Map,
      active: path === "/" || path.startsWith("/trips"),
    },
    {
      href: "/planning",
      label: "规划",
      icon: Route,
      active: path.startsWith("/planning"),
    },
    {
      href: "/postcards",
      label: "明信片",
      icon: Images,
      active: path === "/create" || path.startsWith("/postcards"),
    },
    {
      href: "/reports",
      label: "报告",
      icon: FileText,
      active: path.startsWith("/reports"),
    },
    { href: "/memory", label: "记忆", icon: Brain, active: path.startsWith("/memory") },
  ];
  return (
    <nav className="bottom-nav" aria-label="主导航">
      {items.map((item) => (
        <Link key={item.href} href={item.href} aria-current={item.active ? "page" : undefined}>
          <item.icon size={20} aria-hidden />
          <span>{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}
