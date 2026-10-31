import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { isDevMockEnabled, setDevMockEnabled, clearDevMock } from "../src/utils/devMock"
import { defaultFirebaseTokenProvider, PoolEngineClient, PoolEngineAuthRequiredError } from "../src/services/poolEngine/poolEngineClient"

class MockLocalStorage {
  private store = new Map<string, string>()

  getItem(key: string): string | null {
    return this.store.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value))
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  clear(): void {
    this.store.clear()
  }
}

describe("Development Mock Authentication Security & Production Isolation", () => {
  const originalEnvDev = import.meta.env.DEV
  const mockStorage = new MockLocalStorage()

  beforeEach(() => {
    mockStorage.clear()
    ;(globalThis as any).localStorage = mockStorage
    ;(globalThis as any).window = {
      localStorage: mockStorage,
      location: new URL("http://localhost:5173/")
    }
  })

  afterEach(() => {
    ;(import.meta.env as any).DEV = originalEnvDev
    mockStorage.clear()
  })

  describe("Production Runtime Guardrails (import.meta.env.DEV === false)", () => {
    beforeEach(() => {
      ;(import.meta.env as any).DEV = false
    })

    it("strictly returns false even if localStorage has mock_user=true", () => {
      mockStorage.setItem("mock_user", "true")
      expect(isDevMockEnabled()).toBe(false)
    })

    it("actively purges residual mock_user from localStorage in production", () => {
      mockStorage.setItem("mock_user", "true")
      expect(mockStorage.getItem("mock_user")).toBe("true")

      const result = isDevMockEnabled()
      expect(result).toBe(false)
      expect(mockStorage.getItem("mock_user")).toBeNull()
    })

    it("strictly returns false even if URL contains ?mock=true", () => {
      ;(globalThis as any).window.location = new URL("http://localhost:5173/home?mock=true")
      expect(isDevMockEnabled()).toBe(false)
    })

    it("strictly rejects setDevMockEnabled(true) in production", () => {
      const success = setDevMockEnabled(true)
      expect(success).toBe(false)
      expect(mockStorage.getItem("mock_user")).toBeNull()
    })
  })

  describe("Development Runtime Behavior (import.meta.env.DEV === true)", () => {
    beforeEach(() => {
      ;(import.meta.env as any).DEV = true
    })

    it("returns false by default when no mock flags are present", () => {
      expect(isDevMockEnabled()).toBe(false)
    })

    it("returns true when localStorage has mock_user=true", () => {
      mockStorage.setItem("mock_user", "true")
      expect(isDevMockEnabled()).toBe(true)
    })

    it("returns true when URL contains ?mock=true", () => {
      ;(globalThis as any).window.location = new URL("http://localhost:5173/rides/search?mock=true")
      expect(isDevMockEnabled()).toBe(true)
    })

    it("allows enabling and clearing dev mock via helpers", () => {
      expect(setDevMockEnabled(true)).toBe(true)
      expect(isDevMockEnabled()).toBe(true)

      clearDevMock()
      expect(isDevMockEnabled()).toBe(false)
    })
  })

  describe("Backend & Token Isolation", () => {
    it("defaultFirebaseTokenProvider returns null when user is only in mock local storage", async () => {
      // In mock mode without genuine Firebase Auth, currentUser is null
      mockStorage.setItem("mock_user", "true")
      const token = await defaultFirebaseTokenProvider()
      expect(token).toBeNull()
    })

    it("PoolEngineClient rejects authenticated requests when only mock authentication exists", async () => {
      const client = new PoolEngineClient({
        enabled: true,
        baseUrl: "http://127.0.0.1:8000"
      })

      // Calling an endpoint requiring authentication without genuine Firebase token must throw PoolEngineAuthRequiredError
      await expect(client.createHostRide({
        pickup_location: { latitude: 8.5469, longitude: 76.9054 },
        dropoff_location: { latitude: 8.4875, longitude: 76.9528 },
        departure_time: 1731664800,
        available_seats: 3
      })).rejects.toThrow(PoolEngineAuthRequiredError)
    })
  })

  describe("Fail-Safe Exception Handling & Environment Robustness", () => {
    it("safely returns false if storage access throws a SecurityError (private mode)", () => {
      ;(import.meta.env as any).DEV = true
      vi.spyOn(mockStorage, "getItem").mockImplementation(() => {
        throw new Error("SecurityError: Access to storage is denied")
      })

      expect(isDevMockEnabled()).toBe(false)
    })

    it("safely handles setDevMockEnabled when storage writes throw an error", () => {
      ;(import.meta.env as any).DEV = true
      vi.spyOn(mockStorage, "setItem").mockImplementation(() => {
        throw new Error("QuotaExceededError")
      })

      const result = setDevMockEnabled(true)
      expect(result).toBe(false)
    })

    it("returns false in SSR environments where window is undefined", () => {
      ;(import.meta.env as any).DEV = true
      const win = (globalThis as any).window
      delete (globalThis as any).window

      try {
        expect(isDevMockEnabled()).toBe(false)
      } finally {
        ;(globalThis as any).window = win
      }
    })
  })
})
