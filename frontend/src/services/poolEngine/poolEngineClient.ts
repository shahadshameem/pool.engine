/**
 * Pool Engine API Client
 *
 * Implements typed, verified communication with the separate Python/FastAPI Pool Engine backend.
 *
 * Safety & Security Invariants:
 * 1. Honors the feature flag: refuses to make network requests when VITE_USE_POOL_ENGINE is disabled.
 * 2. Applies timeouts to prevent hanging promises.
 * 3. Does not log tokens, keys, or sensitive payload data.
 * 4. Authentication: End-user requests authenticate by forwarding verified Firebase ID tokens
 *    via `Authorization: Bearer <ID token>`.
 * 5. Automatic token refresh: On 401 responses, the client requests a refreshed token and retries once.
 */

import {
  type PoolEngineConfig,
  getPoolEngineConfig
} from "../../config/poolEngineConfig"

// ============================================================================
// Canonical Pool Engine Domain & DTO Contracts (Verified from Backend Schemas)
// ============================================================================

export interface GeoCoordinate {
  latitude: number
  longitude: number
}

export interface RouteStopDTO {
  stop_id: string
  location: GeoCoordinate
  stop_type: "PICKUP" | "DROPOFF" | string
  scheduled_time: number
  status: string
  passengers: string[]
}

export interface CreateHostRideInput {
  driver_id: string
  origin: GeoCoordinate
  destination: GeoCoordinate
  scheduled_departure_time: number
  available_seats?: number
  max_detour_seconds?: number
  vehicle_id?: string | null
  ride_id?: string | null
}

export interface HostRideDTO {
  ride_id: string
  driver_id: string
  vehicle_id: string
  origin: GeoCoordinate
  destination: GeoCoordinate
  scheduled_departure_time: number
  available_seats: number
  max_detour_seconds: number
  direct_duration_seconds: number
  direct_distance_meters: number
  status: string
  stops: RouteStopDTO[]
}

export interface ProposalDTO {
  proposal_id: string
  ride_id: string
  request_id?: string | null
  host_id?: string | null
  traveller_id?: string | null
  seat_count: number
  submitted_at: number
  expires_at: number
  status: string
  host_accepted: boolean
  traveller_accepted: boolean
  is_confirmed: boolean
  pickup_location?: GeoCoordinate | null
  dropoff_location?: GeoCoordinate | null
  is_masked?: boolean
}

export interface MatchHostRideResult {
  proposals: ProposalDTO[]
  total_matched: number
}

export interface ProposalDecisionInput {
  user_id?: string | null
  role?: "host" | "traveller" | string | null
  idempotency_token?: string | null
  reason?: string | null
  current_time?: number | null
}

export interface ProposalDecisionResult {
  proposal_id: string
  status: string
  host_accepted: boolean
  traveller_accepted: boolean
  is_confirmed: boolean
  ride_id: string
  expires_at?: number | null
  message: string
}

export interface CreateRideRequestInput {
  request_id?: string
  user_id: string
  pickup_location: GeoCoordinate
  dropoff_location: GeoCoordinate
  seat_count?: number
  earliest_pickup_time: number
  latest_dropoff_time: number
  direct_distance_meters?: number | null
  direct_duration_seconds?: number | null
}

export interface RideRequestDTO {
  request_id: string
  user_id: string
  pickup_location: GeoCoordinate
  dropoff_location: GeoCoordinate
  seat_count: number
  earliest_pickup_time: number
  latest_dropoff_time: number
  direct_distance_meters?: number | null
  direct_duration_seconds?: number | null
  status: string
  created_at?: number
}

export interface CancelRideRequestInput {
  reason?: string
  idempotency_token?: string
}

export interface EnRouteJoinInput {
  request_id: string
  current_time?: number | null
}

export interface EnRouteJoinResult {
  eligible: boolean
  rejection_reason?: string | null
  proposal?: ProposalDTO | null
  estimated_pickup_time?: number | null
  estimated_dropoff_time?: number | null
  host_detour_seconds: number
  message: string
}

export interface HealthResponse {
  status: string
  service: string
}

export interface ReadinessResponse {
  ready: boolean
  [key: string]: unknown
}

export interface ErrorDetail {
  field?: string
  issue: string
}

export interface ErrorBody {
  code: string
  message: string
  details?: ErrorDetail[]
}

export interface ErrorEnvelope {
  error: ErrorBody
}

// ============================================================================
// Structured Client Exceptions
// ============================================================================

export class PoolEngineClientError extends Error {
  readonly code: string
  readonly status?: number
  readonly details: ErrorDetail[]

  constructor(
    message: string,
    code: string = "CLIENT_ERROR",
    status?: number,
    details: ErrorDetail[] = []
  ) {
    super(message)
    this.name = "PoolEngineClientError"
    this.code = code
    this.status = status
    this.details = details
  }
}

export class PoolEngineDisabledError extends PoolEngineClientError {
  constructor() {
    super("Pool Engine integration is disabled by feature flag (VITE_USE_POOL_ENGINE=false)", "FEATURE_DISABLED")
    this.name = "PoolEngineDisabledError"
  }
}

export class PoolEngineConfigError extends PoolEngineClientError {
  constructor(message: string) {
    super(message, "INVALID_CONFIG")
    this.name = "PoolEngineConfigError"
  }
}

export class PoolEngineTimeoutError extends PoolEngineClientError {
  constructor(timeoutMs: number) {
    super(`Pool Engine request timed out after ${timeoutMs}ms`, "TIMEOUT", 408)
    this.name = "PoolEngineTimeoutError"
  }
}

export class PoolEngineAuthRequiredError extends PoolEngineClientError {
  constructor(message: string = "Authentication required. Please sign in to continue.") {
    super(message, "AUTHENTICATION_REQUIRED", 401)
    this.name = "PoolEngineAuthRequiredError"
  }
}

export class PoolEngineAuthError extends PoolEngineClientError {
  constructor(
    message: string = "Authentication failed with Pool Engine.",
    code: string = "UNAUTHENTICATED",
    status: number = 401,
    details: ErrorDetail[] = []
  ) {
    super(message, code, status, details)
    this.name = "PoolEngineAuthError"
  }
}

export class PoolEngineForbiddenError extends PoolEngineClientError {
  constructor(
    message: string = "You are not authorized to perform this operation on Pool Engine.",
    code: string = "FORBIDDEN",
    status: number = 403,
    details: ErrorDetail[] = []
  ) {
    super(message, code, status, details)
    this.name = "PoolEngineForbiddenError"
  }
}

export class PoolEngineNotFoundError extends PoolEngineClientError {
  constructor(
    message: string = "The requested resource was not found in Pool Engine.",
    code: string = "NOT_FOUND",
    status: number = 404,
    details: ErrorDetail[] = []
  ) {
    super(message, code, status, details)
    this.name = "PoolEngineNotFoundError"
  }
}

export class PoolEngineConflictError extends PoolEngineClientError {
  constructor(
    message: string = "The requested operation conflicts with existing Pool Engine state.",
    code: string = "CONFLICT",
    status: number = 409,
    details: ErrorDetail[] = []
  ) {
    super(message, code, status, details)
    this.name = "PoolEngineConflictError"
  }
}

export class PoolEngineUnavailableError extends PoolEngineClientError {
  constructor(
    message: string = "Pool Engine backend is currently unavailable.",
    code: string = "SERVICE_UNAVAILABLE",
    status: number = 503,
    details: ErrorDetail[] = []
  ) {
    super(message, code, status, details)
    this.name = "PoolEngineUnavailableError"
  }
}

// ============================================================================
// Token Provider Definition
// ============================================================================

export type TokenProvider = (forceRefresh?: boolean) => Promise<string | null>

export const defaultFirebaseTokenProvider: TokenProvider = async (forceRefresh = false) => {
  try {
    const { auth } = await import("../../config/firebase")
    if (typeof auth !== "undefined" && auth && auth.currentUser) {
      return await auth.currentUser.getIdToken(forceRefresh)
    }
  } catch {
    return null
  }
  return null
}

// ============================================================================
// Pool Engine Client Class
// ============================================================================

export class PoolEngineClient {
  private config: PoolEngineConfig
  private fetchFn: typeof fetch
  private tokenProvider: TokenProvider

  constructor(
    customConfig?: Partial<PoolEngineConfig>,
    customFetch?: typeof fetch,
    tokenProvider?: TokenProvider
  ) {
    this.config = getPoolEngineConfig(customConfig)
    this.fetchFn = customFetch || (
      typeof globalThis !== "undefined" && typeof globalThis.fetch === "function"
        ? globalThis.fetch.bind(globalThis)
        : (fetch as unknown as typeof fetch)
    )
    this.tokenProvider = tokenProvider || defaultFirebaseTokenProvider
  }

  /**
   * Internal request executor with timeout, authentication, error translation, and safety guards.
   */
  private async request<T>(
    method: "GET" | "POST" | "PATCH" | "DELETE",
    path: string,
    options: {
      body?: unknown
      headers?: Record<string, string>
      skipFeatureFlagCheck?: boolean
      requiresAuth?: boolean
    } = {}
  ): Promise<T> {
    // 1. Guard against disabled feature flag
    if (!options.skipFeatureFlagCheck && !this.config.enabled) {
      throw new PoolEngineDisabledError()
    }

    // 2. Validate configuration
    if (!this.config.isValid || !this.config.baseUrl) {
      throw new PoolEngineConfigError(
        this.config.diagnostic || "Pool Engine base URL is missing or invalid."
      )
    }

    const url = `${this.config.baseUrl}${path.startsWith("/") ? path : `/${path}`}`

    // 3. Assemble headers
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...options.headers
    }

    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json"
    }

    // Attach API key if explicitly configured (for server-to-server or test setups)
    if (this.config.apiKey) {
      headers["x-api-key"] = this.config.apiKey
    }

    // 4. Handle Firebase Authentication Token Forwarding
    const requiresAuth = options.requiresAuth !== false
    let currentToken: string | null = null

    if (requiresAuth) {
      currentToken = await this.tokenProvider(false)
      if (!currentToken) {
        throw new PoolEngineAuthRequiredError(
          "Authentication required: No active Firebase ID token found. Please sign in to Waymate."
        )
      }
      headers["Authorization"] = `Bearer ${currentToken}`
    }

    // 5. Helper to execute the fetch with timeout
    const executeFetch = async (reqHeaders: Record<string, string>): Promise<Response> => {
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), this.config.timeoutMs)
      try {
        const res = await this.fetchFn(url, {
          method,
          headers: reqHeaders,
          body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
          signal: controller.signal
        })
        clearTimeout(timer)
        return res
      } catch (err: unknown) {
        clearTimeout(timer)
        if (err instanceof Error && err.name === "AbortError") {
          throw new PoolEngineTimeoutError(this.config.timeoutMs)
        }
        const networkMessage = err instanceof Error ? err.message : "Network error"
        throw new PoolEngineUnavailableError(
          `Failed to communicate with Pool Engine: ${networkMessage}`,
          "NETWORK_ERROR",
          503
        )
      }
    }

    let response = await executeFetch(headers)

    // 6. Token refresh handling on 401
    if (response.status === 401 && requiresAuth) {
      try {
        const refreshedToken = await this.tokenProvider(true)
        if (refreshedToken && refreshedToken !== currentToken) {
          const retryHeaders = { ...headers, Authorization: `Bearer ${refreshedToken}` }
          response = await executeFetch(retryHeaders)
        }
      } catch {
        // If refresh fails, fall through to standard 401 error parsing below
      }
    }

    // 7. Parse response body safely
    const text = await response.text()
    let data: unknown = null
    if (text) {
      try {
        data = JSON.parse(text)
      } catch {
        // Non-JSON response
      }
    }

    // 8. Handle HTTP error statuses with structured error mapping
    if (!response.ok) {
      let errorCode = `HTTP_${response.status}`
      let errorMessage = `Pool Engine request failed with HTTP status ${response.status}`
      let errorDetails: ErrorDetail[] = []

      if (data && typeof data === "object" && "error" in data) {
        const envelope = data as ErrorEnvelope
        errorCode = envelope.error.code || errorCode
        errorMessage = envelope.error.message || errorMessage
        errorDetails = envelope.error.details || []
      }

      switch (response.status) {
        case 401:
          throw new PoolEngineAuthError(errorMessage, errorCode, 401, errorDetails)
        case 403:
          throw new PoolEngineForbiddenError(errorMessage, errorCode, 403, errorDetails)
        case 404:
          throw new PoolEngineNotFoundError(errorMessage, errorCode, 404, errorDetails)
        case 409:
          throw new PoolEngineConflictError(errorMessage, errorCode, 409, errorDetails)
        case 500:
        case 502:
        case 503:
        case 504:
          throw new PoolEngineUnavailableError(errorMessage, errorCode, response.status, errorDetails)
        default:
          throw new PoolEngineClientError(errorMessage, errorCode, response.status, errorDetails)
      }
    }

    return data as T
  }

  // ==========================================================================
  // Health & Diagnostic Endpoints (No authentication required by backend)
  // ==========================================================================

  /**
   * General liveness and identity check. Verified: GET /v1/health
   */
  async getHealth(): Promise<HealthResponse> {
    return this.request<HealthResponse>("GET", "/v1/health", { requiresAuth: false })
  }

  /**
   * Kubernetes/container liveness probe. Verified: GET /v1/health/liveness
   */
  async getLiveness(): Promise<HealthResponse> {
    return this.request<HealthResponse>("GET", "/v1/health/liveness", { requiresAuth: false })
  }

  /**
   * Readiness probe verifying routing and storage backends. Verified: GET /v1/health/readiness
   */
  async getReadiness(): Promise<ReadinessResponse> {
    return this.request<ReadinessResponse>("GET", "/v1/health/readiness", { requiresAuth: false })
  }

  // ==========================================================================
  // Host Ride Management
  // ==========================================================================

  /**
   * Registers a host's planned commute or journey. Verified: POST /v1/host-rides
   */
  async createHostRide(input: CreateHostRideInput): Promise<HostRideDTO> {
    return this.request<HostRideDTO>("POST", "/v1/host-rides", { body: input, requiresAuth: true })
  }

  /**
   * Retrieves public details of a host ride. Verified: GET /v1/host-rides/{ride_id}
   */
  async getHostRide(rideId: string): Promise<HostRideDTO> {
    return this.request<HostRideDTO>("GET", `/v1/host-rides/${encodeURIComponent(rideId)}`, { requiresAuth: true })
  }

  /**
   * Runs single-ride insertion matching against active pending requests.
   * Verified: POST /v1/host-rides/{ride_id}/match
   */
  async matchHostRide(rideId: string, requestId?: string): Promise<MatchHostRideResult> {
    const body = requestId ? { request_id: requestId } : {}
    return this.request<MatchHostRideResult>("POST", `/v1/host-rides/${encodeURIComponent(rideId)}/match`, {
      body,
      requiresAuth: true
    })
  }

  // ==========================================================================
  // Proposals & Bookings
  // ==========================================================================

  /**
   * Fetches proposal state and status. Verified: GET /v1/proposals/{proposal_id}
   */
  async getProposal(proposalId: string, callerUserId?: string): Promise<ProposalDTO> {
    const headers: Record<string, string> = {}
    if (callerUserId) {
      headers["x-user-id"] = callerUserId
    }
    return this.request<ProposalDTO>("GET", `/v1/proposals/${encodeURIComponent(proposalId)}`, {
      headers,
      requiresAuth: true
    })
  }

  /**
   * Accepts a pooling proposal (by either host or traveller).
   * Verified: POST /v1/proposals/{proposal_id}/accept
   */
  async acceptProposal(
    proposalId: string,
    decision: ProposalDecisionInput,
    idempotencyKey?: string
  ): Promise<ProposalDecisionResult> {
    const headers: Record<string, string> = {}
    if (idempotencyKey) {
      headers["idempotency-key"] = idempotencyKey
    }
    return this.request<ProposalDecisionResult>(
      "POST",
      `/v1/proposals/${encodeURIComponent(proposalId)}/accept`,
      {
        body: decision,
        headers,
        requiresAuth: true
      }
    )
  }

  /**
   * Declines a pooling proposal. Verified: POST /v1/proposals/{proposal_id}/decline
   */
  async declineProposal(
    proposalId: string,
    decision: ProposalDecisionInput
  ): Promise<ProposalDecisionResult> {
    return this.request<ProposalDecisionResult>(
      "POST",
      `/v1/proposals/${encodeURIComponent(proposalId)}/decline`,
      {
        body: decision,
        requiresAuth: true
      }
    )
  }

  // ==========================================================================
  // Ride Requests
  // ==========================================================================

  /**
   * Submits a passenger ride request. Verified: POST /v1/requests
   */
  async createRideRequest(
    input: CreateRideRequestInput,
    idempotencyKey?: string
  ): Promise<RideRequestDTO> {
    const headers: Record<string, string> = {}
    if (idempotencyKey) {
      headers["idempotency-key"] = idempotencyKey
    }
    return this.request<RideRequestDTO>("POST", "/v1/requests", {
      body: input,
      headers,
      requiresAuth: true
    })
  }

  /**
   * Retrieves a ride request by ID. Verified: GET /v1/requests/{request_id}
   */
  async getRideRequest(requestId: string): Promise<RideRequestDTO> {
    return this.request<RideRequestDTO>("GET", `/v1/requests/${encodeURIComponent(requestId)}`, { requiresAuth: true })
  }

  /**
   * Cancels an active or pending ride request. Verified: POST /v1/requests/{request_id}/cancel
   */
  async cancelRideRequest(
    requestId: string,
    input?: CancelRideRequestInput,
    idempotencyKey?: string
  ): Promise<RideRequestDTO> {
    const headers: Record<string, string> = {}
    if (idempotencyKey) {
      headers["idempotency-key"] = idempotencyKey
    }
    return this.request<RideRequestDTO>(
      "POST",
      `/v1/requests/${encodeURIComponent(requestId)}/cancel`,
      {
        body: input,
        headers,
        requiresAuth: true
      }
    )
  }

  // ==========================================================================
  // En-Route Join
  // ==========================================================================

  /**
   * Evaluates dynamic insertion eligibility into an active en-route ride.
   * Verified: POST /v1/rides/{ride_id}/en-route-join
   */
  async evaluateEnRouteJoin(rideId: string, input: EnRouteJoinInput): Promise<EnRouteJoinResult> {
    return this.request<EnRouteJoinResult>(
      "POST",
      `/v1/rides/${encodeURIComponent(rideId)}/en-route-join`,
      {
        body: input,
        requiresAuth: true
      }
    )
  }
}

/**
 * Singleton instance of PoolEngineClient initialized with default environment config.
 */
export const poolEngineClient = new PoolEngineClient()
