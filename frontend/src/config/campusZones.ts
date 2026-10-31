/**
 * Campus Zones Configuration
 *
 * Defines geofenced campus zones where automatic pickup assignment takes place.
 * Easy to extend with new university / college zones.
 */

import { getDistanceInMeters } from "../utils/locationService"

export interface CampusZone {
  id: string
  name: string
  address: string
  /**
   * Latitude of the campus zone center.
   * MUST be provided by the administrator / developer.
   */
  lat: number
  /**
   * Longitude of the campus zone center.
   * MUST be provided by the administrator / developer.
   */
  lng: number
  /** Geofence radius in meters around the center (e.g. 100m) */
  radiusMeters: number
}

// Marker to indicate coordinates have not been filled in yet
export const COORDINATES_TODO = Number.NaN

export const CAMPUS_ZONES: CampusZone[] = [
  {
    id: "cet-front-gate",
    name: "College of Engineering Trivandrum",
    address: "College of Engineering Trivandrum (CET) Front Gate, Sreekaryam, Thiruvananthapuram",
    lat: 8.546938,
    lng: 76.905484,
    radiusMeters: 100
  }
]

export interface CampusZoneMatch {
  zone: CampusZone
  distanceMeters: number
}

/**
 * Validates that campus zone coordinates are configured.
 * In development mode, fails loudly if coordinates are still TODO.
 */
export function validateCampusZoneCoordinates(zone: CampusZone): void {
  const isDev = typeof import.meta !== "undefined" && Boolean(import.meta.env?.DEV)
  if (isNaN(zone.lat) || isNaN(zone.lng)) {
    const errorMsg = `[CampusZones] Zone '${zone.id}' coordinates are not configured (TODO). Please supply exact latitude and longitude in src/config/campusZones.ts.`
    if (isDev) {
      console.error(errorMsg)
      throw new Error(errorMsg)
    }
  }
}

/**
 * Resolves the closest campus zone that contains the given coordinate.
 * Uses Haversine distance formula.
 *
 * Returns the matching zone and distance, or null if outside all zones.
 */
export function resolveCampusZone(
  lat: number,
  lng: number,
  zones: CampusZone[] = CAMPUS_ZONES
): CampusZoneMatch | null {
  if (typeof lat !== "number" || typeof lng !== "number" || isNaN(lat) || isNaN(lng)) {
    return null
  }

  let closestMatch: CampusZoneMatch | null = null
  let minDistance = Infinity

  for (const zone of zones) {
    validateCampusZoneCoordinates(zone)

    if (isNaN(zone.lat) || isNaN(zone.lng)) {
      continue
    }

    const distance = getDistanceInMeters(lat, lng, zone.lat, zone.lng)
    if (distance <= zone.radiusMeters) {
      if (distance < minDistance) {
        minDistance = distance
        closestMatch = { zone, distanceMeters: distance }
      }
    }
  }

  return closestMatch
}
