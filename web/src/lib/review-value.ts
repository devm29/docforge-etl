import { jsonSchema, type JsonValue } from "@/lib/api/schemas"

export type ParsedInput = { ok: true; value: JsonValue } | { ok: false; error: string }

export function toEditable(value: JsonValue): string {
  if (value === null) return ""
  if (typeof value === "object") return JSON.stringify(value, null, 2)
  return String(value)
}

export function parseEdited(raw: string, original: JsonValue): ParsedInput {
  const text = raw.trim()
  if (text === "") return { ok: true, value: null }
  if (Array.isArray(original) || (original !== null && typeof original === "object")) {
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch {
      return { ok: false, error: "Enter valid JSON, for example a list of line items." }
    }
    const value = jsonSchema.safeParse(parsed)
    return value.success ? { ok: true, value: value.data } : { ok: false, error: "Enter valid JSON." }
  }
  if (typeof original === "boolean" || text === "true" || text === "false") {
    if (text === "true" || text === "yes") return { ok: true, value: true }
    if (text === "false" || text === "no") return { ok: true, value: false }
    return { ok: false, error: "Enter true or false." }
  }
  return { ok: true, value: text }
}

export function placeholderFor(path: string): string {
  if (path.endsWith("_date")) return "YYYY-MM-DD"
  if (["total", "subtotal", "tax", "contract_value"].includes(path)) return "1234.50"
  if (path.endsWith("_days") || path.endsWith("_months")) return "Whole number"
  if (path === "auto_renews") return "true or false"
  return "Corrected value"
}
