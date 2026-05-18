"use client"

import { FileText, Inbox, LayoutGrid, Search, Workflow } from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"

import { HealthIndicator } from "@/components/health-indicator"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import { useOverview } from "@/lib/api/hooks"

const NAV = [
  { href: "/", label: "Overview", icon: LayoutGrid },
  { href: "/documents", label: "Documents", icon: FileText },
  { href: "/runs", label: "Runs", icon: Workflow },
  { href: "/review", label: "Review", icon: Inbox },
  { href: "/search", label: "Search", icon: Search },
] as const

export function AppSidebar() {
  const pathname = usePathname()
  const overview = useOverview()
  const pending = overview.data?.pending_reviews ?? 0

  return (
    <Sidebar collapsible="icon" className="material border-r border-sidebar-border/60">
      <SidebarHeader className="h-13 justify-center px-3">
        <Link href="/" className="flex items-center gap-2.5 rounded-md px-1 outline-none focus-visible:ring-4 focus-visible:ring-ring">
          <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground">
            <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
              <path d="M6 3h8l4 4v14H6z" strokeLinejoin="round" />
              <path d="M9 12h6M9 16h4" strokeLinecap="round" />
            </svg>
          </span>
          <span className="truncate text-[15px] font-semibold tracking-tight group-data-[collapsible=icon]:hidden">
            DocForge
          </span>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
            Pipeline
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV.map((item) => {
                const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)
                return (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton asChild isActive={active} tooltip={item.label} className="h-8 text-[13px]">
                      <Link href={item.href} aria-current={active ? "page" : undefined}>
                        <item.icon strokeWidth={1.75} />
                        <span>{item.label}</span>
                      </Link>
                    </SidebarMenuButton>
                    {item.href === "/review" && pending > 0 ? (
                      <SidebarMenuBadge className="tabular-nums">{pending}</SidebarMenuBadge>
                    ) : null}
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="group-data-[collapsible=icon]:hidden">
        <HealthIndicator />
      </SidebarFooter>
    </Sidebar>
  )
}
