import { describe, it, expect, vi, beforeEach } from "vitest"
import {
  DEFAULT_CENTER,
  TVM_BOUNDING_BOX,
  H3_RES,
  CAMPUS_PRESETS,
  searchLocations,
  getH3Cell,
  getH3SearchDisk,
  getH3DiskPolygons,
  getDistanceInMeters,
  formatDistance,
  isRideWithinCircles,
  reverseGeocode,
  fetchDrivingRoute
} from "../src/utils/locationService"

describe("Location, Autocomplete & Uber H3 Spatial Service (Trivandrum Edition)", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it("exports Trivandrum center coordinates and bounding box constants", () => {
    expect(DEFAULT_CENTER.lat).toBeCloseTo(8.5459, 3)
    expect(DEFAULT_CENTER.lng).toBeCloseTo(76.9063, 3)
    expect(TVM_BOUNDING_BOX).toBe("76.78,8.35,77.10,8.68")
    expect(H3_RES).toBe(8)
  })

  it("provides strictly the 3 required Trivandrum presets with subtexts and coordinates", () => {
    expect(CAMPUS_PRESETS.length).toBe(3)

    const cet = CAMPUS_PRESETS.find(p => p.name === "College of Engineering Trivandrum")
    expect(cet).toBeDefined()
    expect(cet?.subtext).toBe("Sreekaryam, Thiruvananthapuram")
    expect(cet?.lat).toBeCloseTo(8.5459, 3)
    expect(cet?.lng).toBeCloseTo(76.9063, 3)
    expect(cet?.isPreset).toBe(true)

    const central = CAMPUS_PRESETS.find(p => p.name === "Trivandrum Central Railway Station")
    expect(central).toBeDefined()
    expect(central?.subtext).toBe("Thampanoor, Thiruvananthapuram")
    expect(central?.lat).toBeCloseTo(8.4875, 3)
    expect(central?.lng).toBeCloseTo(76.9525, 3)
    expect(central?.isPreset).toBe(true)

    const kochuveli = CAMPUS_PRESETS.find(p => p.name === "Kochuveli Railway Station")
    expect(kochuveli).toBeDefined()
    expect(kochuveli?.subtext).toBe("Kochuveli, Thiruvananthapuram")
    expect(kochuveli?.lat).toBeCloseTo(8.5089, 3)
    expect(kochuveli?.lng).toBeCloseTo(76.9014, 3)
    expect(kochuveli?.isPreset).toBe(true)
  })

  it("filters Trivandrum presets by name and subtext with instant 0-latency matching", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ features: [] })
    } as any)

    // Search by name "engineering"
    const nameResults = await searchLocations("engineering")
    expect(nameResults.some(r => r.name.includes("College of Engineering Trivandrum"))).toBe(true)

    // Search by subtext "thampanoor"
    const subtextResults = await searchLocations("thampanoor")
    expect(subtextResults.some(r => r.name.includes("Trivandrum Central Railway Station"))).toBe(true)

    // Search by "kochuveli"
    const kochuveliResults = await searchLocations("kochuveli")
    expect(kochuveliResults.some(r => r.name.includes("Kochuveli Railway Station"))).toBe(true)
  })

  it("computes Uber H3 Resolution 8 cell IDs (getH3Cell)", () => {
    // CET Main Gate coordinates
    const h3Cell = getH3Cell(8.5459, 76.9063, 8)
    expect(typeof h3Cell).toBe("string")
    expect(h3Cell.length).toBe(15) // 64-bit hex string in H3 format e.g. "8860262047fffff"
    expect(h3Cell.startsWith("88")).toBe(true)
  })

  it("computes Uber H3 search disks (getH3SearchDisk) with adaptive radius k-rings", () => {
    // Radius <= 600m -> k = 1 (7 hexagons)
    const disk600 = getH3SearchDisk(8.5459, 76.9063, 500)
    expect(disk600.length).toBe(7)

    // Radius <= 1400m -> k = 2 (19 hexagons)
    const disk1000 = getH3SearchDisk(8.5459, 76.9063, 1000)
    expect(disk1000.length).toBe(19)

    // Radius > 1400m -> k = 3 (37 hexagons)
    const disk2000 = getH3SearchDisk(8.5459, 76.9063, 2000)
    expect(disk2000.length).toBe(37)
  })

  it("generates hexagon boundary polygons for rendering on Leaflet maps (getH3DiskPolygons)", () => {
    const polygons = getH3DiskPolygons(8.5459, 76.9063, 500)
    expect(polygons.length).toBe(7)

    // Each hexagon polygon in Leaflet has 6 vertices [lat, lng]
    const hex0 = polygons[0]
    expect(hex0.length).toBeGreaterThanOrEqual(6)
    expect(typeof hex0[0][0]).toBe("number") // lat
    expect(typeof hex0[0][1]).toBe("number") // lng
    expect(hex0[0][0]).toBeCloseTo(8.54, 1)
    expect(hex0[0][1]).toBeCloseTo(76.90, 1)
  })

  it("calculates exact Haversine distance between two coordinates in meters", () => {
    // CET Main Gate (8.5459, 76.9063) to Sreekaryam Jn (8.5476, 76.9161) is approx ~1.08 km
    const dist = getDistanceInMeters(8.5459, 76.9063, 8.5476, 76.9161)
    expect(dist).toBeGreaterThan(950)
    expect(dist).toBeLessThan(1250)
  })

  it("correctly identifies rides within circular radii (isRideWithinCircles)", () => {
    const rider = {
      source: { lat: 8.5459, lng: 76.9063 }, // CET Main Gate
      destination: { lat: 8.5666, lng: 76.8765 } // Kazhakootam
    }
    const nearbyDriver = {
      source: { lat: 8.5482, lng: 76.9041 }, // CET MH (~350m away)
      destination: { lat: 8.5581, lng: 76.8816 } // Technopark (~1.1 km away from Kazhakootam)
    }
    const farDriver = {
      source: { lat: 8.4875, lng: 76.9525 }, // Thampanoor (~8 km away)
      destination: { lat: 8.4828, lng: 76.9453 } // East Fort
    }

    // With 1500m radius, nearby driver matches
    const matchNearby = isRideWithinCircles(rider, nearbyDriver, 1500, 1500)
    expect(matchNearby.isMatch).toBe(true)
    expect(matchNearby.sourceDistance).toBeLessThan(500)
    expect(matchNearby.destDistance).toBeLessThan(1500)

    // With 1500m radius, far driver fails
    const matchFar = isRideWithinCircles(rider, farDriver, 1500, 1500)
    expect(matchFar.isMatch).toBe(false)
    expect(matchFar.sourceDistance).toBeGreaterThan(5000)
  })

  it("parses OSRM driving route response into polylineCoords, distanceKm, and durationMins", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        routes: [
          {
            distance: 5200, // 5.2 km in meters
            duration: 720,  // 12 mins in seconds
            geometry: {
              coordinates: [
                [76.9063, 8.5459],
                [76.8765, 8.5666]
              ]
            }
          }
        ]
      })
    } as any)

    const src = { lat: 8.5459, lng: 76.9063 }
    const dst = { lat: 8.5666, lng: 76.8765 }

    const route = await fetchDrivingRoute(src, dst)
    expect(route.distanceKm).toBe(5.2)
    expect(route.durationMins).toBe(12)
    expect(route.polylineCoords).toEqual([
      [8.5459, 76.9063],
      [8.5666, 76.8765]
    ])
    expect(route.coordinates).toEqual(route.polylineCoords)
  })

  it("formats reverseGeocode with Nominatim display_name or fallback coordinates", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        display_name: "CET Main Building, Sreekaryam, Thiruvananthapuram, Kerala, India"
      })
    } as any)

    const result = await reverseGeocode(8.5459, 76.9063)
    expect(result).toBe("CET Main Building, Sreekaryam, Thiruvananthapuram")

    // Fallback when network fails
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Network error"))
    const fallback = await reverseGeocode(8.5459, 76.9063)
    expect(fallback).toBe("8.5459, 76.9063")
  })

  it("formats distances cleanly in meters or kilometers (formatDistance)", () => {
    expect(formatDistance(350)).toBe("350 m")
    expect(formatDistance(999)).toBe("999 m")
    expect(formatDistance(1000)).toBe("1.0 km")
    expect(formatDistance(2450)).toBe("2.5 km")
  })

  it("attaches calculated distance and formats it when user coordinates are provided in searchLocations", async () => {
    // User at CET Main Gate (8.5459, 76.9063)
    const results = await searchLocations("", 8.5459, 76.9063)
    expect(results.length).toBeGreaterThan(0)

    // First result should be closest to CET Main Gate
    expect(results[0].distanceMeters).toBeDefined()
    expect(results[0].distanceFormatted).toBeDefined()
    expect(results[0].distanceMeters).toBeLessThan(100) // CET Main Gate itself
    expect(results[0].distanceFormatted).toBe("0 m")
  })
})
