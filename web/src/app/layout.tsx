import type { Metadata } from "next"
import { cookies } from "next/headers"
import type { ReactNode } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"

import { Providers } from "./providers"
// Self-hosted Google Fonts, so builds never depend on fonts.googleapis.com being reachable.
import "@fontsource/ibm-plex-sans/400.css"
import "@fontsource/ibm-plex-sans/500.css"
import "@fontsource/ibm-plex-sans/600.css"
import "@fontsource/ibm-plex-mono/400.css"
import "@fontsource/ibm-plex-mono/500.css"
import "@fontsource-variable/source-serif-4/wght.css"
import "./globals.css"

export const metadata: Metadata = {
  title: { default: "DocForge", template: "%s · DocForge" },
  description: "Incremental document-intelligence ETL with page-level provenance.",
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const sidebarCookie = (await cookies()).get("sidebar_state")?.value
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>
          <SidebarProvider defaultOpen={sidebarCookie !== "false"}>
            <AppSidebar />
            <SidebarInset className="min-w-0 bg-background">{children}</SidebarInset>
          </SidebarProvider>
        </Providers>
      </body>
    </html>
  )
}
