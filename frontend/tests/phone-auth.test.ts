import { describe, it, expect } from "vitest"
import { formatToE164 } from "../src/services/auth/authService"

describe("Uber-Style Phone OTP Authentication Service", () => {
  describe("formatToE164 phone formatting", () => {
    it("formats 10-digit Indian phone number with +91 prefix", () => {
      expect(formatToE164("9876543210")).toBe("+919876543210")
      expect(formatToE164("7012345678")).toBe("+917012345678")
    })

    it("cleans formatting spaces, dashes and parentheses", () => {
      expect(formatToE164("98765 43210")).toBe("+919876543210")
      expect(formatToE164("9876-543-210")).toBe("+919876543210")
      expect(formatToE164("(987) 654-3210")).toBe("+919876543210")
    })

    it("preserves already formatted +91 number", () => {
      expect(formatToE164("+919876543210")).toBe("+919876543210")
      expect(formatToE164("+91 98765 43210")).toBe("+919876543210")
    })

    it("handles 12-digit Indian numbers starting with 91 without plus", () => {
      expect(formatToE164("919876543210")).toBe("+919876543210")
    })

    it("preserves international numbers with country code prefix", () => {
      expect(formatToE164("+14155552671")).toBe("+14155552671")
      expect(formatToE164("+447911123456")).toBe("+447911123456")
    })

    it("returns empty string for empty input", () => {
      expect(formatToE164("")).toBe("")
    })
  })
})
