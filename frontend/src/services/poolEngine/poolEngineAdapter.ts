/**
 * Pool Engine Data Adapter
 *
 * Provides bidirectional translation between Waymate domain models and Pool Engine DTOs.
 *
 * Responsibilities:
 * 1. Geographic Coordinate Mapping & Validation: Resolves and bounds-checks latitude/longitude.
 * 2. Temporal Translation: Converts Waymate date/time strings to Unix epoch seconds.
 * 3. Privacy Preservation: Ensures student personal details (phones, departments, roll numbers)
 *    are stripped before sending payloads to Pool Engine.
 * 4. Error Normalization: Converts boundary mapping failures into typed PoolEngineAdapterError.
 * 5. Architectural Clarity: Pool Engine manages private host rides and optimization matching,
 *    not broad public ride catalog discovery.
 */

import {
  type GeoCoordinate,
  type CreateHostRideInput,
  type HostRideDTO,
  type MatchHostRideResult,
  type ProposalDecisionResult,
  PoolEngineClient,
  PoolEngineNotFoundError,
  poolEngineClient
} from "./poolEngineClient"
import { resolveFixedLocation } from "../../config/locations"
import { parseTimeToMinutes } from "../../config/matchingConfig"
import { getLocalDateString } from "../../utils/formatters"
import { RIDE_STATUS, type RideStatus } from "../../types/rideStatus"
import type { Ride, RideLocation } from "../ride/rideService"

// ============================================================================
// Adapter Error Class
// ============================================================================

export class PoolEngineAdapterError extends Error {
  readonly code: string
  readonly field?: string

  constructor(message: string, code: string = "ADAPTER_ERROR", field?: string) {
    super(message)
    this.name = "PoolEngineAdapterError"
    this.code = code
    this.field = field
  }
}

// ============================================================================
// Geographic Coordinate Resolution & Bounds Validation
// ============================================================================

/**
 * Resolves a geographic coordinate from a name and/or location object, ensuring
 * it falls strictly within valid spherical bounds (lat: [-90, 90], lng: [-180, 180]).
 */
export function resolveLocationCoordinate(
  nameOrAddress?: string,
  locationObj?: RideLocation | { latitude?: number; longitude?: number; lat?: number; lng?: number } | null
): GeoCoordinate {
  let lat: number | undefined
  let lng: number | undefined

  if (locationObj) {
    lat = typeof (locationObj as any).latitude === "number"
      ? (locationObj as any).latitude
      : (locationObj as any).lat
    lng = typeof (locationObj as any).longitude === "number"
      ? (locationObj as any).longitude
      : (locationObj as any).lng
  }

  if (typeof lat !== "number" || typeof lng !== "number" || isNaN(lat) || isNaN(lng)) {
    // Attempt fallback resolution using Waymate's fixed locations table
    const resolved = resolveFixedLocation(nameOrAddress, locationObj)
    lat = resolved.latitude
    lng = resolved.longitude
  }

  if (typeof lat !== "number" || typeof lng !== "number" || isNaN(lat) || isNaN(lng)) {
    throw new PoolEngineAdapterError(
      `Unable to resolve valid geographic coordinates for location '${nameOrAddress || "unknown"}'.`,
      "INVALID_COORDINATES",
      "location"
    )
  }

  // Validate bounds
  if (lat < -90 || lat > 90) {
    throw new PoolEngineAdapterError(
      `Latitude ${lat} is out of valid bounds [-90, 90] for '${nameOrAddress || "unknown"}'.`,
      "OUT_OF_BOUNDS_LATITUDE",
      "latitude"
    )
  }

  if (lng < -180 || lng > 180) {
    throw new PoolEngineAdapterError(
      `Longitude ${lng} is out of valid bounds [-180, 180] for '${nameOrAddress || "unknown"}'.`,
      "OUT_OF_BOUNDS_LONGITUDE",
      "longitude"
    )
  }

  return {
    latitude: lat,
    longitude: lng
  }
}

// ============================================================================
// Temporal Conversion (Date + Time -> Unix Epoch Seconds)
// ============================================================================

/**
 * Combines a date string ("YYYY-MM-DD" or standard date string) and time string
 * ("HH:mm" or "hh:mm AM/PM") into Unix epoch seconds.
 */
export function parseDepartureTimestamp(dateStr?: string, timeStr?: string): number {
  if (!dateStr || !dateStr.trim()) {
    throw new PoolEngineAdapterError("Departure date is required", "INVALID_DATE", "date")
  }
  if (!timeStr || !timeStr.trim()) {
    throw new PoolEngineAdapterError("Departure time is required", "INVALID_TIME", "departureTime")
  }

  const trimmedDate = dateStr.trim()
  const trimmedTime = timeStr.trim()

  const isoMatch = trimmedDate.match(/^(\d{4})-(\d{2})-(\d{2})/)
  let depYear = 0
  let depMonth = 0
  let depDay = 0

  if (isoMatch) {
    depYear = parseInt(isoMatch[1], 10)
    depMonth = parseInt(isoMatch[2], 10) - 1
    depDay = parseInt(isoMatch[3], 10)
  } else {
    const dObj = new Date(trimmedDate)
    if (isNaN(dObj.getTime())) {
      throw new PoolEngineAdapterError(`Invalid date format: '${trimmedDate}'`, "INVALID_DATE", "date")
    }
    depYear = dObj.getFullYear()
    depMonth = dObj.getMonth()
    depDay = dObj.getDate()
  }

  const totalMinutes = parseTimeToMinutes(trimmedTime)
  const departureDate = new Date(
    depYear,
    depMonth,
    depDay,
    Math.floor(totalMinutes / 60),
    totalMinutes % 60,
    0,
    0
  )

  if (isNaN(departureDate.getTime())) {
    throw new PoolEngineAdapterError(
      `Failed to compute valid departure timestamp from date '${trimmedDate}' and time '${trimmedTime}'.`,
      "INVALID_TIMESTAMP"
    )
  }

  return Math.floor(departureDate.getTime() / 1000)
}

// ============================================================================
// Waymate -> Pool Engine Schema Mappings
// ============================================================================

/**
 * Maps a Waymate ride creation payload to Pool Engine's CreateHostRideInput.
 *
 * Privacy Invariant:
 * Strictly strips student names, phone numbers, department, year, college, and gender.
 * Only forwards driver UID, origin, destination, timestamp, and capacity.
 */
export function mapWaymateRideToPoolEngineInput(
  data: Partial<Ride>,
  driverUid: string
): CreateHostRideInput {
  if (!driverUid || typeof driverUid !== "string" || !driverUid.trim()) {
    throw new PoolEngineAdapterError("A valid driver UID is required", "INVALID_DRIVER_ID", "driver_id")
  }

  const origin = resolveLocationCoordinate(data.from, data.fromLocation)
  const destination = resolveLocationCoordinate(data.to, data.toLocation)

  const scheduledDepartureTime = parseDepartureTimestamp(data.date, data.departureTime)

  const rawSeats = data.availableSeats ?? data.totalSeats ?? data.seats ?? 1
  const availableSeats = Number(rawSeats)

  if (isNaN(availableSeats) || availableSeats < 1 || availableSeats > 50) {
    throw new PoolEngineAdapterError(
      `Available seats (${rawSeats}) must be a number between 1 and 50.`,
      "INVALID_CAPACITY",
      "available_seats"
    )
  }

  return {
    driver_id: driverUid.trim(),
    origin,
    destination,
    scheduled_departure_time: scheduledDepartureTime,
    available_seats: availableSeats,
    max_detour_seconds: 900, // 15-minute default detour ceiling
    vehicle_id: data.vehicleType ? `veh_${data.vehicleType.toLowerCase()}` : null,
    ride_id: data.id || null
  }
}

/**
 * Maps a Pool Engine HostRideDTO back into Waymate's standard Ride model
 * for consistent frontend display and consumption.
 */
export function mapPoolEngineHostRideToWaymateRide(
  dto: HostRideDTO,
  fallbackDetails?: Partial<Ride>
): Ride {
  const depDate = new Date(dto.scheduled_departure_time * 1000)
  const dateStr = getLocalDateString(depDate)
  const hours = String(depDate.getHours()).padStart(2, "0")
  const minutes = String(depDate.getMinutes()).padStart(2, "0")
  const departureTimeStr = `${hours}:${minutes}`

  let status: RideStatus = RIDE_STATUS.ACTIVE
  const backendStatus = (dto.status || "").toUpperCase()
  if (backendStatus === "CANCELLED") status = RIDE_STATUS.CANCELLED
  else if (backendStatus === "COMPLETED") status = RIDE_STATUS.COMPLETED
  else if (dto.available_seats === 0) status = RIDE_STATUS.FULL

  return {
    id: dto.ride_id,
    ownerId: dto.driver_id,
    from: fallbackDetails?.from || `Coordinate (${dto.origin.latitude.toFixed(4)}, ${dto.origin.longitude.toFixed(4)})`,
    to: fallbackDetails?.to || `Coordinate (${dto.destination.latitude.toFixed(4)}, ${dto.destination.longitude.toFixed(4)})`,
    fromLocation: {
      address: fallbackDetails?.from || "Origin",
      latitude: dto.origin.latitude,
      longitude: dto.origin.longitude
    },
    toLocation: {
      address: fallbackDetails?.to || "Destination",
      latitude: dto.destination.latitude,
      longitude: dto.destination.longitude
    },
    date: dateStr,
    departureTime: departureTimeStr,
    availableSeats: dto.available_seats,
    totalSeats: fallbackDetails?.totalSeats || dto.available_seats,
    seats: fallbackDetails?.seats || dto.available_seats,
    meetingPoint: fallbackDetails?.meetingPoint || "",
    vehicleType: dto.vehicle_id?.replace(/^veh_/, "") || fallbackDetails?.vehicleType || "car",
    genderPolicy: fallbackDetails?.genderPolicy || "any",
    status,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  }
}

// ============================================================================
// Pool Engine Data Adapter Service
// ============================================================================

export class PoolEngineAdapter {
  private client: PoolEngineClient

  constructor(client: PoolEngineClient = poolEngineClient) {
    this.client = client
  }

  /**
   * Registers a host ride with Pool Engine.
   */
  async registerHostRide(ride: Partial<Ride>, driverUid: string): Promise<HostRideDTO> {
    const input = mapWaymateRideToPoolEngineInput(ride, driverUid)
    return await this.client.createHostRide(input)
  }

  /**
   * Retrieves host ride details by ID from Pool Engine.
   */
  async getHostRide(rideId: string): Promise<HostRideDTO> {
    if (!rideId || typeof rideId !== "string" || !rideId.trim()) {
      throw new PoolEngineAdapterError("A non-empty rideId is required", "INVALID_ARGUMENT", "rideId")
    }
    return await this.client.getHostRide(rideId.trim())
  }

  /**
   * Retrieves host ride details and translates them into a Waymate Ride domain model.
   * Returns null if the ride does not exist in Pool Engine.
   */
  async getHostRideAsWaymateRide(rideId: string, fallback?: Partial<Ride>): Promise<Ride | null> {
    try {
      const dto = await this.getHostRide(rideId)
      return mapPoolEngineHostRideToWaymateRide(dto, fallback)
    } catch (err: unknown) {
      if (err instanceof PoolEngineNotFoundError) {
        return null
      }
      throw err
    }
  }

  /**
   * Runs single-ride insertion matching against active pending requests in Pool Engine.
   */
  async matchHostRide(rideId: string, requestId?: string): Promise<MatchHostRideResult> {
    if (!rideId || typeof rideId !== "string" || !rideId.trim()) {
      throw new PoolEngineAdapterError("A non-empty rideId is required", "INVALID_ARGUMENT", "rideId")
    }
    return await this.client.matchHostRide(rideId.trim(), requestId?.trim())
  }

  /**
   * Accepts a proposal in Pool Engine (as either host or traveller).
   */
  async acceptProposal(
    proposalId: string,
    role: "host" | "traveller",
    idempotencyKey?: string
  ): Promise<ProposalDecisionResult> {
    if (!proposalId || typeof proposalId !== "string" || !proposalId.trim()) {
      throw new PoolEngineAdapterError("A non-empty proposalId is required", "INVALID_ARGUMENT", "proposalId")
    }
    return await this.client.acceptProposal(
      proposalId.trim(),
      { role },
      idempotencyKey
    )
  }

  /**
   * Declines a proposal in Pool Engine.
   */
  async declineProposal(
    proposalId: string,
    role: "host" | "traveller",
    reason?: string
  ): Promise<ProposalDecisionResult> {
    if (!proposalId || typeof proposalId !== "string" || !proposalId.trim()) {
      throw new PoolEngineAdapterError("A non-empty proposalId is required", "INVALID_ARGUMENT", "proposalId")
    }
    return await this.client.declineProposal(
      proposalId.trim(),
      { role, reason }
    )
  }
}

/**
 * Singleton instance of PoolEngineAdapter.
 */
export const poolEngineAdapter = new PoolEngineAdapter()
