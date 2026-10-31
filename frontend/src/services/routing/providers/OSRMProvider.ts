/**
 * OSRM Routing Provider (Open Source Routing Machine)
 *
 * NOTE ON PRODUCTION USAGE:
 * The default endpoint (https://router.project-osrm.org) is a free public demo server maintained
 * by the OSRM project for testing and development only. It has strict rate limits and no SLA.
 *
 * FOR PRODUCTION:
 * Replace this provider with Google Directions API, Mapbox Directions API, or a self-hosted
 * Valhalla/OSRM instance hosted on your own infrastructure (e.g. AWS/GCP or a $10/mo Hetzner VPS).
 * Always supply provider credentials via environment variables (e.g. VITE_ROUTING_API_KEY, VITE_ROUTING_BASE_URL),
 * never in committed client source code.
 */

import type { IRoutingProvider, RoutingMode, Coordinates, RouteResult, SnappedPoint, RouteStep } from "../types"
import { getDistanceInMeters } from "../../../utils/locationService"

/**
 * Decodes standard Google / OSRM encoded polyline string (5-digit precision)
 */
export function decodePolyline(encoded: string, precision = 5): [number, number][] {
  const factor = Math.pow(10, precision)
  let index = 0
  let lat = 0
  let lng = 0
  const coordinates: [number, number][] = []

  while (index < encoded.length) {
    let byte: number
    let shift = 0
    let result = 0
    do {
      byte = encoded.charCodeAt(index++) - 63
      result |= (byte & 0x1f) << shift
      shift += 5
    } while (byte >= 0x20)
    const deltaLat = result & 1 ? ~(result >> 1) : result >> 1
    lat += deltaLat

    shift = 0
    result = 0
    do {
      byte = encoded.charCodeAt(index++) - 63
      result |= (byte & 0x1f) << shift
      shift += 5
    } while (byte >= 0x20)
    const deltaLng = result & 1 ? ~(result >> 1) : result >> 1
    lng += deltaLng

    coordinates.push([lat / factor, lng / factor])
  }

  return coordinates
}

export class OSRMProvider implements IRoutingProvider {
  public readonly name = "OSRM"
  private baseUrl: string

  constructor(customBaseUrl?: string) {
    this.baseUrl =
      customBaseUrl ||
      import.meta.env.VITE_ROUTING_BASE_URL ||
      "https://router.project-osrm.org"
  }

  /**
   * Fetches full road-following geometry between two points
   */
  async getRoute(
    from: Coordinates,
    to: Coordinates,
    mode: RoutingMode,
    signal?: AbortSignal
  ): Promise<RouteResult> {
    const profile = mode === "walking" ? "foot" : "driving"
    // Request full overview (unsimplified coordinates) and GeoJSON geometries
    const url = `${this.baseUrl}/route/v1/${profile}/${from.lng},${from.lat};${to.lng},${to.lat}?overview=full&geometries=geojson&steps=true`

    try {
      const response = await fetch(url, {
        signal: signal || AbortSignal.timeout(6000),
        headers: { Accept: "application/json" }
      })

      if (!response.ok) {
        throw new Error(`OSRM HTTP error: ${response.status} ${response.statusText}`)
      }

      const data = await response.json()

      if (data.code !== "Ok" || !data.routes || data.routes.length === 0) {
        throw new Error(`OSRM returned no routes: ${data.code || "unknown"}`)
      }

      const primaryRoute = data.routes[0]

      // Parse geometry
      let geometry: [number, number][] = []
      if (typeof primaryRoute.geometry === "string") {
        geometry = decodePolyline(primaryRoute.geometry)
      } else if (primaryRoute.geometry?.coordinates) {
        // GeoJSON [lng, lat] -> Leaflet [lat, lng]
        geometry = primaryRoute.geometry.coordinates.map(
          ([lng, lat]: [number, number]) => [lat, lng] as [number, number]
        )
      }

      if (geometry.length === 0) {
        throw new Error("OSRM returned empty geometry coordinates")
      }

      // Snapped waypoints from response
      const snappedOrigin: Coordinates | undefined = data.waypoints?.[0]?.location
        ? { lat: data.waypoints[0].location[1], lng: data.waypoints[0].location[0] }
        : undefined

      const snappedDestination: Coordinates | undefined = data.waypoints?.[1]?.location
        ? { lat: data.waypoints[1].location[1], lng: data.waypoints[1].location[0] }
        : undefined

      // Steps if available
      const steps: RouteStep[] = []
      if (primaryRoute.legs?.[0]?.steps) {
        for (const step of primaryRoute.legs[0].steps) {
          steps.push({
            instruction: step.maneuver?.type,
            name: step.name,
            distanceMeters: Math.round(step.distance || 0),
            durationSeconds: Math.round(step.duration || 0)
          })
        }
      }

      return {
        geometry,
        distanceMeters: Math.round(primaryRoute.distance || 0),
        durationSeconds: Math.round(primaryRoute.duration || 0),
        mode,
        isFallback: false,
        snappedOrigin,
        snappedDestination,
        steps
      }
    } catch (err: any) {
      if (err.name === "AbortError") {
        throw err // Re-throw aborts cleanly so cancellation is handled
      }
      console.warn(`[OSRMProvider] Route failed (${mode}):`, err.message || err)
      return this.createFallbackRoute(from, to, mode, err.message)
    }
  }

  /**
   * Snaps a raw coordinate to the nearest routable road/footpath network
   */
  async snapToRoad(
    point: Coordinates,
    mode: RoutingMode,
    signal?: AbortSignal
  ): Promise<SnappedPoint | null> {
    const profile = mode === "walking" ? "foot" : "driving"
    const url = `${this.baseUrl}/nearest/v1/${profile}/${point.lng},${point.lat}?number=1`

    try {
      const response = await fetch(url, {
        signal: signal || AbortSignal.timeout(3000),
        headers: { Accept: "application/json" }
      })

      if (!response.ok) return null
      const data = await response.json()

      if (data.code === "Ok" && data.waypoints && data.waypoints[0]) {
        const wp = data.waypoints[0]
        const [lng, lat] = wp.location
        return {
          lat,
          lng,
          name: wp.name,
          distanceMeters: Math.round(wp.distance || 0)
        }
      }
      return null
    } catch (err: any) {
      if (err.name !== "AbortError") {
        console.warn("[OSRMProvider] Nearest road snap failed:", err.message)
      }
      return null
    }
  }

  /**
   * Safe straight-line fallback with realistic duration estimates
   */
  private createFallbackRoute(
    from: Coordinates,
    to: Coordinates,
    mode: RoutingMode,
    errorMsg?: string
  ): RouteResult {
    const linearDistMeters = getDistanceInMeters(from.lat, from.lng, to.lat, to.lng)
    // Speed heuristics: Walking ~4.8 km/h (1.33 m/s); Driving in city traffic ~24 km/h (6.67 m/s)
    const speedMps = mode === "walking" ? 1.33 : 6.67
    const durationSeconds = Math.max(30, Math.round(linearDistMeters / speedMps))

    return {
      geometry: [
        [from.lat, from.lng],
        [to.lat, to.lng]
      ],
      distanceMeters: linearDistMeters,
      durationSeconds,
      mode,
      isFallback: true,
      warning: errorMsg || "Direct line fallback (road network unavailable)"
    }
  }
}
