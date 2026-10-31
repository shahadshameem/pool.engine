import { useState, useEffect, useRef, useCallback, useMemo } from "react"
import {
  liveLocationService,
  calculateBearing
} from "../services/location/liveLocationService"
import type { LiveUserLocation } from "../services/location/liveLocationService"
import { getDistanceInMeters, formatDistance } from "../utils/locationService"

export interface ConfirmedParticipantInfo {
  uid: string
  name: string
  isCreator?: boolean
  pickupLocation?: any
}

export interface CoRiderLiveStatus {
  userId: string
  userName: string
  isCreator: boolean
  location: LiveUserLocation | null
  distanceMeters: number | null
  distanceFormatted: string | null
  walkMinutes: number | null
  walkMinutesText: string
  isStale: boolean
  staleAgoText: string | null
  isSharing: boolean
}

export interface UseLiveLocationTrackingOptions {
  rideId: string
  userId?: string
  userName?: string
  isCreator?: boolean
  role?: string // Legacy compat
  rideStatus: string
  confirmedParticipants?: ConfirmedParticipantInfo[]
  enabled?: boolean
  initialCoords?: { lat: number; lng: number }
  pickupCoords?: { lat: number; lng: number }
}

export interface UseLiveLocationTrackingResult {
  myLocation: LiveUserLocation | null
  allLocations: Record<string, LiveUserLocation>
  coRiders: CoRiderLiveStatus[]
  selectedCoRiderId: string | null
  setSelectedCoRiderId: (id: string | null) => void
  selectedCoRider: CoRiderLiveStatus | null
  allParticipantsMet: boolean
  bestGroupLocation: { lat: number; lng: number; heading?: number | null } | null
  peerLocation: LiveUserLocation | null // backward compatibility with 1-to-1 callers
  distanceBetweenUsers: number | null // backward compatibility
  distanceFormatted: string | null // backward compatibility
  isSharing: boolean
  toggleSharing: () => void
  error: string | null
  isStale: boolean
  lastPeerUpdateAgoText: string | null
  hasConsent: boolean
  grantConsent: () => void
  simulateLocationUpdate: (lat: number, lng: number, heading?: number) => void
  simulateCoRiderLocation: (coRiderId: string, name: string, lat: number, lng: number) => void
}

const CONSENT_STORAGE_KEY = "waymate_live_location_consent_v1"
const MIN_UPLOAD_INTERVAL_MS = 3000 // 3 seconds
const MIN_UPLOAD_DISTANCE_METERS = 10 // 10 meters
const STALE_THRESHOLD_MS = 30000 // 30 seconds

export function useLiveLocationTracking({
  rideId,
  userId,
  userName = "User",
  isCreator = false,
  role,
  rideStatus,
  confirmedParticipants = [],
  enabled = true,
  initialCoords,
  pickupCoords
}: UseLiveLocationTrackingOptions): UseLiveLocationTrackingResult {
  const [hasConsent, setHasConsent] = useState<boolean>(() => {
    if (typeof window === "undefined") return false
    return localStorage.getItem(CONSENT_STORAGE_KEY) === "true"
  })

  const [isSharing, setIsSharing] = useState(true)
  const [myLocation, setMyLocation] = useState<LiveUserLocation | null>(null)
  const [allLocations, setAllLocations] = useState<Record<string, LiveUserLocation>>({})
  const [selectedCoRiderId, setSelectedCoRiderId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const watchIdRef = useRef<number | null>(null)
  const lastUploadTimeRef = useRef<number>(0)
  const lastUploadedCoordsRef = useRef<{ lat: number; lng: number } | null>(null)
  const lastKnownCoordsRef = useRef<{ lat: number; lng: number } | null>(initialCoords || null)
  const lastKnownHeadingRef = useRef<number>(0)

  // 1. Consent handler
  const grantConsent = useCallback(() => {
    localStorage.setItem(CONSENT_STORAGE_KEY, "true")
    setHasConsent(true)
  }, [])

  // 2. Toggle sharing
  const toggleSharing = useCallback(() => {
    setIsSharing(prev => {
      const next = !prev
      if (!next && userId && rideId) {
        liveLocationService.deleteLiveLocation(rideId, userId).catch(console.warn)
      }
      return next
    })
  }, [rideId, userId])

  // 3. Listen to all participants' live positions in Firestore
  useEffect(() => {
    if (!rideId || !userId || !enabled) return
    if (rideStatus === "completed" || rideStatus === "cancelled") {
      setAllLocations({})
      return
    }

    const unsubscribe = liveLocationService.subscribeToLiveLocations(
      rideId,
      (locationsMap) => {
        setAllLocations(locationsMap)
      },
      (err) => {
        console.warn("[useLiveLocationTracking] Subscription error:", err)
      }
    )

    return () => unsubscribe()
  }, [rideId, userId, enabled, rideStatus])

  // 4. Compute status for all confirmed co-riders
  const coRiders: CoRiderLiveStatus[] = useMemo(() => {
    // If explicit confirmedParticipants provided, use them; otherwise use other reporting users
    const otherParticipants = confirmedParticipants.filter(p => p.uid !== userId)

    // Also include any reporting users from allLocations not yet in confirmedParticipants
    const existingUids = new Set(otherParticipants.map(p => p.uid))
    Object.values(allLocations).forEach(loc => {
      if (loc.userId !== userId && !existingUids.has(loc.userId)) {
        otherParticipants.push({
          uid: loc.userId,
          name: loc.userName,
          isCreator: Boolean(loc.isCreator)
        })
        existingUids.add(loc.userId)
      }
    })

    const now = Date.now()

    return otherParticipants.map(participant => {
      const liveLoc = allLocations[participant.uid] || null
      let isStale = false
      let staleAgoText: string | null = null

      if (liveLoc) {
        const updatedMillis = liveLoc.updatedAt?.toMillis
          ? liveLoc.updatedAt.toMillis()
          : (liveLoc.updatedAt?.seconds ? liveLoc.updatedAt.seconds * 1000 : now)
        const elapsed = now - updatedMillis
        if (elapsed > STALE_THRESHOLD_MS) {
          isStale = true
          const secs = Math.round(elapsed / 1000)
          staleAgoText = secs < 60 ? `Updated ${secs}s ago` : `Updated ${Math.round(secs / 60)}m ago`
        }
      }

      // Compute distance from "You" to this co-rider
      let distMeters: number | null = null
      if (myLocation && liveLoc && liveLoc.lat && liveLoc.lng) {
        distMeters = getDistanceInMeters(myLocation.lat, myLocation.lng, liveLoc.lat, liveLoc.lng)
      } else if (pickupCoords && liveLoc && liveLoc.lat && liveLoc.lng) {
        distMeters = getDistanceInMeters(pickupCoords.lat, pickupCoords.lng, liveLoc.lat, liveLoc.lng)
      }

      const distFormatted = distMeters !== null ? formatDistance(distMeters) : null
      const walkMinutes = distMeters !== null ? Math.max(1, Math.round(distMeters / 80)) : null
      const walkMinutesText = walkMinutes !== null ? `${walkMinutes} min` : ""

      return {
        userId: participant.uid,
        userName: participant.name,
        isCreator: Boolean(participant.isCreator),
        location: liveLoc,
        distanceMeters: distMeters,
        distanceFormatted: distFormatted,
        walkMinutes,
        walkMinutesText,
        isStale,
        staleAgoText,
        isSharing: liveLoc?.isSharing ?? false
      }
    })
  }, [confirmedParticipants, allLocations, userId, myLocation, pickupCoords])

  // 5. Select Co-Rider: Default to nearest co-rider
  const selectedCoRider = useMemo(() => {
    if (coRiders.length === 0) return null
    if (selectedCoRiderId) {
      const match = coRiders.find(c => c.userId === selectedCoRiderId)
      if (match) return match
    }
    // Default: Sort by distance and pick the nearest
    const sorted = [...coRiders].sort((a, b) => (a.distanceMeters ?? Infinity) - (b.distanceMeters ?? Infinity))
    return sorted[0] || null
  }, [coRiders, selectedCoRiderId])

  // 6. Proximity: "You've all met"
  // When everyone confirmed is within about 30-50m of each other (allowing for campus GPS error)
  const allParticipantsMet = useMemo(() => {
    if (rideStatus === "started" || rideStatus === "completed" || rideStatus === "cancelled") {
      return false
    }
    if (coRiders.length === 0) {
      // Single participant waiting for co-riders
      return false
    }

    const reportingLocations: Array<{ lat: number; lng: number }> = []
    if (myLocation) {
      reportingLocations.push({ lat: myLocation.lat, lng: myLocation.lng })
    }
    coRiders.forEach(c => {
      if (c.location && c.location.lat && c.location.lng) {
        reportingLocations.push({ lat: c.location.lat, lng: c.location.lng })
      }
    })

    // If not all confirmed participants are reporting live locations, they have not all met yet
    const totalExpected = (confirmedParticipants.length > 0) ? confirmedParticipants.length : (coRiders.length + 1)
    if (reportingLocations.length < totalExpected || reportingLocations.length < 2) {
      return false
    }

    // Check maximum distance between any two confirmed students in the group
    let maxDistance = 0
    for (let i = 0; i < reportingLocations.length; i++) {
      for (let j = i + 1; j < reportingLocations.length; j++) {
        const d = getDistanceInMeters(
          reportingLocations[i].lat,
          reportingLocations[i].lng,
          reportingLocations[j].lat,
          reportingLocations[j].lng
        )
        if (d > maxDistance) {
          maxDistance = d
        }
      }
    }

    // Check if all confirmed participants are at the pickup point (<= 25m)
    if (pickupCoords && typeof pickupCoords.lat === "number" && typeof pickupCoords.lng === "number") {
      const allAtPickup = reportingLocations.every(
        loc => getDistanceInMeters(loc.lat, loc.lng, pickupCoords.lat, pickupCoords.lng) <= 25
      )
      if (allAtPickup) return true
    }

    // Require immediate visual/walking proximity (<= 20m) to declare participants have met
    return maxDistance <= 20
  }, [rideStatus, coRiders, myLocation, confirmedParticipants, pickupCoords])

  // 7. Phase B Group Position: Participant with best accuracy
  const bestGroupLocation = useMemo(() => {
    const activeLocations = [
      ...(myLocation ? [myLocation] : []),
      ...Object.values(allLocations).filter(l => l.isSharing && l.lat && l.lng)
    ]
    if (activeLocations.length === 0) return null

    // Prefer best (lowest meter error) accuracy
    activeLocations.sort((a, b) => (a.accuracy ?? 50) - (b.accuracy ?? 50))
    const best = activeLocations[0]
    return {
      lat: best.lat,
      lng: best.lng,
      heading: best.heading
    }
  }, [myLocation, allLocations])

  // 8. Watch user's own GPS location and upload with throttling
  useEffect(() => {
    if (!hasConsent || !isSharing || !enabled || !rideId || !userId) {
      if (watchIdRef.current !== null && typeof navigator !== "undefined" && navigator.geolocation) {
        navigator.geolocation.clearWatch(watchIdRef.current)
        watchIdRef.current = null
      }
      return
    }

    if (rideStatus === "completed" || rideStatus === "cancelled") {
      if (watchIdRef.current !== null && typeof navigator !== "undefined" && navigator.geolocation) {
        navigator.geolocation.clearWatch(watchIdRef.current)
        watchIdRef.current = null
      }
      liveLocationService.deleteLiveLocation(rideId, userId).catch(console.warn)
      return
    }

    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setError("Geolocation is not supported by your browser.")
      return
    }

    setError(null)

    const handlePosition = (pos: GeolocationPosition) => {
      const lat = pos.coords.latitude
      const lng = pos.coords.longitude
      const accuracy = pos.coords.accuracy
      const speed = pos.coords.speed

      let heading = pos.coords.heading
      if ((heading === null || isNaN(heading)) && lastKnownCoordsRef.current) {
        const movedDist = getDistanceInMeters(
          lastKnownCoordsRef.current.lat,
          lastKnownCoordsRef.current.lng,
          lat,
          lng
        )
        if (movedDist >= 3) {
          heading = calculateBearing(
            lastKnownCoordsRef.current.lat,
            lastKnownCoordsRef.current.lng,
            lat,
            lng
          )
          lastKnownHeadingRef.current = heading
        } else {
          heading = lastKnownHeadingRef.current
        }
      } else if (typeof heading === "number") {
        lastKnownHeadingRef.current = heading
      }

      lastKnownCoordsRef.current = { lat, lng }

      const currentLoc: LiveUserLocation = {
        rideId,
        userId,
        userName,
        isCreator,
        role: role || (isCreator ? "creator" : "co_rider"),
        lat,
        lng,
        heading,
        speed,
        accuracy,
        isSharing: true
      }
      setMyLocation(currentLoc)

      // Throttled upload: >=3s interval AND >=10m displacement
      const now = Date.now()
      const timeElapsed = now - lastUploadTimeRef.current
      const distFromLastUpload = lastUploadedCoordsRef.current
        ? getDistanceInMeters(lastUploadedCoordsRef.current.lat, lastUploadedCoordsRef.current.lng, lat, lng)
        : Infinity

      if (timeElapsed >= MIN_UPLOAD_INTERVAL_MS && distFromLastUpload >= MIN_UPLOAD_DISTANCE_METERS) {
        lastUploadTimeRef.current = now
        lastUploadedCoordsRef.current = { lat, lng }

        liveLocationService.updateLiveLocation(rideId, currentLoc).catch((uploadErr) => {
          console.warn("[useLiveLocationTracking] Upload error:", uploadErr)
        })
      }
    }

    const handleError = (err: GeolocationPositionError) => {
      console.warn("[useLiveLocationTracking] GPS error:", err.message)
      if (err.code === err.PERMISSION_DENIED) {
        setError("Location permission denied. Please enable GPS in device settings.")
      } else if (err.code === err.POSITION_UNAVAILABLE) {
        setError("GPS signal unavailable.")
      } else if (err.code === err.TIMEOUT) {
        setError("Location request timed out. Retrying...")
      }
    }

    watchIdRef.current = navigator.geolocation.watchPosition(handlePosition, handleError, {
      enableHighAccuracy: true,
      timeout: 10000,
      maximumAge: 2000
    })

    return () => {
      if (watchIdRef.current !== null) {
        navigator.geolocation.clearWatch(watchIdRef.current)
        watchIdRef.current = null
      }
      if (userId && rideId) {
        liveLocationService.deleteLiveLocation(rideId, userId).catch(console.warn)
      }
    }
  }, [hasConsent, isSharing, enabled, rideId, userId, userName, isCreator, role, rideStatus])

  // 9. Simulation functions for dev testing
  const simulateLocationUpdate = useCallback((simLat: number, simLng: number, simHeading?: number) => {
    if (!rideId || !userId) return
    const currentLoc: LiveUserLocation = {
      rideId,
      userId,
      userName,
      isCreator,
      role: role || (isCreator ? "creator" : "co_rider"),
      lat: simLat,
      lng: simLng,
      heading: simHeading ?? lastKnownHeadingRef.current,
      speed: 4.5,
      accuracy: 5,
      isSharing: true
    }
    setMyLocation(currentLoc)
    liveLocationService.updateLiveLocation(rideId, currentLoc).catch(console.warn)
  }, [rideId, userId, userName, isCreator, role])

  const simulateCoRiderLocation = useCallback((coRiderId: string, name: string, lat: number, lng: number) => {
    if (!rideId) return
    const simLoc: LiveUserLocation = {
      rideId,
      userId: coRiderId,
      userName: name,
      isCreator: false,
      role: "co_rider",
      lat,
      lng,
      heading: 45,
      speed: 3.5,
      accuracy: 6,
      isSharing: true
    }
    liveLocationService.updateLiveLocation(rideId, simLoc).catch(console.warn)
  }, [rideId])

  // Legacy compat aliases
  const peerLocation = selectedCoRider?.location || null
  const distanceBetweenUsers = selectedCoRider?.distanceMeters ?? null
  const distanceFormatted = selectedCoRider?.distanceFormatted ?? null
  const isStale = selectedCoRider?.isStale ?? false
  const lastPeerUpdateAgoText = selectedCoRider?.staleAgoText ?? null

  return {
    myLocation,
    allLocations,
    coRiders,
    selectedCoRiderId,
    setSelectedCoRiderId,
    selectedCoRider,
    allParticipantsMet,
    bestGroupLocation,
    peerLocation,
    distanceBetweenUsers,
    distanceFormatted,
    isSharing,
    toggleSharing,
    error,
    isStale,
    lastPeerUpdateAgoText,
    hasConsent,
    grantConsent,
    simulateLocationUpdate,
    simulateCoRiderLocation
  }
}
