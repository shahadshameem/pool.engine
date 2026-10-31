/**
 * Sanitizes and validates a redirect destination path.
 * Strictly prevents open-redirect attacks by only allowing same-origin relative paths.
 *
 * Rules:
 * - Must start with exactly one '/'
 * - Must NOT start with '//' (protocol-relative URL)
 * - Must NOT contain backslashes '\'
 * - Must NOT contain a URL scheme (e.g., http:, https:, javascript:, data:)
 */
export function getSafeRedirectPath(rawPath: string | null | undefined, fallback = "/home"): string {
  if (!rawPath || typeof rawPath !== "string") return fallback

  const trimmed = rawPath.trim()
  if (!trimmed) return fallback

  // Check for protocol-relative or backslash-based bypasses
  if (!trimmed.startsWith("/") || trimmed.startsWith("//") || trimmed.includes("\\")) {
    return fallback
  }

  // Check for schemes (e.g., javascript:, data:, https:)
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(trimmed)) {
    return fallback
  }

  return trimmed
}
