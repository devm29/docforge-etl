const INTERACTIVE = "input, textarea, select, button, a[href], [contenteditable=''], [contenteditable='true']"

/** Single-letter shortcuts fire only on a bare key press outside anything that takes typing or clicks. */
export function isShortcut(event: Pick<KeyboardEvent, "metaKey" | "ctrlKey" | "altKey" | "repeat" | "target">): boolean {
  if (event.metaKey || event.ctrlKey || event.altKey || event.repeat) return false
  const target = event.target
  if (!(target instanceof Element)) return true
  return target.closest(INTERACTIVE) === null
}
