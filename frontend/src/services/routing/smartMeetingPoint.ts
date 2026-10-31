/**
 * Smart Meeting Point Engine
 * Computes balanced walking meeting points between co-riders in Phase A
 */

import type { Coordinates, SmartMeetingPoint } from "./types"
import { getDistanceInMeters } from "../../utils/locationService"
import { routingService } from "./RoutingService"

export interface CalculateMeetingPointParams {
  posA: Coordinates
  posB: Coordinates
  nameA?: string
  nameB?: string
  pickupPoint?: Coordinates
  existingPolyline?: [number, number][]
}

/**
 * Computes an optimal meeting spot along the walking network where walking times are balanced.
 */
export async function computeSmartMeetingPoint({
  posA,
  posB,
  nameA = "You",
  nameB = "Co-rider",
  pickupPoint: _pickupPoint,
  existingPolyline
}: CalculateMeetingPointParams): Promise<SmartMeetingPoint | null> {
  const directDist = getDistanceInMeters(posA.lat, posA.lng, posB.lat, posB.lng)

  // If already within 35m, participants have met; no midpoint needed
  if (directDist <= 35) {
    return null
  }

  // If both participants are very far from each other (> 3km), balanced midpoint isn't feasible
  if (directDist > 3000) {
    return null
  }

  let polyline = existingPolyline

  // If no polyline provided, query walking route between A and B
  if (!polyline || polyline.length < 2) {
    try {
      const route = await routingService.getRoute(posA, posB, "walking")
      polyline = route.geometry
    } catch {
      polyline = [
        [posA.lat, posA.lng],
        [(posA.lat + posB.lat) / 2, (posA.lng + posB.lng) / 2],
        [posB.lat, posB.lng]
      ]
    }
  }

  if (!polyline || polyline.length < 2) {
    return null
  }

  // Calculate cumulative distance along polyline segments
  const cumulativeDistances: number[] = [0]
  let totalDistance = 0

  for (let i = 0; i < polyline.length - 1; i++) {
    const segDist = getDistanceInMeters(
      polyline[i][0],
      polyline[i][1],
      polyline[i + 1][0],
      polyline[i + 1][1]
    )
    totalDistance += segDist
    cumulativeDistances.push(totalDistance)
  }

  // Target midpoint distance along the polyline path
  const targetHalfDist = totalDistance / 2

  // Locate the segment containing targetHalfDist
  let meetingPointCoords: Coordinates = {
    lat: (posA.lat + posB.lat) / 2,
    lng: (posA.lng + posB.lng) / 2
  }

  for (let i = 0; i < cumulativeDistances.length - 1; i++) {
    const dStart = cumulativeDistances[i]
    const dEnd = cumulativeDistances[i + 1]

    if (targetHalfDist >= dStart && targetHalfDist <= dEnd) {
      const segLen = dEnd - dStart
      const fraction = segLen > 0 ? (targetHalfDist - dStart) / segLen : 0.5

      meetingPointCoords = {
        lat: polyline[i][0] + fraction * (polyline[i + 1][0] - polyline[i][0]),
        lng: polyline[i][1] + fraction * (polyline[i + 1][1] - polyline[i][1])
      }
      break
    }
  }

  // Walking speeds in campus environment ~80m per minute
  const distA = Math.round(targetHalfDist)
  const distB = Math.round(totalDistance - targetHalfDist)
  const timeA = Math.max(1, Math.round(distA / 80))
  const timeB = Math.max(1, Math.round(distB / 80))

  return {
    point: meetingPointCoords,
    distanceA: distA,
    distanceB: distB,
    durationMinutesA: timeA,
    durationMinutesB: timeB,
    description: `Meet here · ${nameB} ${timeB} min, ${nameA} ${timeA} min`
  }
}
