import type { JsonValue } from "@/lib/api/schemas"

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 })
const usdPrecise = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
})
const integer = new Intl.NumberFormat("en-US")
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 })

export function formatUsd(value: number): string {
  return value !== 0 && Math.abs(value) < 1 ? usdPrecise.format(value) : usd.format(value)
}

export function formatInt(value: number): string {
  return integer.format(value)
}

export function formatCompact(value: number): string {
  return compact.format(value)
}

export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
}

export function runDuration(startedAt: string | null, finishedAt: string | null): number | null {
  if (!startedAt) return null
  const end = finishedAt ? Date.parse(finishedAt) : Date.now()
  return Math.max(0, end - Date.parse(startedAt))
}

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" })

export function formatRelative(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((Date.parse(iso) - now) / 1000)
  const abs = Math.abs(seconds)
  if (abs < 45) return "just now"
  if (abs < 3600) return relative.format(Math.round(seconds / 60), "minute")
  if (abs < 86400) return relative.format(Math.round(seconds / 3600), "hour")
  return relative.format(Math.round(seconds / 86400), "day")
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

export function humanize(path: string): string {
  const words = path.replace(/_/g, " ").trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

export function shortHash(hash: string | null | undefined): string {
  return hash ? hash.slice(0, 10) : "-"
}

export function displayValue(value: JsonValue): string {
  if (value === null) return "Not found"
  if (typeof value === "boolean") return value ? "Yes" : "No"
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}
