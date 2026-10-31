import { describe, it, expect, vi, beforeEach } from "vitest"
import { RoutingService } from "../src/services/routing/RoutingService"
import { decodePolyline } from "../src/services/routing/providers/OSRMProvider"
import type { IRoutingProvider, Coordinates, RouteResult, SnappedPoint } from "../src/services/routing/types"
import { computeSmartMeetingPoint } from "../src/services/routing/smartMeetingPoint"

class MockRoutingProvider implements IRoutingProvider {
  public name = "MockProvider"
  public getRouteCallCount = 0
  public snapCallCount = 0

  async getRoute(from: Coordinates, to: Coordinates, mode: any, signal?: AbortSignal): Promise<RouteResult> {
    this.getRouteCallCount++
    if (signal?.aborted) {
      const err = new Error("Aborted")
      err.name = "AbortError"
      throw err
    }

    // Default mock response: 3-point geometry
    return {
      geometry: [
        [from.lat, from.lng],
        [(from.lat + to.lat) / 2, (from.lng + to.lng) / 2],
        [to.lat, to.lng]
      ],
      distanceMeters: 1000,
      durationSeconds: 120,
      mode,
      isFallback: false
    }
  }

  async snapToRoad(point: Coordinates, _mode: any): Promise<SnappedPoint | null> {
    this.snapCallCount++
    return {
      lat: point.lat + 0.0001,
      lng: point.lng + 0.0001,
      distanceMeters: 12,
      name: "Campus Ring Road"
    }
  }
}

describe("Routing Service & Layer Unit Tests", () => {
  let mockProvider: MockRoutingProvider
  let service: RoutingService

  beforeEach(() => {
    mockProvider = new MockRoutingProvider()
    service = new RoutingService(mockProvider)
  })

  it("correctly decodes encoded polyline strings into [lat, lng] coordinates", () => {
    // Encoded polyline representing [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    const encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    const coords = decodePolyline(encoded)

    expect(coords.length).toBe(3)
    expect(coords[0][0]).toBeCloseTo(38.5, 3)
    expect(coords[0][1]).toBeCloseTo(-120.2, 3)
    expect(coords[1][0]).toBeCloseTo(40.7, 3)
    expect(coords[1][1]).toBeCloseTo(-120.95, 3)
    expect(coords[2][0]).toBeCloseTo(43.252, 3)
    expect(coords[2][1]).toBeCloseTo(-126.453, 3)
  })

  it("handles very short routes (< 30m) without calling provider", async () => {
    const from = { lat: 8.5459, lng: 76.9063 }
    const to = { lat: 8.54595, lng: 76.90635 } // ~7 meters away

    const result = await service.getRoute(from, to, "walking")

    expect(mockProvider.getRouteCallCount).toBe(0)
    expect(result.warning).toBe("You're here")
    expect(result.durationSeconds).toBe(0)
  })

  it("caches routes to prevent duplicate API requests for identical coordinates", async () => {
    const from = { lat: 8.5459, lng: 76.9063 }
    const to = { lat: 8.4875, lng: 76.9525 }

    // First request -> calls provider
    const r1 = await service.getRoute(from, to, "driving")
    expect(mockProvider.getRouteCallCount).toBe(1)

    // Second request with same coordinates -> served from cache
    const r2 = await service.getRoute(from, to, "driving")
    expect(mockProvider.getRouteCallCount).toBe(1)
    expect(r2.geometry).toEqual(r1.geometry)
  })

  it("detects campus footpath anomalies when walking route exceeds 3x straight-line distance", async () => {
    const from = { lat: 8.5459, lng: 76.9063 }
    const to = { lat: 8.5479, lng: 76.9083 } // ~300m straight line

    // Provider mock returns absurd 2.5km detour around perimeter wall
    vi.spyOn(mockProvider, "getRoute").mockResolvedValueOnce({
      geometry: [
        [from.lat, from.lng],
        [8.5400, 76.9000],
        [to.lat, to.lng]
      ],
      distanceMeters: 2500, // > 3x of 300m!
      durationSeconds: 1800,
      mode: "walking",
      isFallback: false
    })

    const result = await service.getRoute(from, to, "walking", { enableSnapping: false })

    expect(result.isFallback).toBe(true)
    expect(result.warning).toContain("Campus internal paths not mapped")
    expect(result.distanceMeters).toBeLessThan(1000)
  })

  it("detects off-route deviations when user drifts > 30m away from the path", () => {
    // Polyline running straight North along 76.9063 from lat 8.5400 to 8.5500
    const routeGeometry: [number, number][] = [
      [8.5400, 76.9063],
      [8.5500, 76.9063]
    ]

    // Position on the route: lat 8.5450, lng 76.9063 -> 0m away
    expect(service.isOffRoute(routeGeometry, { lat: 8.5450, lng: 76.9063 }, 30)).toBe(false)

    // Position 10m to the side -> not off route (within 30m corridor)
    expect(service.isOffRoute(routeGeometry, { lat: 8.5450, lng: 76.90639 }, 30)).toBe(false)

    // Position 100m to the side -> off route!
    expect(service.isOffRoute(routeGeometry, { lat: 8.5450, lng: 76.9073 }, 30)).toBe(true)
  })

  it("dynamically trims polyline and calculates remaining distance and ETA without network calls", () => {
    const routeGeometry: [number, number][] = [
      [8.5400, 76.9063],
      [8.5450, 76.9063],
      [8.5500, 76.9063]
    ]

    // User is halfway along the first segment at 8.5425
    const trimmed = service.trimRoute(routeGeometry, { lat: 8.5425, lng: 76.9063 })

    expect(trimmed.isOffRoute).toBe(false)
    expect(trimmed.geometry.length).toBeGreaterThanOrEqual(2)
    expect(trimmed.remainingDistanceMeters).toBeGreaterThan(0)
    expect(trimmed.progressRatio).toBeGreaterThan(0.1)
  })

  it("computes balanced smart meeting point between two walking co-riders", async () => {
    const posA = { lat: 8.5459, lng: 76.9063 } // You at CET Main Gate
    const posB = { lat: 8.5499, lng: 76.9099 } // Co-rider ~600m away

    const smp = await computeSmartMeetingPoint({
      posA,
      posB,
      nameA: "You",
      nameB: "Anu"
    })

    expect(smp).not.toBeNull()
    if (smp) {
      expect(smp.description).toContain("Meet here · Anu")
      expect(smp.durationMinutesA).toBeGreaterThan(0)
      expect(smp.durationMinutesB).toBeGreaterThan(0)
      expect(smp.point.lat).toBeGreaterThan(0)
      expect(smp.point.lng).toBeGreaterThan(0)
    }
  })
})
