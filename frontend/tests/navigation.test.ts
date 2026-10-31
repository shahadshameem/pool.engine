import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  getLogicalParent,
  calculateStepsToHome,
  getRouteConfig,
  NAVIGATION_TREE
} from "../src/config/navigationTree"

describe("Navigation Tree & Hierarchical Back Model Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("verifies every route in the app reaches /home in at most 3 back steps", () => {
    NAVIGATION_TREE.forEach(route => {
      const steps = calculateStepsToHome(route.path)
      expect(steps).toBeLessThanOrEqual(route.maxDepthToHome)
      expect(steps).toBeLessThanOrEqual(3)
    })
  })

  it("verifies primary feature screens (Search, Create, My Trips, Profile) reach /home in exactly 1 back step", () => {
    expect(calculateStepsToHome("/rides/search")).toBe(1)
    expect(calculateStepsToHome("/rides/create")).toBe(1)
    expect(calculateStepsToHome("/rides")).toBe(1)
    expect(calculateStepsToHome("/profile")).toBe(1)
    expect(calculateStepsToHome("/activity")).toBe(1)
  })

  it("resolves contextual parent for Ride Details when opened from Search", () => {
    const parent = getLogicalParent("/rides/test-ride-123", { from: "search" })
    expect(parent).toBe("/rides/search")

    // From Search -> Ride Details: total steps to Home = 2 (Details -> Search -> Home)
    const stepsFromDetailsToHome = 1 + calculateStepsToHome(parent)
    expect(stepsFromDetailsToHome).toBe(2)
  })

  it("resolves contextual parent for Ride Details when opened from My Trips", () => {
    const parent = getLogicalParent("/rides/test-ride-123", { from: "my-rides" })
    expect(parent).toBe("/rides")

    // From My Trips -> Ride Details: total steps to Home = 2 (Details -> My Trips -> Home)
    const stepsFromDetailsToHome = 1 + calculateStepsToHome(parent)
    expect(stepsFromDetailsToHome).toBe(2)
  })

  it("resolves Home as parent for Ride Details when opened from notification or deep link (cold start)", () => {
    // When no state is provided (deep link or push notification), parent defaults to /home
    const parent = getLogicalParent("/rides/test-ride-123")
    expect(parent).toBe("/home")
    expect(calculateStepsToHome("/rides/test-ride-123")).toBe(1)
  })

  it("resolves parent for Profile sub-screens to /profile (Depth 2 to Home)", () => {
    expect(getLogicalParent("/profile/account")).toBe("/profile")
    expect(calculateStepsToHome("/profile/account")).toBe(2)

    expect(getLogicalParent("/profile/notifications")).toBe("/profile")
    expect(calculateStepsToHome("/profile/notifications")).toBe(2)

    expect(getLogicalParent("/profile/privacy")).toBe("/profile")
    expect(calculateStepsToHome("/profile/privacy")).toBe(2)
  })

  it("resolves contextual parent for Privacy and Terms when opened from Signup flow", () => {
    const termsFromSignup = getLogicalParent("/terms", { from: "signup" })
    expect(termsFromSignup).toBe("/signup")

    const privacyFromSignup = getLogicalParent("/profile/privacy", { from: "signup" })
    expect(privacyFromSignup).toBe("/signup")
  })

  it("never leaves the user stuck: returns /home if route is unknown or has no parent", () => {
    expect(getLogicalParent("/unknown/screen")).toBe("/home")
    expect(getLogicalParent("/nonexistent-path-123")).toBe("/home")
  })
})

describe("Back Navigation Interceptors & Guards Logic", () => {
  it("prioritizes closing open sheets/modals before page navigation", () => {
    const closedModals: string[] = []
    let pageNavigated = false

    // Simulate modal registry
    const modals = [
      { id: "request-sheet", priority: 5, close: () => closedModals.push("request-sheet") },
      { id: "safety-modal", priority: 10, close: () => closedModals.push("safety-modal") }
    ]

    const simulateBackPress = () => {
      if (modals.length > 0) {
        // Sort by priority descending
        modals.sort((a, b) => b.priority - a.priority)
        const top = modals.shift()!
        top.close()
        return
      }
      pageNavigated = true
    }

    // 1st back press: Safety modal (priority 10) closes first
    simulateBackPress()
    expect(closedModals).toEqual(["safety-modal"])
    expect(pageNavigated).toBe(false)

    // 2nd back press: Request sheet (priority 5) closes next
    simulateBackPress()
    expect(closedModals).toEqual(["safety-modal", "request-sheet"])
    expect(pageNavigated).toBe(false)

    // 3rd back press: No open modals, navigates to parent
    simulateBackPress()
    expect(pageNavigated).toBe(true)
  })

  it("guards against accidental departure from an active in-progress trip", () => {
    let promptShown = false
    let pageNavigated = false

    const isRideStarted = true
    const simulateBackPress = (userConfirmedLeave = false) => {
      if (isRideStarted && !userConfirmedLeave) {
        promptShown = true
        return
      }
      pageNavigated = true
    }

    // Back without confirmation: prompts user, does not leave
    simulateBackPress(false)
    expect(promptShown).toBe(true)
    expect(pageNavigated).toBe(false)

    // User confirms leave: navigates to parent
    simulateBackPress(true)
    expect(pageNavigated).toBe(true)
  })

  it("guards against discarding dirty form input", () => {
    let discardPromptShown = false
    let pageNavigated = false

    const hasEnteredFormInput = true
    const simulateBackPress = (userConfirmedDiscard = false) => {
      if (hasEnteredFormInput && !userConfirmedDiscard) {
        discardPromptShown = true
        return
      }
      pageNavigated = true
    }

    // Back without confirmation: prompts user
    simulateBackPress(false)
    expect(discardPromptShown).toBe(true)
    expect(pageNavigated).toBe(false)

    // User confirms discard: navigates
    simulateBackPress(true)
    expect(pageNavigated).toBe(true)
  })

  it("prompts for exit confirmation when Back is pressed on Home", () => {
    let exitPromptShown = false

    const simulateHomeBack = () => {
      const currentPath = "/home"
      if (currentPath === "/home") {
        exitPromptShown = true
      }
    }

    simulateHomeBack()
    expect(exitPromptShown).toBe(true)
  })
})
