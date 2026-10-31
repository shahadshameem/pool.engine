import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  getPoolEngineConfig,
  isValidHttpUrl
} from "../src/config/poolEngineConfig"
import {
  PoolEngineClient,
  PoolEngineClientError,
  PoolEngineDisabledError,
  PoolEngineConfigError,
  PoolEngineTimeoutError,
  PoolEngineAuthRequiredError,
  PoolEngineAuthError,
  PoolEngineForbiddenError,
  PoolEngineNotFoundError,
  PoolEngineConflictError,
  PoolEngineUnavailableError,
  type CreateHostRideInput,
  type CreateRideRequestInput,
  type ProposalDecisionInput,
  type TokenProvider
} from "../src/services/poolEngine/poolEngineClient"

describe("Pool Engine Integration — Client & Authentication Tests", () => {
  const mockToken = "mock_firebase_id_token_valid"
  const defaultMockTokenProvider: TokenProvider = vi.fn().mockResolvedValue(mockToken)

  beforeEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
  })

  describe("Configuration & URL Validation", () => {
    it("defaults to disabled when VITE_USE_POOL_ENGINE is not set", () => {
      const config = getPoolEngineConfig({ enabled: false, baseUrl: "" })
      expect(config.enabled).toBe(false)
    })

    it("correctly validates HTTP and HTTPS URLs", () => {
      expect(isValidHttpUrl("http://localhost:8000")).toBe(true)
      expect(isValidHttpUrl("https://pool-engine.example.com")).toBe(true)
      expect(isValidHttpUrl("https://api.example.com:8443/v1")).toBe(true)
      expect(isValidHttpUrl("ftp://invalid.com")).toBe(false)
      expect(isValidHttpUrl("not-a-url")).toBe(false)
      expect(isValidHttpUrl("")).toBe(false)
      expect(isValidHttpUrl(null)).toBe(false)
    })

    it("reports diagnostic when enabled without a base URL", () => {
      const config = getPoolEngineConfig({ enabled: true, baseUrl: "" })
      expect(config.enabled).toBe(true)
      expect(config.isValid).toBe(false)
      expect(config.diagnostic).toContain("VITE_POOL_ENGINE_URL is not configured")
    })

    it("reports diagnostic when enabled with a malformed URL", () => {
      const config = getPoolEngineConfig({ enabled: true, baseUrl: "invalid_url_string" })
      expect(config.enabled).toBe(true)
      expect(config.isValid).toBe(false)
      expect(config.diagnostic).toContain("is invalid")
    })

    it("strips trailing slashes from baseUrl for clean concatenation", () => {
      const config = getPoolEngineConfig({ enabled: true, baseUrl: "https://api.example.com///" })
      expect(config.baseUrl).toBe("https://api.example.com")
      expect(config.isValid).toBe(true)
    })
  })

  describe("Feature Flag & Configuration Guard", () => {
    it("refuses to make requests and throws PoolEngineDisabledError when disabled", async () => {
      const mockFetch = vi.fn()
      const client = new PoolEngineClient({ enabled: false, baseUrl: "http://localhost:8000" }, mockFetch)

      await expect(client.getHealth()).rejects.toThrow(PoolEngineDisabledError)
      expect(mockFetch).not.toHaveBeenCalled()
    })

    it("refuses to make requests and throws PoolEngineConfigError when URL is invalid", async () => {
      const mockFetch = vi.fn()
      const client = new PoolEngineClient({ enabled: true, baseUrl: "not-a-url" }, mockFetch)

      await expect(client.getHealth()).rejects.toThrow(PoolEngineConfigError)
      expect(mockFetch).not.toHaveBeenCalled()
    })
  })

  describe("Firebase ID Token Forwarding & Authentication", () => {
    const validConfig = {
      enabled: true,
      baseUrl: "http://localhost:8000",
      timeoutMs: 3000
    }

    it("forwards Authorization: Bearer <ID token> header for authenticated requests", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ ride_id: "ride_123", driver_id: "u1" })
      })

      const client = new PoolEngineClient(validConfig, mockFetch, defaultMockTokenProvider)
      await client.getHostRide("ride_123")

      expect(mockFetch).toHaveBeenCalledTimes(1)
      const [, init] = mockFetch.mock.calls[0]
      expect(init.headers["Authorization"]).toBe(`Bearer ${mockToken}`)
    })

    it("throws PoolEngineAuthRequiredError if no Firebase token is available", async () => {
      const mockFetch = vi.fn()
      const nullTokenProvider: TokenProvider = vi.fn().mockResolvedValue(null)
      const client = new PoolEngineClient(validConfig, mockFetch, nullTokenProvider)

      await expect(client.getHostRide("ride_123")).rejects.toBeInstanceOf(PoolEngineAuthRequiredError)
      expect(mockFetch).not.toHaveBeenCalled()
    })

    it("does not require authentication token for health checks", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ status: "ok", service: "pool-engine" })
      })

      const nullTokenProvider: TokenProvider = vi.fn().mockResolvedValue(null)
      const client = new PoolEngineClient(validConfig, mockFetch, nullTokenProvider)

      const health = await client.getHealth()
      expect(health.status).toBe("ok")
      expect(mockFetch).toHaveBeenCalledTimes(1)
      const [, init] = mockFetch.mock.calls[0]
      expect(init.headers["Authorization"]).toBeUndefined()
    })

    it("retries with refreshed token once when receiving 401", async () => {
      const tokenProvider = vi.fn()
        .mockResolvedValueOnce("token_stale")
        .mockResolvedValueOnce("token_refreshed")

      const mockFetch = vi.fn()
        .mockResolvedValueOnce({
          ok: false,
          status: 401,
          text: async () => JSON.stringify({ error: { code: "AUTHENTICATION_REQUIRED", message: "Token expired" } })
        })
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          text: async () => JSON.stringify({ ride_id: "ride_123", status: "SCHEDULED" })
        })

      const client = new PoolEngineClient(validConfig, mockFetch, tokenProvider)
      const res = await client.getHostRide("ride_123")

      expect(res.ride_id).toBe("ride_123")
      expect(mockFetch).toHaveBeenCalledTimes(2)
      expect(mockFetch.mock.calls[0][1].headers["Authorization"]).toBe("Bearer token_stale")
      expect(mockFetch.mock.calls[1][1].headers["Authorization"]).toBe("Bearer token_refreshed")
    })

    it("throws PoolEngineAuthError when 401 persists after token refresh attempt", async () => {
      const tokenProvider = vi.fn()
        .mockResolvedValueOnce("token_bad")
        .mockResolvedValueOnce("token_bad")

      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        text: async () => JSON.stringify({ error: { code: "AUTHENTICATION_REQUIRED", message: "Invalid token signature" } })
      })

      const client = new PoolEngineClient(validConfig, mockFetch, tokenProvider)

      await expect(client.getHostRide("ride_123")).rejects.toBeInstanceOf(PoolEngineAuthError)
    })
  })

  describe("Request Construction & Endpoint Verification", () => {
    const validConfig = {
      enabled: true,
      baseUrl: "http://localhost:8000",
      timeoutMs: 3000
    }

    it("constructs GET /v1/health request correctly", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ status: "ok", service: "pool-engine" })
      })

      const client = new PoolEngineClient(validConfig, mockFetch)
      const health = await client.getHealth()

      expect(health).toEqual({ status: "ok", service: "pool-engine" })
      expect(mockFetch).toHaveBeenCalledTimes(1)
      const [url, init] = mockFetch.mock.calls[0]
      expect(url).toBe("http://localhost:8000/v1/health")
      expect(init.method).toBe("GET")
      expect(init.headers.Accept).toBe("application/json")
      expect(init.body).toBeUndefined()
    })

    it("constructs POST /v1/host-rides request with exact payload", async () => {
      const payload: CreateHostRideInput = {
        driver_id: "drv_123",
        origin: { latitude: 8.5475, longitude: 76.9048 },
        destination: { latitude: 8.4900, longitude: 76.9530 },
        scheduled_departure_time: 1770000000,
        available_seats: 3,
        max_detour_seconds: 600
      }

      const mockResponse = {
        ride_id: "ride_abc",
        driver_id: "drv_123",
        vehicle_id: "veh_123",
        ...payload,
        direct_duration_seconds: 900,
        direct_distance_meters: 10500,
        status: "SCHEDULED",
        stops: []
      }

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 201,
        text: async () => JSON.stringify(mockResponse)
      })

      const client = new PoolEngineClient(validConfig, mockFetch, defaultMockTokenProvider)
      const res = await client.createHostRide(payload)

      expect(res.ride_id).toBe("ride_abc")
      const [url, init] = mockFetch.mock.calls[0]
      expect(url).toBe("http://localhost:8000/v1/host-rides")
      expect(init.method).toBe("POST")
      expect(init.headers["Content-Type"]).toBe("application/json")
      expect(init.headers["Authorization"]).toBe(`Bearer ${mockToken}`)
      expect(JSON.parse(init.body)).toEqual(payload)
    })

    it("constructs POST /v1/host-rides/{ride_id}/match request with request_id", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ proposals: [], total_matched: 0 })
      })

      const client = new PoolEngineClient(validConfig, mockFetch, defaultMockTokenProvider)
      await client.matchHostRide("ride_999", "req_555")

      const [url, init] = mockFetch.mock.calls[0]
      expect(url).toBe("http://localhost:8000/v1/host-rides/ride_999/match")
      expect(init.method).toBe("POST")
      expect(JSON.parse(init.body)).toEqual({ request_id: "req_555" })
    })

    it("constructs POST /v1/proposals/{proposal_id}/accept with idempotency-key", async () => {
      const mockDecision: ProposalDecisionInput = {
        user_id: "usr_host_1",
        role: "host",
        reason: "Accepted seat request"
      }

      const mockResult = {
        proposal_id: "prop_123",
        status: "CONFIRMED",
        host_accepted: true,
        traveller_accepted: true,
        is_confirmed: true,
        ride_id: "ride_123",
        message: "Proposal accepted"
      }

      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: async () => JSON.stringify(mockResult)
      })

      const client = new PoolEngineClient(validConfig, mockFetch, defaultMockTokenProvider)
      const res = await client.acceptProposal("prop_123", mockDecision, "idemp_abc_456")

      expect(res.is_confirmed).toBe(true)
      const [url, init] = mockFetch.mock.calls[0]
      expect(url).toBe("http://localhost:8000/v1/proposals/prop_123/accept")
      expect(init.headers["idempotency-key"]).toBe("idemp_abc_456")
      expect(JSON.parse(init.body)).toEqual(mockDecision)
    })
  })

  describe("Structured Status Code Handling", () => {
    const validConfig = {
      enabled: true,
      baseUrl: "http://localhost:8000",
      timeoutMs: 50
    }

    it("throws PoolEngineForbiddenError on 403 Forbidden", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 403,
        text: async () => JSON.stringify({ error: { code: "FORBIDDEN", message: "Ownership mismatch" } })
      })

      const client = new PoolEngineClient(validConfig, mockFetch, defaultMockTokenProvider)
      await expect(client.getHostRide("ride_other")).rejects.toBeInstanceOf(PoolEngineForbiddenError)
    })

    it("throws PoolEngineNotFoundError on 404 Not Found", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        text: async () => JSON.stringify({ error: { code: "NOT_FOUND", message: "Ride not found" } })
      })

      const client = new PoolEngineClient(validConfig, mockFetch, defaultMockTokenProvider)
      await expect(client.getHostRide("ride_nonexistent")).rejects.toBeInstanceOf(PoolEngineNotFoundError)
    })

    it("throws PoolEngineConflictError on 409 Conflict", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        text: async () => JSON.stringify({ error: { code: "CONFLICT", message: "Concurrent modification" } })
      })

      const client = new PoolEngineClient(validConfig, mockFetch, defaultMockTokenProvider)
      await expect(client.getHostRide("ride_concurrent")).rejects.toBeInstanceOf(PoolEngineConflictError)
    })

    it("throws PoolEngineUnavailableError on 503 Service Unavailable", async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        text: async () => JSON.stringify({ error: { code: "SERVICE_UNAVAILABLE", message: "Engine down" } })
      })

      const client = new PoolEngineClient(validConfig, mockFetch, defaultMockTokenProvider)
      await expect(client.getHostRide("ride_123")).rejects.toBeInstanceOf(PoolEngineUnavailableError)
    })

    it("throws PoolEngineUnavailableError on network failure", async () => {
      const mockFetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"))
      const client = new PoolEngineClient(validConfig, mockFetch, defaultMockTokenProvider)

      await expect(client.getHostRide("ride_123")).rejects.toBeInstanceOf(PoolEngineUnavailableError)
    })

    it("throws PoolEngineTimeoutError on request timeout", async () => {
      const mockFetch = vi.fn().mockImplementation((_url, init) => {
        return new Promise((_resolve, reject) => {
          if (init.signal) {
            init.signal.addEventListener("abort", () => {
              const abortErr = new Error("The operation was aborted")
              abortErr.name = "AbortError"
              reject(abortErr)
            })
          }
        })
      })

      const client = new PoolEngineClient({
        enabled: true,
        baseUrl: "http://localhost:8000",
        timeoutMs: 20
      }, mockFetch, defaultMockTokenProvider)

      await expect(client.getHostRide("ride_123")).rejects.toBeInstanceOf(PoolEngineTimeoutError)
    })
  })
})
