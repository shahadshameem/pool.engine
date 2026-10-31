/**
 * Development & Testing Mock Authentication Utility
 *
 * SECURITY MANDATE:
 * Mock authentication and bypass flags MUST NEVER be allowed or active in production builds.
 * Under production (import.meta.env.PROD === true || !import.meta.env.DEV), this strictly returns false,
 * preventing any fake or bypassed authenticated session in production runtime.
 */

/**
 * Returns true if mock/demo authentication mode is permitted and active in the current environment.
 * In production builds, this ALWAYS returns false and cleans up any stale local storage keys.
 */
export function isDevMockEnabled(): boolean {
  // 1. Strict production guard: Vite compiles import.meta.env.DEV as a constant boolean
  if (!import.meta.env.DEV) {
    // Defense-in-depth: If a user has a leftover mock_user key in production, purge it immediately
    if (typeof window !== "undefined" && window.localStorage) {
      try {
        if (localStorage.getItem("mock_user")) {
          localStorage.removeItem("mock_user")
          console.warn("[Security] Purged invalid development mock key from production storage.")
        }
      } catch {
        // Storage access restricted; fail safe
      }
    }
    return false
  }

  // 2. SSR/Node safety
  if (typeof window === "undefined") {
    return false
  }

  // 3. In development environments only: check localStorage or query parameter
  try {
    const hasStorageFlag = localStorage.getItem("mock_user") === "true"
    const hasQueryFlag = window.location.search.includes("mock=true")
    return hasStorageFlag || hasQueryFlag
  } catch {
    return false
  }
}

/**
 * Safely sets the development mock user flag. Strictly prohibited in production.
 */
export function setDevMockEnabled(enabled: boolean): boolean {
  if (!import.meta.env.DEV) {
    console.error("[Security] Attempted to enable mock authentication in a production build. Action rejected.")
    return false
  }

  if (typeof window === "undefined" || !window.localStorage) {
    return false
  }

  try {
    if (enabled) {
      localStorage.setItem("mock_user", "true")
    } else {
      localStorage.removeItem("mock_user")
    }
    return true
  } catch {
    return false
  }
}

/**
 * Completely clears any development mock authentication state.
 */
export function clearDevMock(): void {
  if (typeof window !== "undefined" && window.localStorage) {
    try {
      localStorage.removeItem("mock_user")
    } catch {
      // ignore
    }
  }
}
