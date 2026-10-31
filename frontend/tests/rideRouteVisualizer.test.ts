import { describe, it, expect } from "vitest"
import { getDistanceInMeters, formatDistance } from "../src/utils/locationService"
import { resolveFixedLocation } from "../src/config/locations"

describe("Ride Route Visualizer - Distance and Walking Proximity Calculations", () => {
  // CET Main Gate coordinates
  const passengerOrigin = { lat: 8.5459, lng: 76.9063, name: "CET Main Gate" }
  // Near Sreekaryam junction (host departure, ~1.2 km away)
  const hostDeparture = { lat: 8.5480, lng: 76.9150, name: "Sreekaryam Junction" }

  // Host dropoff at Thampanoor
  const hostDropoff = { lat: 8.4875, lng: 76.9525, name: "Trivandrum Central Railway Station" }
  // Passenger destination at KSRTC Central Bus Stand (~150m away from railway station)
  const passengerDestination = { lat: 8.4885, lng: 76.9535, name: "KSRTC Central Bus Stand" }

  it("calculates accurate pickup walking distance and duration", () => {
    const pickupDist = getDistanceInMeters(
      passengerOrigin.lat,
      passengerOrigin.lng,
      hostDeparture.lat,
      hostDeparture.lng
    )
    expect(pickupDist).toBeGreaterThan(900)
    expect(pickupDist).toBeLessThan(1200)

    // Walking speed: ~80 meters per minute
    const walkMinutes = Math.max(1, Math.round(pickupDist / 80))
    expect(walkMinutes).toBeGreaterThanOrEqual(11)
    expect(walkMinutes).toBeLessThanOrEqual(15)
  })

  it("calculates accurate drop-off walking distance and duration", () => {
    const dropoffDist = getDistanceInMeters(
      hostDropoff.lat,
      hostDropoff.lng,
      passengerDestination.lat,
      passengerDestination.lng
    )
    expect(dropoffDist).toBeGreaterThan(100)
    expect(dropoffDist).toBeLessThan(200)

    const walkMinutes = Math.max(1, Math.round(dropoffDist / 80))
    expect(walkMinutes).toBe(2)
  })

  it("identifies direct/exact pickup when distance is under 30 meters", () => {
    const identicalPoint = { lat: 8.5459, lng: 76.9063 }
    const dist = getDistanceInMeters(passengerOrigin.lat, passengerOrigin.lng, identicalPoint.lat, identicalPoint.lng)
    expect(dist).toBe(0)
    expect(formatDistance(dist)).toBe("0 m")
  })

  it("calculates total walking distance as pickup walk + dropoff walk", () => {
    const pickupDist = getDistanceInMeters(
      passengerOrigin.lat,
      passengerOrigin.lng,
      hostDeparture.lat,
      hostDeparture.lng
    )
    const dropoffDist = getDistanceInMeters(
      hostDropoff.lat,
      hostDropoff.lng,
      passengerDestination.lat,
      passengerDestination.lng
    )
    const totalDist = pickupDist + dropoffDist
    expect(totalDist).toBe(pickupDist + dropoffDist)
    expect(formatDistance(totalDist)).toContain("km")
  })

  // --- Group 1 Regression Tests (U11, U12, U10) ---

  it("U11: preserves exact GPS coordinates without snapping to locality centroid", () => {
    const exactGpsLoc = {
      address: "Sreekariyam, Thiruvananthapuram",
      name: "Sreekariyam, Thiruvananthapuram",
      latitude: 8.5484821,
      longitude: 76.9157234
    }

    const resolved = resolveFixedLocation(exactGpsLoc.name, exactGpsLoc, true)
    expect(resolved.latitude).toBe(8.5484821)
    expect(resolved.longitude).toBe(76.9157234)
    expect(resolved.name).toBe("Sreekariyam, Thiruvananthapuram")
  })

  it("U11: preserves exact GPS coordinates passed as lat/lng object", () => {
    const exactGpsLoc = {
      name: "Custom Spot",
      lat: 8.549112,
      lng: 76.914221
    }

    const resolved = resolveFixedLocation("Custom Spot", exactGpsLoc, true)
    expect(resolved.latitude).toBe(8.549112)
    expect(resolved.longitude).toBe(76.914221)
  })

  it("U12: resolves destination coordinates for Trivandrum Central correctly", () => {
    const resolved = resolveFixedLocation("Trivandrum Central Railway Station", undefined, false)
    expect(resolved.latitude).toBeCloseTo(8.4875, 2)
    expect(resolved.longitude).toBeCloseTo(76.9525, 2)
  })
})
