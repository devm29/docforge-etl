"use client"

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react"

import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { cn } from "@/lib/utils"

type LargeTitleState = { visible: boolean; setVisible: (visible: boolean) => void }

const LargeTitleContext = createContext<LargeTitleState | null>(null)

/**
 * Apple's large-title pattern: the page's large title sits in the content, and the toolbar only
 * shows its compact title once the large one has scrolled under it.
 */
export function LargeTitleProvider({ children }: { children: ReactNode }) {
  const [visible, setVisible] = useState(false)
  const value = useMemo(() => ({ visible, setVisible }), [visible])
  return <LargeTitleContext value={value}>{children}</LargeTitleContext>
}

export function Toolbar({
  title,
  leading,
  children,
}: {
  title: ReactNode
  leading?: ReactNode
  children?: ReactNode
}) {
  const largeTitleVisible = useContext(LargeTitleContext)?.visible ?? false
  return (
    <header className="material sticky top-0 z-30 flex h-13 shrink-0 items-center gap-2 border-b border-border/60 bg-background/72 px-4 backdrop-blur-xl backdrop-saturate-[1.8]">
      <SidebarTrigger className="-ml-1" aria-label="Toggle sidebar" />
      <Separator orientation="vertical" className="mr-1 data-vertical:h-4 data-vertical:self-center" />
      {leading}
      <h1
        className={cn(
          "min-w-0 truncate text-[15px] font-semibold tracking-tight transition-opacity duration-200 ease-[var(--ease-apple)] motion-reduce:transition-none",
          largeTitleVisible && "opacity-0"
        )}
      >
        {title}
      </h1>
      <div className="ml-auto flex items-center gap-2">{children}</div>
    </header>
  )
}

export function PageTitle({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children?: ReactNode }) {
  const ref = useRef<HTMLHeadingElement | null>(null)
  const setVisible = useContext(LargeTitleContext)?.setVisible

  useEffect(() => {
    const element = ref.current
    if (!element || !setVisible) return
    const observer = new IntersectionObserver(([entry]) => setVisible(entry?.isIntersecting ?? false), {
      rootMargin: "-52px 0px 0px 0px",
    })
    observer.observe(element)
    return () => {
      observer.disconnect()
      setVisible(false)
    }
  }, [setVisible])

  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h2 ref={ref} className="text-[28px] leading-[34px] font-semibold tracking-tight">
          {title}
        </h2>
        {subtitle ? <p className="mt-1 text-[13px] text-muted-foreground">{subtitle}</p> : null}
      </div>
      {children ? <div className="flex items-center gap-2">{children}</div> : null}
    </div>
  )
}
