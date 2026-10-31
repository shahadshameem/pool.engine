import { useState, useEffect, useMemo, useRef, useCallback } from "react"
import { MapContainer, TileLayer, Marker, Polyline, useMap } from "react-leaflet"
import L from "leaflet"
import "leaflet/dist/leaflet.css"
import { MaterialIcon } from "../common/MaterialIcon"
import {
  getDistanceInMeters
} from "../../utils/locationService"
import { resolveFixedLocation } from "../../config/locations"
import { resolveCampusZone } from "../../config/campusZones"
import { routingService } from "../../services/routing/RoutingService"
import { computeSmartMeetingPoint } from "../../services/routing/smartMeetingPoint"
import type { SmartMeetingPoint } from "../../services/routing/types"
import type { LiveUserLocation } from "../../services/location/liveLocationService"
import type { CoRiderLiveStatus } from "../../hooks/useLiveLocationTracking"

export interface LocationPointLike {
  latitude?: number
  longitude?: number
  lat?: number
  lng?: number
  name?: string
  address?: string
}

export interface LiveLocationCardState {
  myLocation: LiveUserLocation | null
  coRiders?: CoRiderLiveStatus[]
  selectedCoRiderId?: string | null
  setSelectedCoRiderId?: (id: string | null) => void
  selectedCoRider?: CoRiderLiveStatus | null
  allParticipantsMet?: boolean
  bestGroupLocation?: { lat: number; lng: number; heading?: number | null } | null
  peerLocation?: LiveUserLocation | null // backward compatibility with 1-to-1 callers
  distanceBetweenUsers?: number | null // backward compatibility
  distanceFormatted?: string | null // backward compatibility
  isSharing: boolean
  toggleSharing: () => void
  error: string | null
  isStale: boolean
  lastPeerUpdateAgoText: string | null
}

export interface RideRouteVisualizerCardProps {
  ride: {
    id?: string
    from: string
    to: string
    fromLocation?: any
    toLocation?: any
    hostName?: string
    meetingPoint?: string
    vehicle?: string
    vehicleType?: string
    departureTime?: string
    date?: string
    status?: string
    pickupDistanceMeters?: number
    dropoffDistanceMeters?: number
    totalDistanceMeters?: number
    proximityBadge?: string
    acceptedPassengers?: any[]
  }
  userPickup?: LocationPointLike | null
  userDropoff?: LocationPointLike | null
  acceptedPassengers?: Array<{
    uid: string
    name: string
    pickupLocation?: any
    pickupDistanceMeters?: number
  }>
  pendingRequests?: Array<{
    id?: string
    requesterName?: string
    pickupLocation?: any
    pickupDistanceMeters?: number
    seatsRequested?: number
    status?: string
  }>
  isHost?: boolean
  className?: string
  liveLocationState?: LiveLocationCardState
}

// 1. Official Google Maps Pin 4-Color SVG Icon
export function GoogleMapsPinIcon({ className = "w-5 h-5" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 92 132" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M46 0C20.6 0 0 20.6 0 46c0 10.3 3.4 19.8 9.2 27.5L46 132l36.8-58.5C88.6 65.8 92 56.3 92 46 92 20.6 71.4 0 46 0z" fill="#EA4335"/>
      <path d="M0 46c0 10.3 3.4 19.8 9.2 27.5L34 52.8C33 50.7 32.4 48.4 32.4 46c0-7.5 6.1-13.6 13.6-13.6 2.4 0 4.7.6 6.8 1.6L64.5 10C59 3.7 50.9 0 46 0 20.6 0 0 20.6 0 46z" fill="#4285F4"/>
      <path d="M46 132l36.8-58.5C88.6 65.8 92 56.3 92 46c0-6.4-1.3-12.5-3.7-18L55.5 52.8c1 2.1 1.6 4.4 1.6 6.8 0 7.5-6.1 13.6-13.6 13.6-2.4 0-4.7-.6-6.8-1.6L9.2 73.5 46 132z" fill="#34A853"/>
      <path d="M88.3 28C84 16.9 75.3 8 64.5 10L52.8 34.4c2.1 1 3.9 2.5 5.2 4.4L88.3 28z" fill="#FBBC04"/>
      <circle cx="46" cy="46" r="16" fill="#000000"/>
    </svg>
  )
}

// 2. Custom Retina DivIcons matching Campus Pool Design
// Current User ("You") Marker: Glowing Blue Circle Pin with White Ring
const createYouMarkerIcon = () => L.divIcon({
  className: "custom-you-marker",
  html: `
    <div style="position: relative; display: flex; align-items: center; cursor: pointer;">
      <!-- Glowing Blue Circle Pin with White Ring -->
      <div style="position: relative; width: 28px; height: 28px; display: flex; align-items: center; justify-content: center;">
        <div style="position: absolute; inset: -4px; border-radius: 50%; background: rgba(59,130,246,0.45); filter: blur(5px);"></div>
        <div style="width: 24px; height: 24px; border-radius: 50%; background: #3B82F6; border: 3.5px solid #FFFFFF; box-shadow: 0 0 16px rgba(59,130,246,1); flex-shrink: 0;"></div>
      </div>

      <!-- Attached Callout Pill -->
      <div style="margin-left: 6px; background: #000000; border: 1.5px solid rgba(255,255,255,0.7); border-radius: 9999px; padding: 4px 12px; display: inline-flex; align-items: center; box-shadow: 0 4px 14px rgba(0,0,0,0.9); white-space: nowrap;">
        <span style="color: #FFFFFF; font-weight: 700; font-size: 13px; letter-spacing: -0.2px;">You</span>
      </div>
    </div>
  `,
  iconSize: [140, 36],
  iconAnchor: [14, 14]
})

// Trip Host Marker: Green Teardrop Pin with Car Icon
const createCreatorMarkerIcon = (creatorName: string) => L.divIcon({
  className: "custom-creator-proximity-marker",
  html: `
    <div style="position: relative; display: flex; align-items: center; cursor: pointer;">
      <!-- Green Teardrop Pin with Car -->
      <div style="position: relative; width: 32px; height: 38px; display: flex; align-items: center; justify-content: center; filter: drop-shadow(0 3px 6px rgba(0,0,0,0.6));">
        <svg width="32" height="38" viewBox="0 0 32 38" fill="none">
          <path d="M16 0C7.16 0 0 7.16 0 16C0 26 16 38 16 38C16 38 32 26 32 16C32 7.16 24.84 0 16 0Z" fill="#22C55E"/>
        </svg>
        <svg style="position: absolute; top: 8px; left: 8px;" width="16" height="16" viewBox="0 0 24 24" fill="#000000">
          <path d="M18.92 6.01C18.72 5.42 18.16 5 17.5 5h-11c-.66 0-1.21.42-1.42 1.01L3 12v8c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h12v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-8l-2.08-5.99zM6.5 16c-.83 0-1.5-.67-1.5-1.5S5.67 13 6.5 13s1.5.67 1.5 1.5S7.33 16 6.5 16zm11 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zM5 11l1.5-4.5h11L19 11H5z"/>
        </svg>
      </div>

      <!-- Attached Callout Pill -->
      <div style="margin-left: 6px; background: #000000; border: 1.5px solid rgba(255,255,255,0.7); border-radius: 9999px; padding: 4px 12px; display: inline-flex; align-items: center; box-shadow: 0 4px 14px rgba(0,0,0,0.9); white-space: nowrap;">
        <span style="color: #FFFFFF; font-weight: 700; font-size: 13px; letter-spacing: -0.2px;">${creatorName}</span>
      </div>
    </div>
  `,
  iconSize: [200, 38],
  iconAnchor: [16, 38]
})

// Single Group Position Marker (Phase B: In Cab / Ride in Motion)
const createGroupCarMarkerIcon = (heading?: number | null) => {
  const hasHeading = typeof heading === "number" && !isNaN(heading)
  const rotationStyle = hasHeading ? `transform: rotate(${heading}deg);` : ""
  return L.divIcon({
    className: "custom-group-car-marker",
    html: `
      <div style="position: relative; display: flex; align-items: center;">
        <!-- Neon Green Circular Pin with Car Icon -->
        <div style="width: 28px; height: 28px; border-radius: 50%; background: #22C55E; border: 2.5px solid #FFFFFF; box-shadow: 0 0 16px rgba(34,197,94,0.9); flex-shrink: 0; display: flex; align-items: center; justify-content: center; ${rotationStyle}">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="#000000">
            <path d="M18.92 6.01C18.72 5.42 18.16 5 17.5 5h-11c-.66 0-1.21.42-1.42 1.01L3 12v8c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h12v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-8l-2.08-5.99zM6.5 16c-.83 0-1.5-.67-1.5-1.5S5.67 13 6.5 13s1.5.67 1.5 1.5S7.33 16 6.5 16zm11 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zM5 11l1.5-4.5h11L19 11H5z"/>
          </svg>
        </div>
        <div style="margin-left: 6px; background: #000000; border: 1.5px solid rgba(255,255,255,0.7); border-radius: 9999px; padding: 4px 12px; display: inline-flex; align-items: center; box-shadow: 0 4px 14px rgba(0,0,0,0.9); white-space: nowrap;">
          <span style="color: #FFFFFF; font-weight: 700; font-size: 13px; letter-spacing: -0.2px;">Pool in Cab</span>
        </div>
      </div>
    `,
    iconSize: [180, 36],
    iconAnchor: [14, 18]
  })
}

// Co-Rider Marker: Emerald Circle Pin with Beside Pill
const createCoRiderMarkerIcon = (userName: string, distanceText?: string, isSelected?: boolean) => L.divIcon({
  className: "custom-corider-proximity-marker",
  html: `
    <div style="position: relative; display: flex; align-items: center; transition: transform 0.3s ease-out; cursor: pointer;">
      <!-- Green / Emerald Circle Pin with Glow -->
      <div style="width: 20px; height: 20px; border-radius: 50%; background: #10B981; border: 3px solid #6EE7B7; box-shadow: 0 0 16px rgba(16,185,129,0.9), 0 0 0 4px rgba(16,185,129,0.3); flex-shrink: 0;"></div>

      <!-- Beside: Pill with Name and optional Distance -->
      <div style="margin-left: 7px; background: #000000; border: 1.5px solid ${isSelected ? '#C5FF00' : 'rgba(255,255,255,0.4)'}; border-radius: 9999px; padding: 3px 10px; display: inline-flex; align-items: center; gap: 5px; box-shadow: 0 3px 10px rgba(0,0,0,0.8); white-space: nowrap; max-width: 190px;">
        <span style="color: #FFFFFF; font-weight: 700; font-size: 12px; letter-spacing: -0.2px; overflow: hidden; text-overflow: ellipsis;">${userName}</span>
        ${distanceText ? `
          <span style="color: #71717A; font-weight: 700; font-size: 12px;">·</span>
          <span style="color: #C5FF00; font-weight: 800; font-size: 12px; letter-spacing: -0.2px; flex-shrink: 0;">${distanceText}</span>
        ` : ''}
      </div>
    </div>
  `,
  iconSize: [200, 36],
  iconAnchor: [10, 18]
})

// Campus Pickup Landmark Marker: Amber Teardrop Pin with Graduation Cap
const createPickupMarkerIcon = (meetingPoint: string) => L.divIcon({
  className: "custom-pickup-marker",
  html: `
    <div style="position: relative; display: flex; align-items: center; cursor: pointer;">
      <!-- Amber Teardrop Pin with Graduation Cap -->
      <div style="position: relative; width: 32px; height: 38px; display: flex; align-items: center; justify-content: center; filter: drop-shadow(0 3px 6px rgba(0,0,0,0.6));">
        <svg width="32" height="38" viewBox="0 0 32 38" fill="none">
          <path d="M16 0C7.16 0 0 7.16 0 16C0 26 16 38 16 38C16 38 32 26 32 16C32 7.16 24.84 0 16 0Z" fill="#F59E0B"/>
        </svg>
        <svg style="position: absolute; top: 7px; left: 7px;" width="18" height="18" viewBox="0 0 24 24" fill="#000000">
          <path d="M12 3L1 9l11 6 9-4.91V17h2V9L12 3zM5 13.18v4L12 21l7-3.82v-4L12 17l-7-3.82z"/>
        </svg>
      </div>

      <!-- Attached Callout Pill -->
      <div style="margin-left: 6px; background: #000000; border: 1.5px solid rgba(255,255,255,0.7); border-radius: 9999px; padding: 4px 12px; display: inline-flex; align-items: center; box-shadow: 0 4px 14px rgba(0,0,0,0.9); white-space: nowrap;">
        <span style="color: #FFFFFF; font-weight: 700; font-size: 13px; letter-spacing: -0.2px;">${meetingPoint || "Campus Pickup (CET)"}</span>
      </div>
    </div>
  `,
  iconSize: [220, 38],
  iconAnchor: [16, 38]
})

// Destination Pin: Emerald Marker with flag icon and destination label
const createDestinationMarkerIcon = (destName: string, offsetAbove = false) => {
  if (offsetAbove) {
    return L.divIcon({
      className: "custom-destination-marker-offset",
      html: `
        <div style="position: relative; display: flex; flex-direction: column; align-items: center; transform: translate(-50%, -100%); pointer-events: none;">
          <div style="background: #000000; border: 1.5px solid #10B981; border-radius: 9999px; padding: 2.5px 8px; margin-bottom: 3px; display: inline-flex; align-items: center; gap: 4px; box-shadow: 0 4px 12px rgba(0,0,0,0.9); white-space: nowrap; max-width: 170px;">
            <span style="font-size: 10px;">🏁</span>
            <span style="color: #FFFFFF; font-weight: 700; font-size: 11px; letter-spacing: -0.2px; overflow: hidden; text-overflow: ellipsis;">${destName}</span>
          </div>
          <div style="width: 18px; height: 18px; border-radius: 50%; background: #10B981; border: 3px solid #6EE7B7; box-shadow: 0 0 14px rgba(16,185,129,0.85); flex-shrink: 0; display: flex; align-items: center; justify-content: center;">
            <div style="width: 4px; height: 4px; border-radius: 50%; background: #FFFFFF;"></div>
          </div>
        </div>
      `,
      iconSize: [180, 50],
      iconAnchor: [90, 50]
    })
  }

  return L.divIcon({
    className: "custom-destination-marker",
    html: `
      <div style="position: relative; display: flex; align-items: center;">
        <div style="width: 20px; height: 20px; border-radius: 50%; background: #10B981; border: 3px solid #6EE7B7; box-shadow: 0 0 14px rgba(16,185,129,0.8); flex-shrink: 0; display: flex; align-items: center; justify-content: center;">
          <div style="width: 5px; height: 5px; border-radius: 50%; background: #FFFFFF;"></div>
        </div>
        <div style="margin-left: 6px; background: #000000; border: 1.5px solid #10B981; border-radius: 9999px; padding: 3px 9px; display: inline-flex; align-items: center; gap: 4px; box-shadow: 0 3px 10px rgba(0,0,0,0.85); white-space: nowrap; max-width: 170px;">
          <span style="font-size: 11px;">🏁</span>
          <span style="color: #FFFFFF; font-weight: 700; font-size: 11px; letter-spacing: -0.2px; overflow: hidden; text-overflow: ellipsis;">${destName}</span>
        </div>
      </div>
    `,
    iconSize: [180, 36],
    iconAnchor: [10, 18]
  })
}

// Walking Duration Badge (e.g. `🚶 4 min`) on the meet path
const createWalkingTimeBadgeIcon = (minutesText: string) => L.divIcon({
  className: "custom-walk-time-badge",
  html: `
    <div style="background: #000000; border: 1.5px solid #C5FF00; border-radius: 9999px; padding: 4px 11px; display: inline-flex; align-items: center; gap: 5px; box-shadow: 0 4px 14px rgba(0,0,0,0.85); white-space: nowrap; transform: translate(-50%, -50%);">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="5" r="2.5"></circle>
        <path d="m9 20 3-6 2 3 3-1"></path>
        <path d="m6 11 6-2 4 4"></path>
      </svg>
      <span style="color: #FFFFFF; font-weight: 700; font-size: 12px; letter-spacing: -0.2px;">${minutesText}</span>
    </div>
  `,
  iconSize: [84, 30],
  iconAnchor: [42, 15]
})

// Smart Meeting Point Marker (Balanced walking midpoint)
const createSmartMeetingMarkerIcon = (description: string) => L.divIcon({
  className: "custom-smart-meet-marker",
  html: `
    <div style="position: relative; display: flex; flex-direction: column; align-items: center; transform: translate(-50%, -100%); cursor: pointer; pointer-events: auto;">
      <div style="background: #000000; border: 1.5px solid #C5FF00; border-radius: 9999px; padding: 3px 10px; margin-bottom: 3px; display: inline-flex; align-items: center; gap: 4px; box-shadow: 0 4px 14px rgba(0,0,0,0.9); white-space: nowrap;">
        <span style="font-size: 11px;">🤝</span>
        <span style="color: #C5FF00; font-weight: 800; font-size: 11px; letter-spacing: -0.2px;">${description}</span>
      </div>
      <div style="width: 14px; height: 14px; border-radius: 50%; background: #C5FF00; border: 2.5px solid #000000; box-shadow: 0 0 10px rgba(197,255,0,0.8); flex-shrink: 0;"></div>
    </div>
  `,
  iconSize: [220, 42],
  iconAnchor: [110, 42]
})

// 3. Leaflet Controller to Auto-Fit Bounds & Handle Resize with Balanced Padding
function MapBoundsController({
  allCoordinates,
  recenterTrigger,
  isManualPan,
  onUserPan,
  isStarted,
  targetCoord
}: {
  allCoordinates: [number, number][]
  recenterTrigger: number
  isManualPan: boolean
  onUserPan: () => void
  isStarted: boolean
  targetCoord: [number, number]
}) {
  const map = useMap()
  const initialFitDone = useRef(false)
  const prevRecenterRef = useRef(recenterTrigger)
  const prevStartedRef = useRef(isStarted)
  const lastPanCoordRef = useRef<[number, number] | null>(null)

  // 1. Detect manual user pan or zoom interaction
  useEffect(() => {
    const handleUserInteraction = () => {
      onUserPan()
    }
    map.on("dragstart", handleUserInteraction)
    map.on("zoomstart", handleUserInteraction)
    return () => {
      map.off("dragstart", handleUserInteraction)
      map.off("zoomstart", handleUserInteraction)
    }
  }, [map, onUserPan])

  // 2. Handle initial fit or ride phase transition (booked -> started)
  useEffect(() => {
    const phaseChanged = isStarted !== prevStartedRef.current
    prevStartedRef.current = isStarted

    if (!initialFitDone.current || phaseChanged) {
      map.invalidateSize()
      if (allCoordinates.length > 1) {
        const bounds = L.latLngBounds(allCoordinates)
        map.fitBounds(bounds, {
          paddingTopLeft: [65, 30],
          paddingBottomRight: [65, 30],
          maxZoom: 16
        })
      } else if (allCoordinates.length === 1) {
        map.setView(allCoordinates[0], 16)
      }
      initialFitDone.current = true
    }
  }, [map, allCoordinates, isStarted])

  // 3. Handle explicit user tap on Recenter button
  useEffect(() => {
    if (recenterTrigger === prevRecenterRef.current) return
    prevRecenterRef.current = recenterTrigger

    map.invalidateSize()
    if (isStarted) {
      // In cab moving: smooth fly directly to current cab position at driving zoom
      map.flyTo(targetCoord, 16, { animate: true, duration: 0.6 })
    } else {
      // Phase A: fit to meetup participants
      if (allCoordinates.length > 1) {
        const bounds = L.latLngBounds(allCoordinates)
        map.flyToBounds(bounds, {
          paddingTopLeft: [65, 30],
          paddingBottomRight: [65, 30],
          maxZoom: 16,
          duration: 0.6
        })
      } else {
        map.flyTo(targetCoord, 16, { animate: true, duration: 0.6 })
      }
    }
  }, [map, recenterTrigger, isStarted, targetCoord, allCoordinates])

  // 4. Smooth auto-follow during live movement (when user has not manually panned)
  useEffect(() => {
    if (!initialFitDone.current || isManualPan) return

    const [lat, lng] = targetCoord
    const last = lastPanCoordRef.current

    // Don't pan if movement is less than 3 meters (prevents micro-jitter)
    if (last) {
      const movedMeters = getDistanceInMeters(last[0], last[1], lat, lng)
      if (movedMeters < 3) return
    }

    lastPanCoordRef.current = [lat, lng]

    if (isStarted) {
      // Smoothly pan camera to follow moving cab without resetting user's zoom
      map.panTo([lat, lng], { animate: true, duration: 0.8 })
    } else {
      // Phase A: If "You" moves near or outside the current view bounds, smoothly pan
      const currentBounds = map.getBounds()
      if (!currentBounds.pad(-0.1).contains([lat, lng])) {
        map.panTo([lat, lng], { animate: true, duration: 0.8 })
      }
    }
  }, [map, targetCoord, isManualPan, isStarted])

  return null
}

export function RideRouteVisualizerCard({
  ride,
  userPickup,
  acceptedPassengers: _acceptedPassengers,
  pendingRequests: _pendingRequests,
  isHost = false,
  className = "",
  liveLocationState
}: RideRouteVisualizerCardProps) {
  const [recenterTrigger, setRecenterTrigger] = useState(0)
  const [isManualPan, setIsManualPan] = useState(false)

  // 1. Destination coordinates
  const destLocation = useMemo(() => {
    return resolveFixedLocation(ride.to, ride.toLocation, false)
  }, [ride.to, ride.toLocation])

  const destCoord: [number, number] = useMemo(() => {
    return [destLocation.latitude, destLocation.longitude]
  }, [destLocation])

  // 2. Base Fallback Origin Coordinates (Campus Pickup Point)
  const pBaseLat = Number(ride.fromLocation?.latitude ?? (ride as any).source?.lat ?? 8.5459)
  const pBaseLng = Number(ride.fromLocation?.longitude ?? (ride as any).source?.lng ?? 76.9063)
  const pickupCoord: [number, number] = useMemo(() => [pBaseLat, pBaseLng], [pBaseLat, pBaseLng])

  const isCetPickupZone = useMemo(() => {
    if ((ride as any).matchedZoneId === "cet-front-gate") return true
    if (pickupCoord && resolveCampusZone(pickupCoord[0], pickupCoord[1])?.zone.id === "cet-front-gate") return true
    const lowerFrom = (ride.from || "").toLowerCase()
    const lowerMeet = (ride.meetingPoint || "").toLowerCase()
    return lowerFrom.includes("cet") || lowerFrom.includes("college of engineering") || lowerMeet.includes("cet")
  }, [(ride as any).matchedZoneId, pickupCoord, ride.from, ride.meetingPoint])

  const pickupMarkerLabel = useMemo(() => {
    if (isCetPickupZone) {
      return "CET Front Gate"
    }
    return ride.meetingPoint || "Campus Pickup"
  }, [isCetPickupZone, ride.meetingPoint])

  // 3. Resolve "You" Live / Fallback Position
  const myLive = liveLocationState?.myLocation
  const myLat = myLive?.lat ?? Number(userPickup?.latitude ?? userPickup?.lat ?? (isHost ? pBaseLat : pBaseLat + 0.0022))
  const myLng = myLive?.lng ?? Number(userPickup?.longitude ?? userPickup?.lng ?? (isHost ? pBaseLng : pBaseLng + 0.0018))
  const myCoord: [number, number] = useMemo(() => [myLat, myLng], [myLat, myLng])

  // 4. Co-Riders array & Selection
  const coRiders = liveLocationState?.coRiders || []
  const selectedCoRider = liveLocationState?.selectedCoRider || (coRiders.length > 0 ? coRiders[0] : null)
  const isStarted = ride.status === "started"
  const isEnded = ride.status === "completed" || ride.status === "cancelled" || !liveLocationState

  // 5. Target for Meet Path in Phase A: Selected Co-Rider or Pickup Point
  const hasSelectedCoRiderLoc = Boolean(selectedCoRider?.location?.lat && selectedCoRider?.location?.lng)
  const meetTargetCoord: [number, number] = useMemo(() => {
    if (hasSelectedCoRiderLoc && selectedCoRider?.location) {
      return [selectedCoRider.location.lat, selectedCoRider.location.lng]
    }
    return pickupCoord
  }, [hasSelectedCoRiderLoc, selectedCoRider, pickupCoord])

  // Distance to target
  const distanceToMeetTarget = useMemo(() => {
    if (hasSelectedCoRiderLoc && selectedCoRider?.distanceMeters !== null && selectedCoRider?.distanceMeters !== undefined) {
      return selectedCoRider.distanceMeters
    }
    return getDistanceInMeters(myLat, myLng, meetTargetCoord[0], meetTargetCoord[1])
  }, [hasSelectedCoRiderLoc, selectedCoRider?.distanceMeters, myLat, myLng, meetTargetCoord])

  const walkMinutes = useMemo(() => {
    return Math.max(1, Math.round(distanceToMeetTarget / 80))
  }, [distanceToMeetTarget])
  const walkMinutesText = `${walkMinutes} min`

  const midpoint: [number, number] = useMemo(() => {
    return [(myLat + meetTargetCoord[0]) / 2, (myLng + meetTargetCoord[1]) / 2]
  }, [myLat, myLng, meetTargetCoord])

  // 6. Best Group Location in Phase B (Car in motion)
  const bestGroupLoc = liveLocationState?.bestGroupLocation
  const groupCoord: [number, number] = useMemo(() => {
    if (bestGroupLoc) return [bestGroupLoc.lat, bestGroupLoc.lng]
    return myCoord
  }, [bestGroupLoc, myCoord])

  // 7. Route Polylines:
  // - Meet Path: Solid Neon Lime connecting "You" & Selected Co-Rider / Pickup (Phase A)
  // - Trip Route: Pickup-to-Destination (dashed during active, solid during started or ended)
  const [meetPathPolyline, setMeetPathPolyline] = useState<[number, number][]>([])
  const [, setIsMeetPathFallback] = useState(false)
  const [smartMeetingPoint, setSmartMeetingPoint] = useState<SmartMeetingPoint | null>(null)
  const [tripRoutePolyline, setTripRoutePolyline] = useState<[number, number][]>([])
  const [destDistanceKm, setDestDistanceKm] = useState<number | null>(null)
  const [destDurationMins, setDestDurationMins] = useState<number | null>(null)
  const [_isUpdatingRoute, setIsUpdatingRoute] = useState(false)

  // Master untrimmed route geometries for real-time local trimming
  const fullMeetPathRef = useRef<[number, number][]>([])
  const fullTripPathRef = useRef<[number, number][]>([])

  const walkingBadgePos: [number, number] = useMemo(() => {
    if (meetPathPolyline.length > 2) {
      const midIndex = Math.floor(meetPathPolyline.length / 2)
      return meetPathPolyline[midIndex]
    }
    return midpoint
  }, [meetPathPolyline, midpoint])

  // Re-request meet path route only when either moves > 25m or goes off-route (> 30m), with debouncing
  const lastMeetCoordsRef = useRef<{ mLat: number; mLng: number; tLat: number; tLng: number } | null>(null)
  useEffect(() => {
    if (isStarted || isEnded || allMet || distanceToMeetTarget < 35) {
      setMeetPathPolyline([])
      fullMeetPathRef.current = []
      setSmartMeetingPoint(null)
      return
    }

    // If selected co-rider has no live location yet and distance to pickup > 1500m (student is far from campus),
    // don't draw an unrealistic cross-city foot route.
    if (!hasSelectedCoRiderLoc && distanceToMeetTarget > 1500) {
      setMeetPathPolyline([])
      fullMeetPathRef.current = []
      setSmartMeetingPoint(null)
      return
    }

    const tLat = meetTargetCoord[0]
    const tLng = meetTargetCoord[1]
    const last = lastMeetCoordsRef.current

    // Check if user is off current planned route
    const isOff = fullMeetPathRef.current.length > 1
      ? routingService.isOffRoute(fullMeetPathRef.current, { lat: myLat, lng: myLng }, 30)
      : true

    if (last && !isOff) {
      const mMoved = getDistanceInMeters(last.mLat, last.mLng, myLat, myLng)
      const tMoved = getDistanceInMeters(last.tLat, last.tLng, tLat, tLng)
      if (mMoved < 25 && tMoved < 25) {
        // Local zero-network polyline trimming: slice points behind user
        if (fullMeetPathRef.current.length > 1) {
          const trimmed = routingService.trimRoute(fullMeetPathRef.current, { lat: myLat, lng: myLng })
          if (!trimmed.isOffRoute && trimmed.geometry.length > 1) {
            setMeetPathPolyline(trimmed.geometry)
          }
        }
        return
      }
    }

    const timer = setTimeout(async () => {
      lastMeetCoordsRef.current = { mLat: myLat, mLng: myLng, tLat, tLng }
      setIsUpdatingRoute(true)

      try {
        const route = await routingService.getRoute(
          { lat: myLat, lng: myLng },
          { lat: tLat, lng: tLng },
          "walking",
          { enableSnapping: true }
        )

        fullMeetPathRef.current = route.geometry
        setMeetPathPolyline(route.geometry)
        setIsMeetPathFallback(route.isFallback)

        // Compute smart balanced meeting point if coordinating with a co-rider
        if (hasSelectedCoRiderLoc && selectedCoRider) {
          const smp = await computeSmartMeetingPoint({
            posA: { lat: myLat, lng: myLng },
            posB: { lat: tLat, lng: tLng },
            nameA: "You",
            nameB: selectedCoRider.userName,
            pickupPoint: { lat: pickupCoord[0], lng: pickupCoord[1] },
            existingPolyline: route.geometry
          })
          setSmartMeetingPoint(smp)
        } else {
          setSmartMeetingPoint(null)
        }
      } catch (err: any) {
        if (err.name !== "AbortError") {
          console.warn("[RideRouteVisualizerCard] Meet path route failed:", err)
        }
      } finally {
        setIsUpdatingRoute(false)
      }
    }, 800)

    return () => clearTimeout(timer)
  }, [isStarted, isEnded, hasSelectedCoRiderLoc, myLat, myLng, meetTargetCoord, distanceToMeetTarget, selectedCoRider, pickupCoord])

  // Fetch Trip Route to Destination via routingService (Driving Profile)
  const lastTripFetchCoordRef = useRef<{ lat: number; lng: number } | null>(null)
  useEffect(() => {
    const originLat = isStarted ? groupCoord[0] : pBaseLat
    const originLng = isStarted ? groupCoord[1] : pBaseLng

    if (isStarted && lastTripFetchCoordRef.current) {
      const isOff = fullTripPathRef.current.length > 1
        ? routingService.isOffRoute(fullTripPathRef.current, { lat: originLat, lng: originLng }, 30)
        : true

      const moved = getDistanceInMeters(
        lastTripFetchCoordRef.current.lat,
        lastTripFetchCoordRef.current.lng,
        originLat,
        originLng
      )

      if (moved < 25 && !isOff) {
        // Local zero-network polyline trimming: slice points behind moving cab & update ETA
        if (fullTripPathRef.current.length > 1) {
          const trimmed = routingService.trimRoute(fullTripPathRef.current, { lat: originLat, lng: originLng })
          if (!trimmed.isOffRoute && trimmed.geometry.length > 1) {
            setTripRoutePolyline(trimmed.geometry)
            setDestDistanceKm(Math.round((trimmed.remainingDistanceMeters / 1000) * 10) / 10)
            setDestDurationMins(Math.max(1, Math.round(trimmed.remainingDurationSeconds / 60)))
          }
        }
        return
      }
    }

    const timer = setTimeout(async () => {
      lastTripFetchCoordRef.current = { lat: originLat, lng: originLng }
      setIsUpdatingRoute(true)

      try {
        const route = await routingService.getRoute(
          { lat: originLat, lng: originLng },
          { lat: destLocation.latitude, lng: destLocation.longitude },
          "driving",
          { enableSnapping: true }
        )

        fullTripPathRef.current = route.geometry
        setTripRoutePolyline(route.geometry)
        setDestDistanceKm(Math.round((route.distanceMeters / 1000) * 10) / 10)
        setDestDurationMins(Math.max(1, Math.round(route.durationSeconds / 60)))
      } catch (err: any) {
        if (err.name !== "AbortError") {
          console.warn("[RideRouteVisualizerCard] Trip route fetch failed:", err)
        }
      } finally {
        setIsUpdatingRoute(false)
      }
    }, isStarted ? 800 : 1000)

    return () => clearTimeout(timer)
  }, [isStarted, groupCoord, pBaseLat, pBaseLng, destLocation.latitude, destLocation.longitude])

  // Collect map bounding coordinates
  const allCoordinates: [number, number][] = useMemo(() => {
    if (isEnded) {
      return [pickupCoord, destCoord]
    }
    if (isStarted) {
      return [groupCoord, destCoord]
    }
    const list: [number, number][] = [myCoord, pickupCoord]
    coRiders.forEach(cr => {
      if (cr.location) {
        list.push([cr.location.lat, cr.location.lng])
      }
    })
    return list
  }, [isEnded, isStarted, groupCoord, destCoord, myCoord, pickupCoord, coRiders])

  // Google Maps external link
  const googleMapsUrl = useMemo(() => {
    if (isEnded) {
      return `https://www.google.com/maps/dir/?api=1&origin=${pickupCoord[0]},${pickupCoord[1]}&destination=${destLocation.latitude},${destLocation.longitude}&travelmode=driving`
    }
    if (isStarted) {
      return `https://www.google.com/maps/dir/?api=1&origin=${groupCoord[0]},${groupCoord[1]}&destination=${destLocation.latitude},${destLocation.longitude}&travelmode=driving`
    }
    return `https://www.google.com/maps/dir/?api=1&origin=${myLat},${myLng}&destination=${meetTargetCoord[0]},${meetTargetCoord[1]}&travelmode=walking`
  }, [isEnded, isStarted, pickupCoord, groupCoord, destLocation.latitude, destLocation.longitude, myLat, myLng, meetTargetCoord])

  const handleRecenter = useCallback(() => {
    setIsManualPan(false)
    setRecenterTrigger(prev => prev + 1)
  }, [])

  const allMet = Boolean(liveLocationState?.allParticipantsMet)

  return (
    <div
      className={`relative w-full h-[290px] sm:h-[330px] rounded-[24px] overflow-hidden border border-zinc-800/80 shadow-md bg-[#0D0D0D] ${className}`}
      style={{ height: 290, minHeight: 290 }}
    >
      <MapContainer
        center={isEnded ? pickupCoord : (isStarted ? groupCoord : myCoord)}
        zoom={15}
        zoomControl={false}
        scrollWheelZoom={false}
        keyboard={false}
        className="w-full h-full dark-leaflet-map"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />

        <MapBoundsController
          allCoordinates={allCoordinates}
          recenterTrigger={recenterTrigger}
          isManualPan={isManualPan}
          onUserPan={() => setIsManualPan(true)}
          isStarted={isStarted}
          targetCoord={isEnded ? pickupCoord : (isStarted ? groupCoord : myCoord)}
        />

        {/* 1. Trip Route to Destination (Vibrant Electric Blue with soft glow casing) */}
        {tripRoutePolyline.length > 0 && (
          <>
            <Polyline
              positions={tripRoutePolyline}
              pathOptions={{
                color: "#0284C7",
                weight: 8,
                opacity: 0.4,
                lineCap: "round",
                lineJoin: "round"
              }}
            />
            <Polyline
              positions={tripRoutePolyline}
              pathOptions={{
                color: isEnded ? "#10B981" : "#38BDF8",
                weight: 5,
                opacity: 1,
                lineCap: "round",
                lineJoin: "round"
              }}
            />
          </>
        )}

        {/* 2. Meet Path (Vibrant Electric Blue with soft glow casing) */}
        {!isStarted && !isEnded && meetPathPolyline.length > 0 && (
          <>
            <Polyline
              positions={meetPathPolyline}
              pathOptions={{
                color: "#0284C7",
                weight: 8,
                opacity: 0.4,
                lineCap: "round",
                lineJoin: "round"
              }}
            />
            <Polyline
              positions={meetPathPolyline}
              pathOptions={{
                color: "#38BDF8",
                weight: 5,
                opacity: 1,
                lineCap: "round",
                lineJoin: "round"
              }}
            />
          </>
        )}

        {/* Smart Meeting Point Marker (Balanced walking midpoint) */}
        {!isStarted && !isEnded && smartMeetingPoint && !allMet && (
          <Marker
            position={[smartMeetingPoint.point.lat, smartMeetingPoint.point.lng]}
            icon={createSmartMeetingMarkerIcon(smartMeetingPoint.description)}
          />
        )}

        {/* 3. Walking Time Badge on Meet Path (Phase A) */}
        {!isStarted && !isEnded && !allMet && meetPathPolyline.length > 0 && distanceToMeetTarget > 35 && (hasSelectedCoRiderLoc || distanceToMeetTarget <= 1500) && (
          <Marker
            position={walkingBadgePos}
            icon={createWalkingTimeBadgeIcon(walkMinutesText)}
            interactive={false}
          />
        )}

        {/* Campus Pickup Landmark Marker */}
        {!isStarted && (
          <Marker
            position={pickupCoord}
            icon={createPickupMarkerIcon(pickupMarkerLabel)}
          />
        )}

        {/* 4. PHASE A: Individual Live Markers */}
        {!isStarted && !isEnded && (
          <>
            {/* "You" Marker */}
            <Marker
              position={myCoord}
              icon={createYouMarkerIcon()}
            />

            {/* Other Confirmed Co-Riders Markers */}
            {coRiders.map((cr) => {
              if (!cr.location) return null
              const isSelected = selectedCoRider?.userId === cr.userId
              const pos: [number, number] = [cr.location.lat, cr.location.lng]

              if (cr.isCreator) {
                return (
                  <Marker
                    key={cr.userId}
                    position={pos}
                    icon={createCreatorMarkerIcon(cr.userName)}
                    eventHandlers={{
                      click: () => liveLocationState?.setSelectedCoRiderId?.(cr.userId)
                    }}
                  />
                )
              }

              return (
                <Marker
                  key={cr.userId}
                  position={pos}
                  icon={createCoRiderMarkerIcon(
                    cr.userName,
                    cr.distanceFormatted || undefined,
                    isSelected
                  )}
                  eventHandlers={{
                    click: () => liveLocationState?.setSelectedCoRiderId?.(cr.userId)
                  }}
                />
              )
            })}
          </>
        )}

        {/* 5. PHASE B: Single Group Position Marker */}
        {isStarted && (
          <Marker
            position={groupCoord}
            icon={createGroupCarMarkerIcon(bestGroupLoc?.heading)}
          />
        )}

        {/* 6. Destination Marker */}
        <Marker
          position={destCoord}
          icon={createDestinationMarkerIcon(
            destLocation.name || ride.to,
            getDistanceInMeters(isEnded ? pickupCoord[0] : myLat, isEnded ? pickupCoord[1] : myLng, destCoord[0], destCoord[1]) < 60
          )}
        />
      </MapContainer>

      {/* Top Controls Bar (Shown only once trip is in motion or completed) */}
      {(isStarted || isEnded) && (
        <div className="absolute top-2.5 inset-x-2.5 z-[1000] flex items-center justify-between gap-1.5 pointer-events-none">
          <div className="bg-black/90 backdrop-blur-md border border-zinc-700/80 rounded-full px-3 py-1 shadow-xl flex items-center gap-1.5 min-w-0 max-w-[calc(100%-85px)] pointer-events-auto">
            {isEnded ? (
              <>
                <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" />
                <span className="text-[11px] font-bold text-white truncate">
                  {ride.status === "cancelled" ? "Ride cancelled" : "Ride completed · Route summary"}
                </span>
              </>
            ) : (
              <>
                <span className="w-2 h-2 rounded-full bg-[#3B82F6] animate-ping shrink-0" />
                <span className="text-[11px] font-bold text-white truncate">
                  {destDistanceKm !== null ? `${destDistanceKm} km left · ${destDurationMins} min` : `En route to ${destLocation.name || ride.to}`}
                </span>
              </>
            )}
          </div>

          {/* Live Location Sharing Toggle Pill */}
          {!isEnded && liveLocationState && (
            <button
              type="button"
              onClick={liveLocationState.toggleSharing}
              className={`h-7 px-2.5 rounded-full border shadow-md flex items-center gap-1 text-[11px] font-bold transition-all active:scale-95 cursor-pointer shrink-0 pointer-events-auto ${
                liveLocationState.isSharing
                  ? "bg-black/90 hover:bg-black text-white border-zinc-700/80"
                  : "bg-amber-950/90 hover:bg-amber-900 text-amber-200 border-amber-700/80"
              }`}
              title={liveLocationState.isSharing ? "Stop sharing live location" : "Resume sharing live location"}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                  liveLocationState.isSharing ? "bg-emerald-400 animate-pulse" : "bg-amber-400"
                }`}
              />
              <span>{liveLocationState.isSharing ? "Live" : "Paused"}</span>
            </button>
          )}
        </div>
      )}


      {/* Map Controls: Stacked Vertically in Bottom Right (Clean White Circular FABs) */}
      {/* 1. Recenter Button */}
      <button
        type="button"
        onClick={handleRecenter}
        className="absolute bottom-[60px] right-3.5 z-[1000] h-11 w-11 rounded-full bg-white text-zinc-900 border border-zinc-200/90 shadow-xl flex items-center justify-center cursor-pointer transition-all active:scale-95 hover:bg-zinc-100"
        title="Re-center map"
        aria-label="Re-center map"
      >
        <MaterialIcon
          name="my_location"
          className="text-[22px] text-zinc-900"
        />
      </button>

      {/* 2. Official Google Maps Button */}
      <a
        href={googleMapsUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="absolute bottom-3.5 right-3.5 z-[1000] h-11 w-11 rounded-full bg-white border border-zinc-200/90 shadow-xl flex items-center justify-center cursor-pointer transition-all active:scale-95 hover:bg-zinc-100"
        title="Open in Google Maps"
        aria-label="Open in Google Maps"
      >
        <GoogleMapsPinIcon className="w-6 h-6" />
      </a>
    </div>
  )
}
