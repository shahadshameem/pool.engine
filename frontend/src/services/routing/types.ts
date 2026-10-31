/**
 * Waymate Routing Layer Core Types & Interfaces
 */

export type RoutingMode = "driving" | "walking"

export interface Coordinates {
  lat: number
  lng: number
}

export interface SnappedPoint extends Coordinates {
  name?: string
  distanceMeters: number
}

export interface RouteStep {
  instruction?: string
  distanceMeters: number
  durationSeconds: number
  name?: string
}

export interface RouteResult {
  /** Array of [lat, lng] coordinates formatted for Leaflet */
  geometry: [number, number][]
  distanceMeters: number
  durationSeconds: number
  mode: RoutingMode
  isFallback: boolean
  warning?: string
  snappedOrigin?: Coordinates
  snappedDestination?: Coordinates
  steps?: RouteStep[]
}

export interface IRoutingProvider {
  name: string
  getRoute(
    from: Coordinates,
    to: Coordinates,
    mode: RoutingMode,
    signal?: AbortSignal
  ): Promise<RouteResult>

  snapToRoad(
    point: Coordinates,
    mode: RoutingMode,
    signal?: AbortSignal
  ): Promise<SnappedPoint | null>
}

export interface TrimmedRouteResult {
  /** The remaining geometry from current position to destination */
  geometry: [number, number][]
  remainingDistanceMeters: number
  remainingDurationSeconds: number
  /** True if the user is more than deviation threshold (e.g. 30m) away from the route */
  isOffRoute: boolean
  /** Perpendicular/closest distance to the current planned route */
  distanceToRouteMeters: number
  /** Progress along the original route (0.0 = start, 1.0 = completed) */
  progressRatio: number
}

export interface SmartMeetingPoint {
  point: Coordinates
  distanceA: number
  distanceB: number
  durationMinutesA: number
  durationMinutesB: number
  description: string
}
