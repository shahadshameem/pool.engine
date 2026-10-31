/**
 * Canonical Ride Status Definition for WayMate
 *
 * Standard status lifecycle:
 * - ACTIVE: Ride is open and has available seats.
 * - FULL: All seats are reserved (availableSeats === 0).
 * - COMPLETED: Ride has successfully departed / arrived.
 * - CANCELLED: Ride was cancelled by host or admin.
 * - EXPIRED: Departure time passed with no accepted passengers.
 */

export const RIDE_STATUS = {
  ACTIVE: "active",
  FULL: "full",
  COMPLETED: "completed",
  CANCELLED: "cancelled",
  EXPIRED: "expired",
} as const

export type RideStatus = typeof RIDE_STATUS[keyof typeof RIDE_STATUS]

/**
 * Normalizes any legacy or case-variant status string into the canonical RideStatus.
 * e.g., "OPEN" -> "active", "FULL" -> "full", "CANCELLED" -> "cancelled"
 */
export function normalizeRideStatus(status?: string | null): RideStatus {
  if (!status) return RIDE_STATUS.ACTIVE
  const s = status.trim().toLowerCase()
  if (s === "open" || s === "active") return RIDE_STATUS.ACTIVE
  if (s === "full") return RIDE_STATUS.FULL
  if (s === "completed") return RIDE_STATUS.COMPLETED
  if (s === "cancelled" || s === "canceled") return RIDE_STATUS.CANCELLED
  if (s === "expired") return RIDE_STATUS.EXPIRED
  return RIDE_STATUS.ACTIVE
}

/**
 * Checks whether a ride status represents an active, requestable ride with seats.
 */
export function isRideRequestable(status?: string | null): boolean {
  const normalized = normalizeRideStatus(status)
  return normalized === RIDE_STATUS.ACTIVE
}
