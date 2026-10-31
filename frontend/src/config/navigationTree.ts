/**
 * Centralized Navigation Tree & Hierarchy Configuration
 *
 * Defines deterministic logical parents for every screen in Waymate.
 * Guarantees that any screen reaches Home in at most 2-3 back presses.
 */

export interface RouteConfig {
  path: string
  pattern: RegExp
  title: string
  defaultParent: string
  maxDepthToHome: number
  /** Resolves contextual parent (e.g. whether Ride Details came from Search, My Trips, or Home) */
  resolveParent?: (pathname: string, state?: any) => string
}

export const NAVIGATION_TREE: RouteConfig[] = [
  // Root Dashboard
  {
    path: "/home",
    pattern: /^\/home\/?$/,
    title: "Home",
    defaultParent: "/home",
    maxDepthToHome: 0
  },

  // Level 1: Primary Features
  {
    path: "/rides/search",
    pattern: /^\/rides\/search\/?$/,
    title: "Find Rides",
    defaultParent: "/home",
    maxDepthToHome: 1
  },
  {
    path: "/rides/create",
    pattern: /^\/rides\/create\/?$/,
    title: "Offer a Ride",
    defaultParent: "/home",
    maxDepthToHome: 1
  },
  {
    path: "/rides",
    pattern: /^\/rides\/?$/,
    title: "My Trips",
    defaultParent: "/home",
    maxDepthToHome: 1
  },
  {
    path: "/activity",
    pattern: /^\/activity\/?$/,
    title: "Activity & Notifications",
    defaultParent: "/home",
    maxDepthToHome: 1
  },
  {
    path: "/profile",
    pattern: /^\/profile\/?$/,
    title: "Profile",
    defaultParent: "/home",
    maxDepthToHome: 1
  },

  // Level 2: Ride Details (Contextual parent: /rides/search, /rides, or /home)
  {
    path: "/rides/:rideId",
    pattern: /^\/rides\/[^/]+\/?$/,
    title: "Ride Details",
    defaultParent: "/home",
    maxDepthToHome: 2,
    resolveParent: (_pathname, state) => {
      if (state?.from === "search" || state?.returnTo === "/rides/search") {
        return "/rides/search"
      }
      if (state?.from === "my-rides" || state?.returnTo === "/rides") {
        return "/rides"
      }
      return "/home"
    }
  },

  // Level 2: Profile Sub-screens
  {
    path: "/profile/account",
    pattern: /^\/profile\/account\/?$/,
    title: "Edit Profile",
    defaultParent: "/profile",
    maxDepthToHome: 2
  },
  {
    path: "/profile/notifications",
    pattern: /^\/profile\/notifications\/?$/,
    title: "Notification Settings",
    defaultParent: "/profile",
    maxDepthToHome: 2
  },
  {
    path: "/profile/privacy",
    pattern: /^\/profile\/privacy\/?$/,
    title: "Privacy & Permissions",
    defaultParent: "/profile",
    maxDepthToHome: 2,
    resolveParent: (_pathname, state) => {
      if (state?.from === "signup") return "/signup"
      return "/profile"
    }
  },
  {
    path: "/profile/settings",
    pattern: /^\/profile\/settings\/?$/,
    title: "Settings",
    defaultParent: "/profile",
    maxDepthToHome: 2
  },

  // Level 2/3: Legal & DPDP Compliance
  {
    path: "/terms",
    pattern: /^\/terms\/?$/,
    title: "Terms of Service",
    defaultParent: "/profile/privacy",
    maxDepthToHome: 3,
    resolveParent: (_pathname, state) => {
      if (state?.from === "signup") return "/signup"
      return "/profile/privacy"
    }
  },
  {
    path: "/data-rights",
    pattern: /^\/data-rights\/?$/,
    title: "Data Rights",
    defaultParent: "/profile/privacy",
    maxDepthToHome: 3,
    resolveParent: (_pathname, state) => {
      if (state?.from === "profile") return "/profile"
      return "/profile/privacy"
    }
  },

  // Auth Screens
  {
    path: "/login",
    pattern: /^\/login\/?$/,
    title: "Log In",
    defaultParent: "/",
    maxDepthToHome: 2
  },
  {
    path: "/signup",
    pattern: /^\/signup\/?$/,
    title: "Sign Up",
    defaultParent: "/login",
    maxDepthToHome: 3
  },
  {
    path: "/forgot-password",
    pattern: /^\/forgot-password\/?$/,
    title: "Forgot Password",
    defaultParent: "/login",
    maxDepthToHome: 3
  },
  {
    path: "/onboarding",
    pattern: /^\/onboarding\/?$/,
    title: "Complete Profile",
    defaultParent: "/login",
    maxDepthToHome: 3
  }
]

/**
 * Finds the route config matching a given pathname.
 */
export function getRouteConfig(pathname: string): RouteConfig | undefined {
  const normalized = pathname.toLowerCase()
  return NAVIGATION_TREE.find(route => route.pattern.test(normalized))
}

/**
 * Returns the logical parent path for a given pathname and history state.
 * Never leaves the user stuck: defaults to "/home" for app routes or "/" for auth routes.
 */
export function getLogicalParent(pathname: string, state?: any): string {
  const config = getRouteConfig(pathname)
  if (!config) {
    return "/home"
  }
  if (config.resolveParent) {
    return config.resolveParent(pathname, state)
  }
  return config.defaultParent
}

/**
 * Calculates the number of back steps to reach /home from any pathname.
 */
export function calculateStepsToHome(pathname: string, state?: any): number {
  if (pathname === "/home" || pathname === "/") return 0

  let current = pathname
  let steps = 0
  const visited = new Set<string>()

  while (current !== "/home" && steps < 10) {
    visited.add(current)
    const next = getLogicalParent(current, state)
    steps++
    if (next === "/home") break
    if (visited.has(next)) break // cycle guard
    current = next
  }

  return steps
}
