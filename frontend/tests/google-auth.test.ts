import { describe, it, expect, vi, beforeEach } from "vitest"

// Hoist mock state
const mockGetDoc = vi.fn()
const mockSetDoc = vi.fn()
const mockDoc = vi.fn()
const mockServerTimestamp = vi.fn(() => "MOCK_TIMESTAMP")
const mockSignInWithPopup = vi.fn()
const mockSignInWithRedirect = vi.fn()
const mockGetRedirectResult = vi.fn()
const mockFirebaseSignOut = vi.fn()

vi.mock("firebase/firestore", () => ({
  doc: (...args: any[]) => mockDoc(...args),
  getDoc: (...args: any[]) => mockGetDoc(...args),
  setDoc: (...args: any[]) => mockSetDoc(...args),
  serverTimestamp: () => mockServerTimestamp(),
  getFirestore: vi.fn(),
}))

vi.mock("firebase/auth", () => {
  class MockGoogleAuthProvider {
    setCustomParameters = vi.fn()
  }
  return {
    GoogleAuthProvider: MockGoogleAuthProvider,
    signInWithPopup: (...args: any[]) => mockSignInWithPopup(...args),
    signInWithRedirect: (...args: any[]) => mockSignInWithRedirect(...args),
    getRedirectResult: (...args: any[]) => mockGetRedirectResult(...args),
    signOut: (...args: any[]) => mockFirebaseSignOut(...args),
    createUserWithEmailAndPassword: vi.fn(),
    signInWithEmailAndPassword: vi.fn(),
    sendEmailVerification: vi.fn(),
    sendPasswordResetEmail: vi.fn(),
    signInWithCustomToken: vi.fn(),
    getAuth: vi.fn(() => ({ currentUser: { uid: "redirect_user_1", email: "redirect@test.com" } }))
  }
})

vi.mock("../src/config/firebase", () => ({
  auth: { currentUser: { uid: "current_user_1", email: "current@test.com" } },
  db: {}
}))

import { authService } from "../src/services/auth/authService"

describe("Google Sign-In & Authentication Service Unit Tests", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockDoc.mockReturnValue({ path: "users/test-uid" })
  })

  describe("signInWithGoogle popup flow", () => {
    it("successfully logs in with Google popup and initializes user profile", async () => {
      const mockUser = {
        uid: "google-uid-123",
        email: "student@cet.ac.in",
        displayName: "Anjali Menon",
        photoURL: "https://example.com/avatar.jpg"
      }
      mockSignInWithPopup.mockResolvedValueOnce({ user: mockUser })
      mockGetDoc.mockResolvedValueOnce({
        exists: () => false
      })

      const result = await authService.signInWithGoogle()

      expect(mockSignInWithPopup).toHaveBeenCalledTimes(1)
      expect(result.user).toEqual(mockUser)
      expect(mockSetDoc).toHaveBeenCalledWith(
        { path: "users/test-uid" },
        expect.objectContaining({
          uid: "google-uid-123",
          name: "Anjali Menon",
          email: "student@cet.ac.in",
          phone: "",
          emailVerified: false,
          collegeVerified: false,
          accountStatus: "active"
        })
      )
    })

    it("falls back to signInWithRedirect when popup is blocked by the browser", async () => {
      const popupBlockedErr = new Error("Popup blocked")
      ;(popupBlockedErr as any).code = "auth/popup-blocked"
      mockSignInWithPopup.mockRejectedValueOnce(popupBlockedErr)
      mockSignInWithRedirect.mockResolvedValueOnce(undefined)

      const result = await authService.signInWithGoogle()

      expect(mockSignInWithPopup).toHaveBeenCalledTimes(1)
      expect(mockSignInWithRedirect).toHaveBeenCalledTimes(1)
      expect(result.user).toBeDefined()
      expect(result.user.uid).toBe("current_user_1")
    })

    it("falls back to signInWithRedirect when popup request is cancelled", async () => {
      const cancelledErr = new Error("Cancelled")
      ;(cancelledErr as any).code = "auth/cancelled-popup-request"
      mockSignInWithPopup.mockRejectedValueOnce(cancelledErr)
      mockSignInWithRedirect.mockResolvedValueOnce(undefined)

      const result = await authService.signInWithGoogle()

      expect(mockSignInWithPopup).toHaveBeenCalledTimes(1)
      expect(mockSignInWithRedirect).toHaveBeenCalledTimes(1)
      expect(result.user).toBeDefined()
    })

    it("throws friendly error when user closes the popup", async () => {
      const closedErr = new Error("User closed popup")
      ;(closedErr as any).code = "auth/popup-closed-by-user"
      mockSignInWithPopup.mockRejectedValueOnce(closedErr)

      await expect(authService.signInWithGoogle()).rejects.toMatchObject({
        code: "auth/popup-closed-by-user",
        message: "Sign-in was cancelled."
      })
      expect(mockSignInWithRedirect).not.toHaveBeenCalled()
    })

    it("throws friendly error on network failure", async () => {
      const netErr = new Error("Network error")
      ;(netErr as any).code = "auth/network-request-failed"
      mockSignInWithPopup.mockRejectedValueOnce(netErr)

      await expect(authService.signInWithGoogle()).rejects.toMatchObject({
        code: "auth/network-request-failed",
        message: expect.stringContaining("Network connection failed")
      })
    })

    it("throws clear error on unauthorized domain", async () => {
      const domainErr = new Error("Domain not authorized")
      ;(domainErr as any).code = "auth/unauthorized-domain"
      mockSignInWithPopup.mockRejectedValueOnce(domainErr)

      await expect(authService.signInWithGoogle()).rejects.toMatchObject({
        code: "auth/unauthorized-domain",
        message: expect.stringContaining("Authorized Domains")
      })
    })
  })

  describe("handleRedirectResult", () => {
    it("returns null if no redirect operation was pending", async () => {
      mockGetRedirectResult.mockResolvedValueOnce(null)

      const result = await authService.handleRedirectResult()
      expect(result).toBeNull()
    })

    it("processes user and creates profile if redirect result is present", async () => {
      const redirectUser = {
        uid: "redirect-user-789",
        email: "redirect@cet.ac.in",
        displayName: "Rahul Sharma"
      }
      mockGetRedirectResult.mockResolvedValueOnce({ user: redirectUser })
      mockGetDoc.mockResolvedValueOnce({ exists: () => false })

      const result = await authService.handleRedirectResult()
      expect(result).toEqual(redirectUser)
      expect(mockSetDoc).toHaveBeenCalledWith(
        { path: "users/test-uid" },
        expect.objectContaining({
          uid: "redirect-user-789",
          name: "Rahul Sharma",
          email: "redirect@cet.ac.in"
        })
      )
    })

    it("safely returns null if getRedirectResult throws an error", async () => {
      mockGetRedirectResult.mockRejectedValueOnce(new Error("Redirect error"))

      const result = await authService.handleRedirectResult()
      expect(result).toBeNull()
    })
  })

  describe("ensureUserProfile profile synchronization", () => {
    it("does not overwrite custom user name if existing profile has one", async () => {
      const mockUser = {
        uid: "user-123",
        email: "user@example.com",
        displayName: "Google Name"
      } as any

      mockGetDoc.mockResolvedValueOnce({
        exists: () => true,
        data: () => ({
          name: "Custom Prior Name",
          email: "user@example.com",
          college: "CET"
        })
      })

      await authService.ensureUserProfile(mockUser)

      // Since name was already set and not "Student" or "User", setDoc should not update it
      expect(mockSetDoc).not.toHaveBeenCalled()
    })

    it("updates generic 'Student' name with Google displayName on login", async () => {
      const mockUser = {
        uid: "user-456",
        email: "student@cet.ac.in",
        displayName: "Arun K"
      } as any

      mockGetDoc.mockResolvedValueOnce({
        exists: () => true,
        data: () => ({
          name: "Student",
          email: "student@cet.ac.in"
        })
      })

      await authService.ensureUserProfile(mockUser)

      expect(mockSetDoc).toHaveBeenCalledWith(
        { path: "users/test-uid" },
        expect.objectContaining({
          name: "Arun K"
        }),
        { merge: true }
      )
    })

    it("derives name from email prefix if displayName is missing", async () => {
      const mockUser = {
        uid: "user-789",
        email: "karthik.subbaraj@example.com",
        displayName: null
      } as any

      mockGetDoc.mockResolvedValueOnce({ exists: () => false })

      await authService.ensureUserProfile(mockUser)

      expect(mockSetDoc).toHaveBeenCalledWith(
        { path: "users/test-uid" },
        expect.objectContaining({
          name: "karthik.subbaraj"
        })
      )
    })
  })

  describe("normalizeErrorMessage mapping", () => {
    it("maps recognized Firebase auth error codes correctly", () => {
      expect(authService.normalizeErrorMessage({ code: "auth/popup-closed-by-user" }))
        .toBe("Sign-in was cancelled.")
      expect(authService.normalizeErrorMessage({ code: "auth/popup-blocked" }))
        .toContain("blocked by your browser")
      expect(authService.normalizeErrorMessage({ code: "auth/network-request-failed" }))
        .toContain("Network connection failed")
      expect(authService.normalizeErrorMessage({ code: "auth/unauthorized-domain" }))
        .toContain("Authorized Domains")
      expect(authService.normalizeErrorMessage({ code: "auth/user-disabled" }))
        .toContain("disabled")
      expect(authService.normalizeErrorMessage({ code: "auth/account-exists-with-different-credential" }))
        .toContain("already exists")
    })

    it("falls back to error message or default text for unknown codes", () => {
      expect(authService.normalizeErrorMessage({ code: "unknown/code", message: "Custom err" }))
        .toBe("Custom err")
      expect(authService.normalizeErrorMessage({}))
        .toBe("Failed to sign in. Please try again.")
    })
  })
})
