/**
 * Waymate Unified Routing Service
 * Single entry point for all route calculation, snapping, caching, trimming, and rerouting.
 */

import type {
  IRoutingProvider,
  RoutingMode,
  Coordinates,
  RouteResult,
  TrimmedRouteResult,
  SnappedPoint
} from "./types"
import { OSRMProvider } from "./providers/OSRMProvider"
import { getDistanceInMeters } from "../../utils/locationService"

interface CacheEntry {
  result: RouteResult
  timestamp: number
}

interface SnapCacheEntry {
  snapped: SnappedPoint | null
  timestamp: number
}

export class RoutingService {
  private provider: IRoutingProvider
  private routeCache = new Map<string, CacheEntry>()
  private snapCache = new Map<string, SnapCacheEntry>()
  private inFlightRequests = new Map<string, AbortController>()
  private cacheTtlMs: number

  constructor(provider?: IRoutingProvider, cacheTtlMs = 5 * 60 * 1000) {
    this.provider = provider || new OSRMProvider()
    this.cacheTtlMs = cacheTtlMs
  }

  /**
   * Swap underlying routing provider at runtime (e.g. for Google Directions or Mapbox)
   */
  public setProvider(newProvider: IRoutingProvider) {
    this.provider = newProvider
    this.routeCache.clear()
    this.snapCache.clear()
  }

  public getProviderName(): string {
    return this.provider.name
  }

  /**
   * Primary route query method
   */
  public async getRoute(
    from: Coordinates,
    to: Coordinates,
    mode: RoutingMode,
    options?: {
      skipCache?: boolean
      enableSnapping?: boolean
      requestKey?: string
    }
  ): Promise<RouteResult> {
    const linearDist = getDistanceInMeters(from.lat, from.lng, to.lat, to.lng)

    // Edge Case 1: Extremely short distances (< 30m) -> already at target!
    if (linearDist < 30) {
      return {
        geometry: [
          [from.lat, from.lng],
          [to.lat, to.lng]
        ],
        distanceMeters: linearDist,
        durationSeconds: 0,
        mode,
        isFallback: false,
        warning: "You're here"
      }
    }

    // Road Snapping (optional, enabled by default for driving routes)
    let routedFrom = from
    let routedTo = to
    let snappedOrigin: Coordinates | undefined
    let snappedDestination: Coordinates | undefined

    if (options?.enableSnapping !== false) {
      const [snapFrom, snapTo] = await Promise.all([
        this.snapToRoad(from, mode),
        this.snapToRoad(to, mode)
      ])

      // Only use snapped coordinate if it is within 150m of the original pin
      if (snapFrom && snapFrom.distanceMeters <= 150) {
        routedFrom = { lat: snapFrom.lat, lng: snapFrom.lng }
        snappedOrigin = routedFrom
      }
      if (snapTo && snapTo.distanceMeters <= 150) {
        routedTo = { lat: snapTo.lat, lng: snapTo.lng }
        snappedDestination = routedTo
      }
    }

    // Cache lookup (using 4 decimal precision bucket ~11m)
    const cacheKey = this.getCacheKey(routedFrom, routedTo, mode)
    if (!options?.skipCache) {
      const cached = this.routeCache.get(cacheKey)
      if (cached && Date.now() - cached.timestamp < this.cacheTtlMs) {
        return cached.result
      }
    }

    // Deduplication & In-Flight Request Cancellation
    const inFlightKey = options?.requestKey || `${mode}_${cacheKey}`
    if (this.inFlightRequests.has(inFlightKey)) {
      this.inFlightRequests.get(inFlightKey)?.abort()
    }

    const abortController = new AbortController()
    this.inFlightRequests.set(inFlightKey, abortController)

    try {
      const result = await this.provider.getRoute(
        routedFrom,
        routedTo,
        mode,
        abortController.signal
      )

      // Campus Footpath Anomaly Detection:
      // If a pedestrian walking route is > 3x the straight-line distance for journeys under 1500m,
      // the map provider lacks campus pathways. Fall back to direct walking path.
      if (mode === "walking" && linearDist < 1500) {
        if (result.distanceMeters > 3 * linearDist) {
          const directDuration = Math.max(30, Math.round(linearDist / 1.33)) // ~80m/min
          const anomalyResult: RouteResult = {
            geometry: [
              [from.lat, from.lng],
              [to.lat, to.lng]
            ],
            distanceMeters: linearDist,
            durationSeconds: directDuration,
            mode: "walking",
            isFallback: true,
            warning: "Campus internal paths not mapped; showing direct walking line",
            snappedOrigin,
            snappedDestination
          }
          this.routeCache.set(cacheKey, { result: anomalyResult, timestamp: Date.now() })
          return anomalyResult
        }
      }

      // Attach snapped origins if available
      const finalResult: RouteResult = {
        ...result,
        snappedOrigin: result.snappedOrigin || snappedOrigin,
        snappedDestination: result.snappedDestination || snappedDestination
      }

      // Cache successful or fallback result
      this.routeCache.set(cacheKey, { result: finalResult, timestamp: Date.now() })
      return finalResult
    } catch (err: any) {
      if (err.name === "AbortError") {
        throw err
      }

      // Safe fallback on provider error / rate limit (429) / offline
      console.warn("[RoutingService] getRoute failed, returning straight-line fallback:", err)
      const fallbackResult: RouteResult = {
        geometry: [
          [from.lat, from.lng],
          [to.lat, to.lng]
        ],
        distanceMeters: linearDist,
        durationSeconds: Math.round(linearDist / (mode === "walking" ? 1.33 : 6.67)),
        mode,
        isFallback: true,
        warning: "Offline / road network unavailable"
      }
      return fallbackResult
    } finally {
      this.inFlightRequests.delete(inFlightKey)
    }
  }

  /**
   * Snaps a coordinate to the nearest road with caching
   */
  public async snapToRoad(
    point: Coordinates,
    mode: RoutingMode
  ): Promise<SnappedPoint | null> {
    const key = `${mode}:${point.lat.toFixed(4)},${point.lng.toFixed(4)}`
    const cached = this.snapCache.get(key)
    if (cached && Date.now() - cached.timestamp < this.cacheTtlMs) {
      return cached.snapped
    }

    try {
      const snapped = await this.provider.snapToRoad(point, mode)
      this.snapCache.set(key, { snapped, timestamp: Date.now() })
      return snapped
    } catch {
      return null
    }
  }

  /**
   * Trims the route geometry as the user moves along it,
   * recalculating remaining distance and ETA locally without any network requests.
   */
  public trimRoute(
    routeGeometry: [number, number][],
    currentPos: Coordinates,
    deviationThresholdMeters = 30
  ): TrimmedRouteResult {
    if (!routeGeometry || routeGeometry.length < 2) {
      return {
        geometry: routeGeometry || [],
        remainingDistanceMeters: 0,
        remainingDurationSeconds: 0,
        isOffRoute: false,
        distanceToRouteMeters: 0,
        progressRatio: 1
      }
    }

    let minDistance = Infinity
    let closestSegmentIndex = 0
    let closestProjectedPoint: Coordinates = { lat: routeGeometry[0][0], lng: routeGeometry[0][1] }

    // Find the closest segment on the polyline to the current position
    for (let i = 0; i < routeGeometry.length - 1; i++) {
      const a: Coordinates = { lat: routeGeometry[i][0], lng: routeGeometry[i][1] }
      const b: Coordinates = { lat: routeGeometry[i + 1][0], lng: routeGeometry[i + 1][1] }
      const projection = this.projectPointOnSegment(currentPos, a, b)

      if (projection.distanceMeters < minDistance) {
        minDistance = projection.distanceMeters
        closestSegmentIndex = i
        closestProjectedPoint = projection.point
      }
    }

    const isOffRoute = minDistance > deviationThresholdMeters

    // Build the remaining sliced geometry:
    // Start from current location or closest projected point, followed by the rest of the polyline
    const remainingGeometry: [number, number][] = [
      [currentPos.lat, currentPos.lng],
      [closestProjectedPoint.lat, closestProjectedPoint.lng],
      ...routeGeometry.slice(closestSegmentIndex + 1)
    ]

    // Calculate total original length vs remaining length
    let totalLength = 0
    for (let i = 0; i < routeGeometry.length - 1; i++) {
      totalLength += getDistanceInMeters(
        routeGeometry[i][0],
        routeGeometry[i][1],
        routeGeometry[i + 1][0],
        routeGeometry[i + 1][1]
      )
    }

    let remainingDistanceMeters = 0
    for (let i = 0; i < remainingGeometry.length - 1; i++) {
      remainingDistanceMeters += getDistanceInMeters(
        remainingGeometry[i][0],
        remainingGeometry[i][1],
        remainingGeometry[i + 1][0],
        remainingGeometry[i + 1][1]
      )
    }

    // Estimate duration: assume ~25 km/h driving average (6.9 m/s) or 80m/min walking
    const remainingDurationSeconds = Math.max(10, Math.round(remainingDistanceMeters / 6.9))
    const progressRatio = totalLength > 0 ? Math.min(1, Math.max(0, 1 - remainingDistanceMeters / totalLength)) : 0

    return {
      geometry: remainingGeometry,
      remainingDistanceMeters: Math.round(remainingDistanceMeters),
      remainingDurationSeconds,
      isOffRoute,
      distanceToRouteMeters: Math.round(minDistance),
      progressRatio
    }
  }

  /**
   * Projects a point P onto segment AB and returns closest point, distance, and factor t [0, 1]
   */
  private projectPointOnSegment(
    p: Coordinates,
    a: Coordinates,
    b: Coordinates
  ): { point: Coordinates; distanceMeters: number; t: number } {
    const latFactor = 111139
    const avgLatRad = ((a.lat + b.lat) / 2) * (Math.PI / 180)
    const lngFactor = 111139 * Math.cos(avgLatRad)

    const dx = (b.lng - a.lng) * lngFactor
    const dy = (b.lat - a.lat) * latFactor

    const segLengthSq = dx * dx + dy * dy
    if (segLengthSq === 0) {
      const dist = getDistanceInMeters(p.lat, p.lng, a.lat, a.lng)
      return { point: a, distanceMeters: dist, t: 0 }
    }

    const px = (p.lng - a.lng) * lngFactor
    const py = (p.lat - a.lat) * latFactor

    const t = Math.max(0, Math.min(1, (px * dx + py * dy) / segLengthSq))

    const projLng = a.lng + (t * dx) / lngFactor
    const projLat = a.lat + (t * dy) / latFactor

    const dist = getDistanceInMeters(p.lat, p.lng, projLat, projLng)
    return { point: { lat: projLat, lng: projLng }, distanceMeters: dist, t }
  }

  /**
   * Checks whether a coordinate is off the planned route by more than threshold
   */
  public isOffRoute(
    routeGeometry: [number, number][],
    currentPos: Coordinates,
    thresholdMeters = 30
  ): boolean {
    if (!routeGeometry || routeGeometry.length < 2) return false
    for (let i = 0; i < routeGeometry.length - 1; i++) {
      const a = { lat: routeGeometry[i][0], lng: routeGeometry[i][1] }
      const b = { lat: routeGeometry[i + 1][0], lng: routeGeometry[i + 1][1] }
      const proj = this.projectPointOnSegment(currentPos, a, b)
      if (proj.distanceMeters <= thresholdMeters) {
        return false // Within acceptable corridor
      }
    }
    return true
  }

  private getCacheKey(from: Coordinates, to: Coordinates, mode: RoutingMode): string {
    return `${mode}_${from.lat.toFixed(4)},${from.lng.toFixed(4)}->${to.lat.toFixed(4)},${to.lng.toFixed(4)}`
  }
}

// Global Singleton Instance
export const routingService = new RoutingService()
