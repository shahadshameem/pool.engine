/**
 * Firebase Firestore Schema & Uber H3 Ride Matching Service
 * Centered on Trivandrum (Thiruvananthapuram), Kerala
 * Uses Uber H3 Hexagonal Spatial Indexing (v4) & Firebase Firestore
 */

import {
  collection,
  addDoc,
  getDoc,
  getDocs,
  doc,
  updateDoc,
  query,
  where,
  limit,
  serverTimestamp,
  Timestamp
} from "firebase/firestore"
import { db } from "../config/firebase"
import {
  isRideExpired,
  calculateTimeDifferenceMinutes,
  MAX_TIME_DIFF_MINUTES
} from "../config/matchingConfig"
import {
  getH3Cell,
  getH3SearchDisk,
  getDistanceInMeters,
  formatDistance,
  fetchDrivingRoute
} from "../utils/locationService"

/**
 * Creates a new ride in Firestore with Uber H3 Resolution 8 spatial indices
 *
 * Schema: rides/{rideId}
 * {
 *   driverId: string,
 *   driverName: string,
 *   vehicleType: "bike" | "car" | "auto",
 *   availableSeats: number,
 *   farePerSeat: number,
 *   status: "OPEN" | "FULL" | "COMPLETED" | "CANCELLED",
 *   departureTime: Timestamp,
 *   source: {
 *     name: string,
 *     lat: number,
 *     lng: number,
 *     h3IndexRes8: string, // Generated via latLngToCell(lat, lng, 8)
 *     pickupRadiusMeters: number
 *   },
 *   destination: {
 *     name: string,
 *     lat: number,
 *     lng: number,
 *     h3IndexRes8: string, // Generated via latLngToCell(lat, lng, 8)
 *     dropoffRadiusMeters: number
 *   },
 *   routeSummary: {
 *     distanceKm: number,
 *     durationMins: number
 *   },
 *   createdAt: serverTimestamp()
 * }
 */
export async function createRideWithH3(rideData) {
  const {
    driverId,
    driverName = "",
    vehicleType = "bike",
    availableSeats = 1,
    farePerSeat = 0,
    departureTime,
    source,
    destination,
    pickupRadiusMeters = 1000,
    dropoffRadiusMeters = 1000,
    routeSummary
  } = rideData

  if (!source?.lat || !source?.lng) {
    throw new Error("Source location coordinates (lat, lng) are required")
  }
  if (!destination?.lat || !destination?.lng) {
    throw new Error("Destination location coordinates (lat, lng) are required")
  }

  // 1. Generate Uber H3 Resolution 8 indices
  const sourceH3 = getH3Cell(source.lat, source.lng, 8)
  const destH3 = getH3Cell(destination.lat, destination.lng, 8)

  // 2. Fetch OSRM route summary if not already provided
  let finalRouteSummary = routeSummary
  if (!finalRouteSummary || !finalRouteSummary.distanceKm) {
    try {
      finalRouteSummary = await fetchDrivingRoute(source, destination)
    } catch {
      const dist = Math.round((getDistanceInMeters(source.lat, source.lng, destination.lat, destination.lng) / 1000) * 10) / 10
      finalRouteSummary = { distanceKm: dist, durationMins: Math.round(dist * 2.5) }
    }
  }

  // 3. Format departureTime as Firestore Timestamp if needed
  let finalDepartureTime = departureTime
  if (!(finalDepartureTime instanceof Timestamp)) {
    if (finalDepartureTime instanceof Date) {
      finalDepartureTime = Timestamp.fromDate(finalDepartureTime)
    } else if (typeof finalDepartureTime === "string") {
      finalDepartureTime = Timestamp.fromDate(new Date(finalDepartureTime))
    } else {
      finalDepartureTime = Timestamp.now()
    }
  }

  // 4. Construct Firestore document adhering to the requested schema
  const newRide = {
    driverId: driverId || "",
    driverName,
    vehicleType,
    availableSeats: Number(availableSeats),
    farePerSeat: Number(farePerSeat) || 0,
    status: "active",
    departureTime: finalDepartureTime,
    source: {
      name: source.name || "Trivandrum Origin",
      lat: Number(source.lat),
      lng: Number(source.lng),
      h3IndexRes8: sourceH3,
      pickupRadiusMeters: Number(pickupRadiusMeters) || 1000
    },
    destination: {
      name: destination.name || "Trivandrum Destination",
      lat: Number(destination.lat),
      lng: Number(destination.lng),
      h3IndexRes8: destH3,
      dropoffRadiusMeters: Number(dropoffRadiusMeters) || 1000
    },
    routeSummary: {
      distanceKm: finalRouteSummary.distanceKm || 0,
      durationMins: finalRouteSummary.durationMins || 0
    },
    // Backwards-compatible aliases for existing Waymate UI components
    ownerId: driverId,
    hostName: driverName,
    from: source.name,
    to: destination.name,
    totalSeats: Number(availableSeats),
    createdAt: serverTimestamp()
  }

  const docRef = await addDoc(collection(db, "rides"), newRide)
  return { id: docRef.id, ...newRide }
}

/**
 * Searches and matches rides using Uber H3 Hexagonal Spatial Indexing
 */
export async function matchRidesWithH3(riderQuery) {
  const {
    source,
    destination,
    minSeats = 1,
    vehicleType
  } = riderQuery

  if (!source?.lat || !source?.lng) {
    throw new Error("Rider source coordinates are required for H3 matching")
  }
  if (!destination?.lat || !destination?.lng) {
    throw new Error("Rider destination coordinates are required for H3 matching")
  }

  const pickupRadius = source.pickupRadiusMeters || 1000
  const dropoffRadius = destination.dropoffRadiusMeters || 1000

  // 1. Generate H3 search disk around rider's pickup spot
  const sourceSearchDisk = getH3SearchDisk(source.lat, source.lng, pickupRadius)

  // 2. Generate H3 search disk around rider's drop-off spot
  const destSearchDisk = new Set(getH3SearchDisk(destination.lat, destination.lng, dropoffRadius))

  // 3. Query Firestore rides by source H3 cells
  const chunks = []
  const maxInLimit = 30
  for (let i = 0; i < sourceSearchDisk.length; i += maxInLimit) {
    chunks.push(sourceSearchDisk.slice(i, i + maxInLimit))
  }

  const candidateRides = []
  const seenIds = new Set()

  for (const chunk of chunks) {
    const q1 = query(
      collection(db, "rides"),
      where("source.h3IndexRes8", "in", chunk),
      limit(50)
    )
    const snap = await getDocs(q1)

    for (const d of snap.docs) {
      if (!seenIds.has(d.id)) {
        seenIds.add(d.id)
        candidateRides.push({ id: d.id, ...d.data() })
      }
    }
  }

  // 4. Spatial Matching & Verification (Dual H3 Check + Exact Haversine Distance)
  const matchedRides = []

  for (const ride of candidateRides) {
    const status = (ride.status || "").toUpperCase()
    if (status !== "OPEN" && status !== "ACTIVE") continue

    const seats = Number(ride.availableSeats ?? ride.totalSeats ?? 0)
    if (seats < minSeats) continue

    if (vehicleType && ride.vehicleType && ride.vehicleType !== vehicleType) continue

    const driverSrc = {
      lat: ride.source?.lat ?? ride.fromLocation?.latitude,
      lng: ride.source?.lng ?? ride.fromLocation?.longitude
    }
    const driverDst = {
      lat: ride.destination?.lat ?? ride.toLocation?.latitude,
      lng: ride.destination?.lng ?? ride.toLocation?.longitude
    }

    if (!driverSrc.lat || !driverSrc.lng || !driverDst.lat || !driverDst.lng) continue

    const sourceDistanceMeters = getDistanceInMeters(source.lat, source.lng, driverSrc.lat, driverSrc.lng)
    const destDistanceMeters = getDistanceInMeters(destination.lat, destination.lng, driverDst.lat, driverDst.lng)

    const driverDestH3 = ride.destination?.h3IndexRes8 || getH3Cell(driverDst.lat, driverDst.lng, 8)
    const isDestH3Match = destSearchDisk.has(driverDestH3)

    const isSourceWithinRadius = sourceDistanceMeters <= pickupRadius
    const isDestWithinRadius = destDistanceMeters <= dropoffRadius || isDestH3Match

    if (isSourceWithinRadius && isDestWithinRadius) {
      const totalDetourMeters = sourceDistanceMeters + destDistanceMeters

      matchedRides.push({
        ...ride,
        sourceDistanceMeters,
        destDistanceMeters,
        totalDetourMeters,
        pickupRadiusMeters: pickupRadius,
        dropoffRadiusMeters: dropoffRadius,
        isH3Match: true
      })
    }
  }

  matchedRides.sort((a, b) => a.totalDetourMeters - b.totalDetourMeters)
  return matchedRides
}

/**
 * Smallest-Distance Ride Matching Algorithm
 * Queries open rides, calculates exact pickup/dropoff/total Haversine walk distance,
 * filters by circle radii, and sorts strictly by smallest total distance.
 */
export async function findRidesBySmallestDistance({
  riderSource,
  source: origSource,
  riderDestination,
  destination: origDestination,
  maxDistanceMeters = 2500,
  pickupRadiusMeters = 2500,
  dropoffRadiusMeters = 2500,
  minSeats = 1,
  vehicleType,
  userId,
  date,
  time,
  maxTimeDiffMinutes = MAX_TIME_DIFF_MINUTES
}) {
  const source = riderSource || origSource
  const destination = riderDestination || origDestination
  const effectivePickupRadius = pickupRadiusMeters ?? maxDistanceMeters ?? 2500
  const effectiveDropoffRadius = dropoffRadiusMeters ?? maxDistanceMeters ?? 2500

  if (!source?.lat || !source?.lng) {
    throw new Error("Passenger source coordinates are required")
  }
  if (!destination?.lat || !destination?.lng) {
    throw new Error("Passenger destination coordinates are required")
  }

  const ridesRef = collection(db, "rides")
  const candidateDocs = []
  const seenIds = new Set()

  // 1. Query rides by status and date in Firestore if date is provided
  if (date) {
    try {
      const qDate = query(
        ridesRef,
        where("status", "in", ["active", "OPEN"]),
        where("date", "==", date),
        limit(50)
      )
      const snapDate = await getDocs(qDate)
      snapDate.forEach(d => {
        seenIds.add(d.id)
        candidateDocs.push({ id: d.id, ...d.data() })
      })
    } catch (err) {
      console.warn("[rideService] Query by status + date failed:", err)
    }
  }

  // 2. Query active rides if date was not provided or candidateDocs is still empty
  if (candidateDocs.length === 0) {
    try {
      const qActive = query(ridesRef, where("status", "in", ["active", "OPEN"]), limit(50))
      const snapActive = await getDocs(qActive)
      snapActive.forEach(d => {
        if (!seenIds.has(d.id)) {
          seenIds.add(d.id)
          candidateDocs.push({ id: d.id, ...d.data() })
        }
      })
    } catch (err) {
      console.warn("[rideService] Query active status failed:", err)
    }
  }

  // Fallback if index query returned empty or failed
  if (candidateDocs.length === 0) {
    try {
      const qAll = query(ridesRef, limit(50))
      const snapAll = await getDocs(qAll)
      snapAll.forEach(d => {
        const data = d.data()
        const st = (data.status || "").toLowerCase()
        if ((st === "open" || st === "active" || !data.status) && !seenIds.has(d.id)) {
          seenIds.add(d.id)
          candidateDocs.push({ id: d.id, ...data })
        }
      })
    } catch (e) {
      console.warn("[rideService] General fallback query failed:", e)
    }
  }

  const matchedRides = []

  for (const ride of candidateDocs) {
    if (userId && (ride.ownerId === userId || ride.driverId === userId)) continue

    // Exclude expired or completed/cancelled rides and update doc status
    if (isRideExpired(ride.date, ride.departureTime || ride.time, ride.status)) {
      const hasPassengers = Array.isArray(ride.acceptedPassengers) && ride.acceptedPassengers.length > 0
      const newStatus = hasPassengers ? "completed" : "expired"
      if (ride.id && ride.status !== newStatus) {
        updateDoc(doc(db, "rides", ride.id), { status: newStatus, updatedAt: serverTimestamp() }).catch(() => {})
      }
      continue
    }

    // Filter by target date if provided
    if (date && ride.date && ride.date !== date) continue

    // Filter by departure time window (±maxTimeDiffMinutes) if search time is provided
    if (time && (ride.departureTime || ride.time)) {
      const rideTime = ride.departureTime || ride.time
      const timeDiff = calculateTimeDifferenceMinutes(time, rideTime)
      if (timeDiff > maxTimeDiffMinutes) continue
    }

    const seats = Number(ride.availableSeats ?? ride.totalSeats ?? 0)
    if (seats < minSeats) continue

    if (vehicleType && ride.vehicleType && ride.vehicleType !== vehicleType) continue

    const driverSrc = {
      lat: ride.source?.lat ?? ride.fromLocation?.latitude,
      lng: ride.source?.lng ?? ride.fromLocation?.longitude
    }
    const driverDst = {
      lat: ride.destination?.lat ?? ride.toLocation?.latitude,
      lng: ride.destination?.lng ?? ride.toLocation?.longitude
    }

    if (!driverSrc.lat || !driverSrc.lng || !driverDst.lat || !driverDst.lng) continue

    const pickupDistanceMeters = getDistanceInMeters(source.lat, source.lng, driverSrc.lat, driverSrc.lng)
    const dropoffDistanceMeters = getDistanceInMeters(destination.lat, destination.lng, driverDst.lat, driverDst.lng)
    const totalDistanceMeters = pickupDistanceMeters + dropoffDistanceMeters

    if (pickupDistanceMeters <= effectivePickupRadius && dropoffDistanceMeters <= effectiveDropoffRadius) {
      matchedRides.push({
        ...ride,
        pickupDistanceMeters,
        dropoffDistanceMeters,
        totalDistanceMeters,
        pickupDistanceFormatted: formatDistance(pickupDistanceMeters),
        dropoffDistanceFormatted: formatDistance(dropoffDistanceMeters),
        totalDistanceFormatted: formatDistance(totalDistanceMeters),
        proximityBadge: `Pickup: ${formatDistance(pickupDistanceMeters)} away • Drop-off: ${formatDistance(dropoffDistanceMeters)} away (Total walk: ${formatDistance(totalDistanceMeters)})`,
        isClosestMatch: false
      })
    }
  }

  // Sort strictly in ascending order of totalDistanceMeters, tie-breaking by pickupDistanceMeters
  matchedRides.sort((a, b) => {
    if (a.totalDistanceMeters !== b.totalDistanceMeters) {
      return a.totalDistanceMeters - b.totalDistanceMeters
    }
    return a.pickupDistanceMeters - b.pickupDistanceMeters
  })

  // Mark the #1 closest ride
  if (matchedRides.length > 0) {
    matchedRides[0].isClosestMatch = true
  }

  return matchedRides
}

/**
 * Get ride by ID
 */
export async function getRideById(rideId) {
  const docRef = doc(db, "rides", rideId)
  const snap = await getDoc(docRef)
  if (snap.exists()) {
    const data = { id: snap.id, ...snap.data() }
    if (isRideExpired(data.date, data.departureTime || data.time, data.status)) {
      const hasPassengers = Array.isArray(data.acceptedPassengers) && data.acceptedPassengers.length > 0
      const newStatus = hasPassengers ? "completed" : "expired"
      if (data.status !== newStatus) {
        await updateDoc(docRef, { status: newStatus, updatedAt: serverTimestamp() }).catch(() => {})
        data.status = newStatus
      }
    }
    return data
  }
  return null
}

/**
 * Update ride status ("OPEN" | "FULL" | "COMPLETED" | "CANCELLED")
 */
export async function updateRideStatus(rideId, status) {
  const rideRef = doc(db, "rides", rideId)
  await updateDoc(rideRef, {
    status,
    updatedAt: serverTimestamp()
  })
}

/**
 * Aliases for matching & creation
 */
export const createRideOffer = createRideWithH3
export const findMatchingRides = findRidesBySmallestDistance

export default {
  createRideWithH3,
  createRideOffer,
  matchRidesWithH3,
  findRidesBySmallestDistance,
  findMatchingRides,
  getRideById,
  updateRideStatus
}
