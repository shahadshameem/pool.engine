/**
 * 100% Free Open-Source Location, Autocomplete, GPS & Uber H3 Spatial Service
 * Center: Trivandrum (Thiruvananthapuram), Kerala (CET, Technopark, Kazhakootam Corridor)
 * Uses OpenStreetMap, Photon (Trivandrum Bounded), Nominatim, OSRM, and Uber H3 (v4)
 * Zero API Keys & Zero Cost Required
 */

import { latLngToCell, gridDisk, cellToBoundary } from "h3-js"
import { resolveCampusZone, CAMPUS_ZONES, type CampusZoneMatch } from "../config/campusZones"

export interface LocationPoint {
  name: string
  subtext?: string
  area?: string
  lat: number
  lng: number
  category?: string
  isPreset?: boolean
  isLiveGps?: boolean
  distanceFromUserMeters?: number
  distanceMeters?: number
  distanceFormatted?: string
  address?: string
  matchedZoneId?: string
  rawGps?: { lat: number; lng: number; accuracy: number }
  isLowAccuracy?: boolean
  accuracyMeters?: number
}

export interface RouteSummary {
  polylineCoords: [number, number][]
  coordinates: [number, number][] // Alias for backwards compatibility
  distanceKm: number
  durationMins: number
}

export interface CircleMatchResult {
  isMatch: boolean
  sourceDistance: number
  destDistance: number
}

// 1. Trivandrum Map Constants
export const DEFAULT_CENTER = { lat: 8.5459, lng: 76.9063 } // College of Engineering Trivandrum
export const TVM_BOUNDING_BOX = "76.78,8.35,77.10,8.68" // minLon,minLat,maxLon,maxLat covering Trivandrum metro area
export const H3_RES = 8 // Uber H3 Resolution 8 (~460m edge length / 0.73 km² area)

// 2. CAMPUS_PRESETS Array: Strictly 3 Instant Presets
export const CAMPUS_PRESETS: LocationPoint[] = [
  {
    name: "College of Engineering Trivandrum",
    subtext: "Sreekaryam, Thiruvananthapuram",
    area: "Sreekaryam",
    category: "Campus",
    lat: 8.5459,
    lng: 76.9063,
    isPreset: true
  },
  {
    name: "Trivandrum Central Railway Station",
    subtext: "Thampanoor, Thiruvananthapuram",
    area: "Thampanoor",
    category: "Transit",
    lat: 8.4875,
    lng: 76.9525,
    isPreset: true
  },
  {
    name: "Kochuveli Railway Station",
    subtext: "Kochuveli, Thiruvananthapuram",
    area: "Kochuveli",
    category: "Transit",
    lat: 8.5089,
    lng: 76.9014,
    isPreset: true
  }
]

// 3. searchLocations (Trivandrum-Locked Hybrid Autocomplete with Distance Calculation)
export async function searchLocations(
  query: string,
  userLat?: number,
  userLng?: number
): Promise<LocationPoint[]> {
  const clean = (query || "").trim().toLowerCase()
  let list: LocationPoint[] = []

  if (!clean) {
    list = [...CAMPUS_PRESETS]
  } else {
    // Step 1: Filter Campus Presets by name, subtext, area, or category
    const presetMatches = CAMPUS_PRESETS.filter(p =>
      p.name.toLowerCase().includes(clean) ||
      (p.subtext && p.subtext.toLowerCase().includes(clean)) ||
      (p.area && p.area.toLowerCase().includes(clean)) ||
      (p.category && p.category.toLowerCase().includes(clean))
    )

    // Step 2: Query Photon API strictly bounded and biased to Trivandrum if query >= 2 chars
    let photonMatches: LocationPoint[] = []
    if (clean.length >= 2) {
      try {
        const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(clean)}&lat=${DEFAULT_CENTER.lat}&lon=${DEFAULT_CENTER.lng}&bbox=${TVM_BOUNDING_BOX}&limit=8`
        const res = await fetch(url, { signal: AbortSignal.timeout(3000) })
        if (res.ok) {
          const data = await res.json()
          if (data.features && Array.isArray(data.features)) {
            photonMatches = data.features
              .filter((f: any) => f.geometry?.coordinates && f.properties?.name)
              .map((f: any) => {
                const props = f.properties || {}
                const [lng, lat] = f.geometry.coordinates
                const parts = [
                  props.street,
                  props.district,
                  props.city || props.county,
                  props.state
                ].filter(Boolean)

                const uniqueParts = Array.from(new Set(parts))
                const subtext = uniqueParts.slice(0, 3).join(", ") || props.city || "Thiruvananthapuram, Kerala"
                const area = props.district || props.city || props.suburb || props.street || "Trivandrum"

                return {
                  name: props.name,
                  subtext,
                  area,
                  lat,
                  lng,
                  category: props.osm_value || "Trivandrum",
                  isPreset: false,
                  address: props.name
                }
              })
          }
        }
      } catch (err) {
        console.warn("[Photon API] Trivandrum lookup failed, using presets:", err)
      }
    }

    // Deduplicate results by name
    const seenNames = new Set<string>()
    for (const item of [...presetMatches, ...photonMatches]) {
      const key = item.name.toLowerCase()
      if (!seenNames.has(key)) {
        seenNames.add(key)
        list.push(item)
      }
    }
  }

  // Calculate distance from user's current location if provided
  if (typeof userLat === "number" && typeof userLng === "number") {
    const withDist = list.map(item => {
      const dist = getDistanceInMeters(userLat, userLng, item.lat, item.lng)
      return {
        ...item,
        distanceFromUserMeters: dist,
        distanceMeters: dist,
        distanceFormatted: formatDistance(dist)
      }
    })

    if (!clean) {
      withDist.sort((a, b) => (a.distanceFromUserMeters ?? 0) - (b.distanceFromUserMeters ?? 0))
    }
    return withDist
  }

  return list
}

// 4. Reverse Geocoding (Nominatim API)
export async function reverseGeocode(lat: number, lng: number): Promise<string> {
  try {
    const url = `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${lat}&lon=${lng}`
    const res = await fetch(url, {
      headers: {
        "Accept-Language": "en"
      },
      signal: AbortSignal.timeout(3000)
    })
    if (res.ok) {
      const data = await res.json()
      if (data.display_name) {
        const segments = data.display_name.split(", ").slice(0, 3).join(", ")
        return segments || data.display_name
      }
    }
  } catch (err) {
    console.warn("[Nominatim] Reverse geocode failed, returning coordinates:", err)
  }

  return `${lat.toFixed(4)}, ${lng.toFixed(4)}`
}

export interface GpsAcquisitionResult {
  lat: number
  lng: number
  accuracy: number
  isTimeout: boolean
}

/**
 * Acquires a high-accuracy GPS fix.
 * Uses watchPosition to listen for fixes with accuracy <= 50m (or waits up to 10 seconds).
 * Clears watchPosition immediately once a satisfactory fix is obtained or upon timeout.
 */
export function acquireHighAccuracyGps(
  targetAccuracyMeters = 50,
  timeoutMs = 10000
): Promise<GpsAcquisitionResult> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      reject(new Error("Geolocation is not supported by your browser"))
      return
    }

    let watchId: number | null = null
    let bestFix: { lat: number; lng: number; accuracy: number } | null = null
    let hasResolved = false

    const cleanup = () => {
      if (watchId !== null) {
        navigator.geolocation.clearWatch(watchId)
        watchId = null
      }
      if (timerId) {
        clearTimeout(timerId)
      }
    }

    const timerId = setTimeout(() => {
      if (hasResolved) return
      hasResolved = true
      cleanup()
      if (bestFix) {
        resolve({ ...bestFix, isTimeout: true })
      } else {
        reject(new Error("GPS acquisition timed out before acquiring location"))
      }
    }, timeoutMs)

    watchId = navigator.geolocation.watchPosition(
      (pos) => {
        const accuracy = pos.coords.accuracy
        const lat = pos.coords.latitude
        const lng = pos.coords.longitude

        if (!bestFix || accuracy < bestFix.accuracy) {
          bestFix = { lat, lng, accuracy }
        }

        // If accuracy <= 50m, resolve immediately and stop watching!
        if (accuracy <= targetAccuracyMeters) {
          if (hasResolved) return
          hasResolved = true
          cleanup()
          resolve({ lat, lng, accuracy, isTimeout: false })
        }
      },
      (err) => {
        if (!bestFix && !hasResolved) {
          hasResolved = true
          cleanup()
          reject(err)
        }
      },
      {
        enableHighAccuracy: true,
        timeout: timeoutMs,
        maximumAge: 0
      }
    )
  })
}

// 5. Current Live GPS Location with Campus Zone Auto-Assignment & Accuracy Filtering
export async function getCurrentLiveLocation(): Promise<LocationPoint> {
  const gps = await acquireHighAccuracyGps(50, 10000)
  const rawGps = { lat: gps.lat, lng: gps.lng, accuracy: gps.accuracy }

  let matchedZone: CampusZoneMatch | null = null
  try {
    matchedZone = resolveCampusZone(gps.lat, gps.lng)
  } catch (err) {
    // If dev coordinate validation fails, rethrow loudly
    throw err
  }

  const cetZone = CAMPUS_ZONES.find(z => z.id === "cet-front-gate" || z.id === "cet")
  const distToCet = cetZone ? Math.round(getDistanceInMeters(gps.lat, gps.lng, cetZone.lat, cetZone.lng)) : null
  console.log("[AutoLocation] GPS Fix Analysis:", {
    userLat: gps.lat,
    userLng: gps.lng,
    accuracyMeters: Math.round(gps.accuracy),
    distanceToCetGateMeters: distToCet,
    cetRadiusMeters: cetZone?.radiusMeters,
    matchedZone: matchedZone?.zone.id || "NONE (Outside radius)",
    rule1_inRadius: Boolean(matchedZone),
    rule2_accuracyUnder50: gps.accuracy <= 50
  })

  // Accuracy rule: auto-assign a zone ONLY if accuracy <= 50 m AND point is within zone radius
  if (matchedZone && gps.accuracy <= 50) {
    return {
      name: matchedZone.zone.name,
      subtext: matchedZone.zone.address,
      area: matchedZone.zone.name,
      lat: matchedZone.zone.lat,
      lng: matchedZone.zone.lng,
      category: "Campus",
      isPreset: true,
      isLiveGps: true,
      matchedZoneId: matchedZone.zone.id,
      rawGps,
      accuracyMeters: gps.accuracy,
      address: matchedZone.zone.address
    }
  }

  // If point is within zone radius but accuracy is worse than 50m:
  if (matchedZone && gps.accuracy > 50) {
    const reverseName = await reverseGeocode(gps.lat, gps.lng)
    return {
      name: reverseName || "Current Location",
      subtext: `Low GPS accuracy (±${Math.round(gps.accuracy)}m) · Confirm on map`,
      area: reverseName,
      lat: gps.lat,
      lng: gps.lng,
      category: "Live GPS",
      isPreset: false,
      isLiveGps: true,
      rawGps,
      isLowAccuracy: true,
      accuracyMeters: gps.accuracy,
      address: reverseName
    }
  }

  // Outside campus zones: fallback to standard reverse geocoding
  const address = await reverseGeocode(gps.lat, gps.lng)
  return {
    name: address || "Current Location",
    subtext: gps.accuracy > 50 ? `Low GPS accuracy (±${Math.round(gps.accuracy)}m)` : "Detected via Live GPS",
    area: address,
    lat: gps.lat,
    lng: gps.lng,
    category: "Live GPS",
    isPreset: false,
    isLiveGps: true,
    rawGps,
    isLowAccuracy: gps.accuracy > 50,
    accuracyMeters: gps.accuracy,
    address
  }
}

// Alias for getAutoLiveLocation
export const getAutoLiveLocation = getCurrentLiveLocation

// 6. Haversine Distance Calculation & Formatting
export function getDistanceInMeters(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371000 // Earth radius in meters
  const dLat = ((lat2 - lat1) * Math.PI) / 180
  const dLng = ((lng2 - lng1) * Math.PI) / 180
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLng / 2) *
      Math.sin(dLng / 2)
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
  return Math.round(R * c)
}

/**
 * Formats distance in meters cleanly for UI display (e.g., "240 m" or "1.4 km")
 */
export function formatDistance(meters: number): string {
  if (meters < 1000) {
    return `${Math.round(meters)} m`
  }
  return `${(meters / 1000).toFixed(1)} km`
}

// Helper to normalize location coordinates
function extractCoords(loc: any): { lat: number; lng: number } {
  if (!loc) return DEFAULT_CENTER
  const lat = typeof loc.lat === "number" ? loc.lat : loc.latitude ?? DEFAULT_CENTER.lat
  const lng = typeof loc.lng === "number" ? loc.lng : loc.longitude ?? DEFAULT_CENTER.lng
  return { lat, lng }
}

// 7. Circle-based Matching
export function isRideWithinCircles(
  rider: { source: any; destination: any },
  driver: { source: any; destination: any },
  sourceRadiusMeters = 1000,
  destRadiusMeters = 1000
): CircleMatchResult {
  const rSrc = extractCoords(rider.source)
  const dSrc = extractCoords(driver.source)
  const rDst = extractCoords(rider.destination)
  const dDst = extractCoords(driver.destination)

  const sourceDistance = getDistanceInMeters(rSrc.lat, rSrc.lng, dSrc.lat, dSrc.lng)
  const destDistance = getDistanceInMeters(rDst.lat, rDst.lng, dDst.lat, dDst.lng)

  const isMatch = sourceDistance <= sourceRadiusMeters && destDistance <= destRadiusMeters

  return {
    isMatch,
    sourceDistance,
    destDistance
  }
}

// 8. Driving Route via OSRM / Unified Routing Service
export async function fetchDrivingRoute(
  source: { lat: number; lng: number },
  destination: { lat: number; lng: number }
): Promise<RouteSummary> {
  const linearDistanceKm = Math.round((getDistanceInMeters(source.lat, source.lng, destination.lat, destination.lng) / 1000) * 10) / 10
  const fallbackSummary = {
    polylineCoords: [
      [source.lat, source.lng],
      [destination.lat, destination.lng]
    ] as [number, number][],
    coordinates: [
      [source.lat, source.lng],
      [destination.lat, destination.lng]
    ] as [number, number][],
    distanceKm: linearDistanceKm,
    durationMins: Math.round(linearDistanceKm * 2.5)
  }

  try {
    const url = `https://router.project-osrm.org/route/v1/driving/${source.lng},${source.lat};${destination.lng},${destination.lat}?overview=full&geometries=geojson`
    const res = await fetch(url, { signal: AbortSignal.timeout(3000) })
    if (res.ok) {
      const data = await res.json()
      if (data.routes && data.routes[0]) {
        const route = data.routes[0]
        const polylineCoords: [number, number][] = route.geometry.coordinates.map(
          ([lng, lat]: [number, number]) => [lat, lng]
        )
        const distanceKm = Math.round((route.distance / 1000) * 10) / 10
        const durationMins = Math.round(route.duration / 60)
        return {
          polylineCoords,
          coordinates: polylineCoords,
          distanceKm,
          durationMins
        }
      }
    }
  } catch (err) {
    console.warn("[locationService] fetchDrivingRoute fallback:", err)
  }

  return fallbackSummary
}

// 9. Uber H3 Helper Functions (h3-js v4)
export function getH3Cell(lat: number, lng: number, res = H3_RES): string {
  return latLngToCell(lat, lng, res)
}

export function getH3SearchDisk(lat: number, lng: number, radiusMeters = 1000): string[] {
  const originCell = latLngToCell(lat, lng, H3_RES)
  const k = radiusMeters <= 600 ? 1 : radiusMeters <= 1400 ? 2 : 3
  return gridDisk(originCell, k)
}

export function getH3DiskPolygons(lat: number, lng: number, radiusMeters = 1000): [number, number][][] {
  const cells = getH3SearchDisk(lat, lng, radiusMeters)
  return cells.map(cellId => cellToBoundary(cellId) as [number, number][])
}

export default {
  DEFAULT_CENTER,
  TVM_BOUNDING_BOX,
  H3_RES,
  CAMPUS_PRESETS,
  searchLocations,
  reverseGeocode,
  getCurrentLiveLocation,
  getAutoLiveLocation,
  getDistanceInMeters,
  formatDistance,
  isRideWithinCircles,
  fetchDrivingRoute,
  getH3Cell,
  getH3SearchDisk,
  getH3DiskPolygons
}
