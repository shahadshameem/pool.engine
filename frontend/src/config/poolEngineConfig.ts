/**
 * Configuration module for Pool Engine backend integration.
 *
 * Safety Invariants:
 * 1. Disabled by default (VITE_USE_POOL_ENGINE defaults to false).
 * 2. Validated before use: does not crash the React application if URL is missing or malformed.
 * 3. Never prints or logs secrets or credentials.
 */

export interface PoolEngineConfig {
  /**
   * Whether the Pool Engine backend integration is enabled.
   * Defaults to false.
   */
  enabled: boolean

  /**
   * Base URL of the Pool Engine service (e.g. "http://localhost:8000" or "https://api.example.com").
   */
  baseUrl: string

  /**
   * Optional API key for authenticating with Pool Engine when ApiKeyAuthProvider is configured.
   */
  apiKey?: string

  /**
   * Request timeout in milliseconds. Defaults to 5000ms.
   */
  timeoutMs: number

  /**
   * Whether the configuration is syntactically and logically valid.
   */
  isValid: boolean

  /**
   * Diagnostic message describing any configuration errors or warnings.
   */
  diagnostic?: string
}

/**
 * Validates whether a given string is a valid HTTP or HTTPS URL.
 */
export function isValidHttpUrl(urlString?: string | null): boolean {
  if (!urlString || typeof urlString !== "string") return false
  try {
    const url = new URL(urlString.trim())
    return url.protocol === "http:" || url.protocol === "https:"
  } catch {
    return false
  }
}

/**
 * Reads and validates Pool Engine configuration from environment variables or custom overrides.
 *
 * @param overrides Optional partial configuration to override environment defaults (useful in testing)
 */
export function getPoolEngineConfig(overrides?: Partial<PoolEngineConfig>): PoolEngineConfig {
  const envEnabledStr = (import.meta.env?.VITE_USE_POOL_ENGINE as string | undefined)?.trim().toLowerCase()
  const enabled = overrides?.enabled ?? (envEnabledStr === "true" || envEnabledStr === "1")

  const rawUrl = (overrides?.baseUrl ?? (import.meta.env?.VITE_POOL_ENGINE_URL as string | undefined) ?? "").trim()
  const apiKey = (overrides?.apiKey ?? (import.meta.env?.VITE_POOL_ENGINE_API_KEY as string | undefined))?.trim() || undefined
  const timeoutMs = overrides?.timeoutMs ?? (Number(import.meta.env?.VITE_POOL_ENGINE_TIMEOUT_MS) || 5000)

  let isValid = true
  let diagnostic: string | undefined

  if (enabled) {
    if (!rawUrl) {
      isValid = false
      diagnostic = "Pool Engine is enabled (VITE_USE_POOL_ENGINE=true), but VITE_POOL_ENGINE_URL is not configured."
    } else if (!isValidHttpUrl(rawUrl)) {
      isValid = false
      diagnostic = `Pool Engine URL '${rawUrl}' is invalid. Must be an absolute http:// or https:// URL.`
    }
  }

  // Remove trailing slashes for clean URI concatenation
  const baseUrl = rawUrl.replace(/\/+$/, "")

  return {
    enabled,
    baseUrl,
    apiKey,
    timeoutMs,
    isValid,
    diagnostic
  }
}

/**
 * Helper returning true only if Pool Engine is enabled and has valid configuration.
 */
export function isPoolEngineEnabled(): boolean {
  const config = getPoolEngineConfig()
  return config.enabled && config.isValid
}
