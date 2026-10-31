import { describe, it, expect } from "vitest"
import {
  resolveCampusZone,
  validateCampusZoneCoordinates,
  COORDINATES_TODO,
  CAMPUS_ZONES,
  type CampusZone
} from "../src/config/campusZones"
import { resolveFixedLocation } from "../src/config/locations"
import { getDistanceInMeters } from "../src/utils/locationService"

describe("Campus Zone Geofencing & Auto-Assignment Tests (CET Front Gate)", () => {
  // CET Front Gate coordinates chosen by user
  const gateLat = 8.546938
  const gateLng = 76.905484

  // Degrees latitude per meter: 1 / 111139
  const degPerMeter = 1 / 111139

  it("verifies configured CET zone has no TODO or NaN placeholders", () => {
    const cetZone = CAMPUS_ZONES.find(z => z.id === "cet-front-gate")
    expect(cetZone).toBeDefined()
    expect(cetZone?.lat).toBe(8.546938)
    expect(cetZone?.lng).toBe(76.905484)
    expect(cetZone?.radiusMeters).toBe(100)
    expect(isNaN(cetZone?.lat!)).toBe(false)
    expect(isNaN(cetZone?.lng!)).toBe(false)

    // validateCampusZoneCoordinates should not throw on the configured zone
    expect(() => validateCampusZoneCoordinates(cetZone!)).not.toThrow()
  })

  it("fails loudly in dev if a zone's coordinates are left unconfigured as TODO", () => {
    const unconfiguredZone: CampusZone = {
      id: "unconfigured-zone",
      name: "Unconfigured Campus",
      address: "Campus",
      lat: COORDINATES_TODO,
      lng: COORDINATES_TODO,
      radiusMeters: 100
    }

    expect(() => validateCampusZoneCoordinates(unconfiguredZone)).toThrow(
      "[CampusZones] Zone 'unconfigured-zone' coordinates are not configured (TODO)"
    )
  })

  it("assigns user at 0 m from CET Front Gate to cet-front-gate", () => {
    const match = resolveCampusZone(gateLat, gateLng)

    expect(match).not.toBeNull()
    expect(match?.zone.id).toBe("cet-front-gate")
    expect(match?.distanceMeters).toBe(0)
    expect(match?.zone.lat).toBe(gateLat)
    expect(match?.zone.lng).toBe(gateLng)
  })

  it("assigns user at 50 m from CET Front Gate to cet-front-gate", () => {
    // Offset North by 50m
    const lat50m = gateLat + 50 * degPerMeter
    const lng50m = gateLng
    const actualDist = getDistanceInMeters(gateLat, gateLng, lat50m, lng50m)

    expect(actualDist).toBe(50)

    const match = resolveCampusZone(lat50m, lng50m)
    expect(match).not.toBeNull()
    expect(match?.zone.id).toBe("cet-front-gate")
    expect(match?.distanceMeters).toBe(50)
  })

  it("assigns user at 99 m (just inside the 100 m buffer) from CET Front Gate", () => {
    // Offset North by 99m
    const lat99m = gateLat + 99 * degPerMeter
    const lng99m = gateLng
    const actualDist = getDistanceInMeters(gateLat, gateLng, lat99m, lng99m)

    expect(actualDist).toBe(99)

    const match = resolveCampusZone(lat99m, lng99m)
    expect(match).not.toBeNull()
    expect(match?.zone.id).toBe("cet-front-gate")
    expect(match?.distanceMeters).toBe(99)
  })

  it("does NOT assign user at 101 m (outside the 100 m buffer) from CET Front Gate", () => {
    // Offset North by 101m
    const lat101m = gateLat + 101 * degPerMeter
    const lng101m = gateLng
    const actualDist = getDistanceInMeters(gateLat, gateLng, lat101m, lng101m)

    expect(actualDist).toBe(101)

    const match = resolveCampusZone(lat101m, lng101m)
    expect(match).toBeNull()
  })

  it("does NOT assign user at 500 m from CET Front Gate", () => {
    const lat500m = gateLat + 500 * degPerMeter
    const lng500m = gateLng
    const actualDist = getDistanceInMeters(gateLat, gateLng, lat500m, lng500m)

    expect(actualDist).toBe(500)

    const match = resolveCampusZone(lat500m, lng500m)
    expect(match).toBeNull()
  })

  it("handles overlapping zones by selecting the closest zone center", () => {
    // Zone A: CET Front Gate (radius 150m)
    const zoneA: CampusZone = {
      id: "cet-front-gate",
      name: "College of Engineering Trivandrum",
      address: "CET Front Gate",
      lat: gateLat,
      lng: gateLng,
      radiusMeters: 150
    }

    // Zone B: CET PG / MCA Block 100m away (radius 150m)
    const zoneB: CampusZone = {
      id: "cet-pg",
      name: "CET PG Block",
      address: "CET PG",
      lat: gateLat + 100 * degPerMeter,
      lng: gateLng,
      radiusMeters: 150
    }

    // Point 20m north of Zone A (80m from Zone B): Zone A is closer
    const pointNearA = gateLat + 20 * degPerMeter
    const matchA = resolveCampusZone(pointNearA, gateLng, [zoneA, zoneB])
    expect(matchA?.zone.id).toBe("cet-front-gate")

    // Point 80m north of Zone A (20m from Zone B): Zone B is closer
    const pointNearB = gateLat + 80 * degPerMeter
    const matchB = resolveCampusZone(pointNearB, gateLng, [zoneA, zoneB])
    expect(matchB?.zone.id).toBe("cet-pg")
  })

  it("enforces accuracy rule: point in zone is rejected from auto-assignment if accuracy > 50 m", () => {
    // Simulated point 40m from CET Front Gate
    const pointLat = gateLat + 40 * degPerMeter
    const pointLng = gateLng

    const evaluateAutoAssignment = (lat: number, lng: number, accuracy: number) => {
      const match = resolveCampusZone(lat, lng)
      const isAutoAssigned = Boolean(match && accuracy <= 50)
      const isLowAccuracy = Boolean(match && accuracy > 50)

      return { isAutoAssigned, isLowAccuracy, zoneId: match?.zone.id }
    }

    // Accuracy = 15m (Good) -> Auto-assigned!
    const goodGps = evaluateAutoAssignment(pointLat, pointLng, 15)
    expect(goodGps.isAutoAssigned).toBe(true)
    expect(goodGps.isLowAccuracy).toBe(false)
    expect(goodGps.zoneId).toBe("cet-front-gate")

    // Accuracy = 50m (Boundary) -> Auto-assigned!
    const boundaryGps = evaluateAutoAssignment(pointLat, pointLng, 50)
    expect(boundaryGps.isAutoAssigned).toBe(true)
    expect(boundaryGps.isLowAccuracy).toBe(false)

    // Accuracy = 65m (> 50m, Poor accuracy) -> NOT auto-assigned, flagged as low accuracy
    const poorGps = evaluateAutoAssignment(pointLat, pointLng, 65)
    expect(poorGps.isAutoAssigned).toBe(false)
    expect(poorGps.isLowAccuracy).toBe(true)
  })

  it("resolves CET name searches ('cet' and 'college of engineering') to cet-front-gate", () => {
    const resolvedByName = resolveFixedLocation("College of Engineering Trivandrum")
    expect(resolvedByName.id).toBe("cet-front-gate")
    expect(resolvedByName.matchedZoneId).toBe("cet-front-gate")
    expect(resolvedByName.latitude).toBe(8.546938)
    expect(resolvedByName.longitude).toBe(76.905484)

    const resolvedByAcronym = resolveFixedLocation("cet")
    expect(resolvedByAcronym.id).toBe("cet-front-gate")
    expect(resolvedByAcronym.matchedZoneId).toBe("cet-front-gate")
    expect(resolvedByAcronym.latitude).toBe(8.546938)
    expect(resolvedByAcronym.longitude).toBe(76.905484)

    const resolvedByGate = resolveFixedLocation("CET Front Gate")
    expect(resolvedByGate.id).toBe("cet-front-gate")
    expect(resolvedByGate.matchedZoneId).toBe("cet-front-gate")
  })

  it("strictly preserves user's explicit coordinates and never re-snaps them to zone centroid", () => {
    const customUserLoc = {
      name: "Near CET Mechanical Shed",
      address: "Near CET Mechanical Shed, Sreekaryam",
      latitude: 8.546123,
      longitude: 76.907456,
      matchedZoneId: "cet-front-gate",
      rawGps: { lat: 8.546123, lng: 76.907456, accuracy: 12 }
    }

    const resolved = resolveFixedLocation(customUserLoc.name, customUserLoc)
    expect(resolved.latitude).toBe(8.546123)
    expect(resolved.longitude).toBe(76.907456)
    expect(resolved.matchedZoneId).toBe("cet-front-gate")
    expect(resolved.rawGps?.accuracy).toBe(12)
  })
})
