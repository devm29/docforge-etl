import type { Metadata } from "next"
import { Inter } from "next/font/google"
import { cookies } from "next/headers"
import type { ReactNode } from "react"

import { AppSidebar } from "@/components/app-sidebar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"

import { Providers } from "./providers"
import "./globals.css"

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" })

export const metadata: Metadata = {
  title: { default: "DocForge", template: "%s · DocForge" },
  description: "Incremental document-intelligence ETL with page-level provenance.",
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const sidebarCookie = (await cookies()).get("sidebar_state")?.value
  return (
    <html lang="en" suppressHydrationWarning className={inter.variable}>
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
