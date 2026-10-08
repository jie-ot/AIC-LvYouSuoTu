"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { isNavigationActive, navigationItems } from "./navigation";
export function BottomNav() {
  const path = usePathname();
  return (
    <nav className="bottom-nav" aria-label="主导航">
      {navigationItems.map((item) => (
        <Link key={item.href} href={item.href} aria-current={isNavigationActive(path, item.href) ? "page" : undefined}>
          <item.icon size={20} aria-hidden />
          <span>{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}
