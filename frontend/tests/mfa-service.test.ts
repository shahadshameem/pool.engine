import { describe, it, expect, vi } from "vitest"
import { formatToE164, mfaService } from "../src/services/auth/mfaService"

describe("SMS Multi-Factor Authentication (MFA) Service & Unit Tests", () => {
  describe("E.164 Phone Number Formatting", () => {
    it("formats a standard 10-digit Indian mobile number to +91XXXXXXXXXX", () => {
      expect(formatToE164("9876543210")).toBe("+919876543210")
      expect(formatToE164("9495816772")).toBe("+919495816772")
    })

    it("strips whitespace, dashes, and parentheses", () => {
      expect(formatToE164("+91 (987) 654-3210")).toBe("+919876543210")
      expect(formatToE164("98765 43210")).toBe("+919876543210")
    })

    it("handles 12-digit numbers starting with 91", () => {
      expect(formatToE164("919876543210")).toBe("+919876543210")
    })

    it("preserves international numbers already with leading plus", () => {
      expect(formatToE164("+14155552671")).toBe("+14155552671")
    })
  })

  describe("MFA Enrollment State Invariants", () => {
    it("returns false for isMfaEnrolled when user is null or undefined", () => {
      expect(mfaService.isMfaEnrolled(null)).toBe(false)
      expect(mfaService.getEnrolledFactors(null)).toEqual([])
    })

    it("detects multiFactor enrolledFactors accurately on mock user", () => {
      const mockUnenrolledUser: any = {
        multiFactor: {
          enrolledFactors: []
        }
      }
      expect(mfaService.isMfaEnrolled(mockUnenrolledUser)).toBe(false)
      expect(mfaService.getEnrolledFactors(mockUnenrolledUser)).toEqual([])

      const mockEnrolledUser: any = {
        multiFactor: {
          enrolledFactors: [
            {
              uid: "factor-123",
              displayName: "Primary Phone",
              factorId: "phone",
              phoneNumber: "+919876543210"
            }
          ]
        }
      }
      expect(mfaService.isMfaEnrolled(mockEnrolledUser)).toBe(true)
      expect(mfaService.getEnrolledFactors(mockEnrolledUser)).toHaveLength(1)
      expect(mfaService.getEnrolledFactors(mockEnrolledUser)[0].phoneNumber).toBe("+919876543210")
    })

    it("safely handles getResolver for non-MFA errors", () => {
      expect(mfaService.getResolver(null)).toBeNull()
      expect(mfaService.getResolver({ code: "auth/invalid-credential" })).toBeNull()
    })
  })
})
