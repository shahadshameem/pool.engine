import {
  collection,
  query,
  where,
  limit,
  getDocs,
  doc,
  getDoc,
  updateDoc,
  serverTimestamp,
  addDoc,
  Timestamp
} from "firebase/firestore"
import { db } from "../../config/firebase"
import { notificationService } from "../notification/notificationService"
import { rideMatchService } from "../rideMatch/rideMatchService"
import {
  calculateTimeDifferenceMinutes,
  MAX_TIME_DIFF_MINUTES,
  isRideExpired,
  calculateHaversineDistance,
  parseTimeToMinutes
} from "../../config/matchingConfig"
import { getLocalDateString, formatTime12h } from "../../utils/formatters"
import type { UserProfile } from "../user/userService"
import { blockService } from "../safety/blockService"
import { getH3Cell } from "../../utils/locationService"
import { removeUndefined } from "../../utils/firestoreUtils"
import { RIDE_STATUS, normalizeRideStatus } from "../../types/rideStatus"
import type { RideStatus } from "../../types/rideStatus"
import { isPoolEngineEnabled } from "../../config/poolEngineConfig"
import { poolEngineAdapter } from "../poolEngine/poolEngineAdapter"

export { RIDE_STATUS, normalizeRideStatus }
export type { RideStatus }
export type GenderPolicy = "any" | "female_only" | "female" | "unknown"

export interface AcceptedPassenger {
  uid: string
  name: string
  college?: string
  department?: string
  year?: string
  verified?: boolean
  joinedAt?: string
}

export interface RideLocation {
  name?: string
  address: string
  latitude: number
  longitude: number
  matchedZoneId?: string
  rawGps?: { lat: number; lng: number; accuracy: number }
  isLowAccuracy?: boolean
  accuracyMeters?: number
}

export interface Ride {
  id?: string
  ownerId: string
  from: string
  to: string
  fromLocation?: RideLocation
  toLocation?: RideLocation
  date: string
  departureTime: string
  availableSeats: number
  totalSeats: number
  seats?: number
  meetingPoint?: string
  vehicleType?: string
  notes?: string
  genderPolicy?: GenderPolicy
  status: RideStatus
  acceptedPassengers?: AcceptedPassenger[]
  matchGroupId?: string
  hostName?: string
  hostDepartment?: string
  hostYear?: string
  hostCollege?: string
  createdAt?: any
  updatedAt?: any
}

const activeCreateRequests = new Set<string>()

export type RideEligibilityCode =
  | "GENDER_VERIFICATION_REQUIRED"
  | "RIDE_GENDER_POLICY_RESTRICTED"
  | "GENDER_MISMATCH"
  | "RIDE_FULL"
  | "RIDE_NOT_ACTIVE"
  | "RIDE_EXPIRED"
  | "SELF_REQUEST"
  | "BLOCKED_USER"
  | "ACCOUNT_RESTRICTED"
  | "NOT_AUTHENTICATED"

export interface RideEligibilityResult {
  eligible: boolean
  reason?: string
  code?: RideEligibilityCode
}

export const rideService = {
  async createRide(
    ownerId: string,
    data: Omit<Ride, "id" | "ownerId" | "status" | "createdAt" | "updatedAt" | "genderPolicy">
  ): Promise<string> {
    const requestKey = `${ownerId}_${data.date}_${data.departureTime}_${data.from}_${data.to}`
    if (activeCreateRequests.has(requestKey)) {
      console.warn("[rideService] Duplicate ride creation attempt blocked in-flight for key:", requestKey)
      throw new Error("A ride creation request for this route and schedule is already in progress.")
    }
    activeCreateRequests.add(requestKey)

    try {
      // 1. Mandatory Fields & String Length Validation
      const fromTrim = (data.from || "").trim()
      const toTrim = (data.to || "").trim()
      if (fromTrim.length < 2 || fromTrim.length > 150) {
        throw new Error("'from' location must be between 2 and 150 characters.")
      }
      if (toTrim.length < 2 || toTrim.length > 150) {
        throw new Error("'to' location must be between 2 and 150 characters.")
      }
      if (!data.date) throw new Error("'date' is required")
      if (!data.departureTime) throw new Error("'departureTime' is required")
      if (data.notes && data.notes.length > 500) {
        throw new Error("Notes cannot exceed 500 characters.")
      }
      if (data.meetingPoint && data.meetingPoint.length > 200) {
        throw new Error("Meeting point cannot exceed 200 characters.")
      }

      // 2. Origin != Destination
      if (fromTrim.toLowerCase() === toTrim.toLowerCase()) {
        throw new Error("Origin and destination cannot be the same place.")
      }
      if (
        data.fromLocation?.latitude && data.fromLocation?.longitude &&
        data.toLocation?.latitude && data.toLocation?.longitude
      ) {
        const distKm = calculateHaversineDistance(
          data.fromLocation.latitude, data.fromLocation.longitude,
          data.toLocation.latitude, data.toLocation.longitude
        )
        if (distKm < 0.1) {
          throw new Error("Origin and destination are too close (must be at least 100m apart).")
        }
      }

      // 3. Past Date / Time Validation
      const departureMinutes = parseTimeToMinutes(data.departureTime)
      let depYear = 0
      let depMonth = 0
      let depDay = 0
      const isoMatch = data.date.match(/^(\d{4})-(\d{2})-(\d{2})/)
      if (isoMatch) {
        depYear = parseInt(isoMatch[1], 10)
        depMonth = parseInt(isoMatch[2], 10) - 1
        depDay = parseInt(isoMatch[3], 10)
      } else {
        const dObj = new Date(data.date)
        depYear = dObj.getFullYear()
        depMonth = dObj.getMonth()
        depDay = dObj.getDate()
      }
      const departureDate = new Date(
        depYear,
        depMonth,
        depDay,
        Math.floor(departureMinutes / 60),
        departureMinutes % 60,
        0,
        0
      )
      const now = Date.now()
      // Allow 2-minute clock skew buffer
      if (departureDate.getTime() < now - 2 * 60 * 1000) {
        throw new Error("Cannot create a ride for a past date or time.")
      }

      // 4. Vehicle Capacity Ceiling
      const totalSeats = data.totalSeats !== undefined ? data.totalSeats : (data.seats !== undefined ? data.seats : 1)
      const availableSeats = data.availableSeats !== undefined ? data.availableSeats : totalSeats
      const defaultVehicle = (totalSeats > 1) ? "car" : "bike"
      const vehicle = (data.vehicleType || defaultVehicle).toLowerCase()
      const MAX_CAPACITY: Record<string, number> = {
        bike: 1,
        auto: 3,
        car: 6
      }
      const maxSeats = MAX_CAPACITY[vehicle] || 6
      if (totalSeats < 1 || totalSeats > maxSeats) {
        throw new Error(`Vehicle type '${vehicle}' allows between 1 and ${maxSeats} passenger seats.`)
      }
      if (availableSeats < 0) throw new Error("'availableSeats' cannot be negative")
      if (availableSeats > totalSeats) throw new Error("'availableSeats' cannot exceed 'totalSeats'")

      // Server-derived genderPolicy from creator's users/{uid} document
      const ownerDoc = await getDoc(doc(db, "users", ownerId))
      const ownerData = ownerDoc.exists() ? ownerDoc.data() : null
      const ownerGender = ownerData?.gender as "male" | "female" | undefined

      if (!ownerGender) {
        throw new Error("Gender selection is required on your profile before offering a ride.")
      }

      // Check if host already has an active or full ride scheduled for the same date & time (or within 30 mins)
      try {
        const existingQuery = query(
          collection(db, "rides"),
          where("ownerId", "==", ownerId),
          where("date", "==", data.date)
        )
        const existingSnap = await getDocs(existingQuery)
        const conflictingRide = existingSnap.docs.find(d => {
          const r = d.data()
          if (r.status !== "active" && r.status !== "full") return false
          if (!r.departureTime || !data.departureTime) return true
          const [h1, m1] = r.departureTime.split(":").map(Number)
          const [h2, m2] = data.departureTime.split(":").map(Number)
          const t1 = h1 * 60 + m1
          const t2 = h2 * 60 + m2
          return Math.abs(t1 - t2) < 30
        })

        if (conflictingRide) {
          const confData = conflictingRide.data()
          const timeLabel = formatTime12h(confData.departureTime)
          throw new Error(`You already have an active ride scheduled (${confData.from} → ${confData.to} at ${timeLabel}). You cannot host multiple rides at the same time.`)
        }
      } catch (err: any) {
        if (err?.message?.includes("You already have an active ride")) throw err
        console.warn("[rideService] Schedule conflict check error:", err)
      }

      // Female hosts can restrict rides to female_only; male hosts create open rides ("any")
      const genderPolicy = ownerGender === "female" ? "female_only" : "any"

      // Controlled Workflow: If Pool Engine is enabled, delegate host ride creation to Pool Engine.
      // Safety Invariant: Fail loudly if Pool Engine fails; do not silently fall back to Firestore.
      if (isPoolEngineEnabled()) {
        const poolEngineRide = await poolEngineAdapter.registerHostRide(
          {
            ...data,
            from: fromTrim,
            to: toTrim,
            totalSeats,
            availableSeats,
            seats: totalSeats,
            vehicleType: data.vehicleType || defaultVehicle,
            genderPolicy
          },
          ownerId
        )
        return poolEngineRide.ride_id
      }

      const rideData: Record<string, any> = {
        ...data,
        from: fromTrim,
        to: toTrim,
        seats: totalSeats,
        totalSeats,
        availableSeats,
        departureTimestamp: Timestamp.fromDate(departureDate),
        ownerId,
        driverId: ownerId,
        driverName: ownerData?.name || "",
        genderPolicy,
        hostName: ownerData?.name || "",
        hostDepartment: ownerData?.department || "",
        hostYear: ownerData?.year || "",
        hostCollege: ownerData?.college || "College of Engineering Trivandrum (CET)",
        status: RIDE_STATUS.ACTIVE,
        vehicleType: data.vehicleType || defaultVehicle,
        farePerSeat: (data as any).farePerSeat || 0,
        source: data.fromLocation ? {
          name: data.from,
          lat: data.fromLocation.latitude,
          lng: data.fromLocation.longitude,
          h3IndexRes8: getH3Cell(data.fromLocation.latitude, data.fromLocation.longitude, 8),
          pickupRadiusMeters: 1000
        } : undefined,
        destination: data.toLocation ? {
          name: data.to,
          lat: data.toLocation.latitude,
          lng: data.toLocation.longitude,
          h3IndexRes8: getH3Cell(data.toLocation.latitude, data.toLocation.longitude, 8),
          dropoffRadiusMeters: 1000
        } : undefined,
        createdAt: serverTimestamp(),
        updatedAt: serverTimestamp()
      }

      // Deeply strip any undefined values to prevent Firestore unsupported field value errors
      const cleanRideData = removeUndefined(rideData)

      const docRef = await addDoc(collection(db, "rides"), cleanRideData)
      const createdRide = { id: docRef.id, ...cleanRideData } as Ride

      // Trigger background automatic ride-pool match detection and await completion before navigation
      try {
        await rideMatchService.triggerMatchNotifications(createdRide)
      } catch (err) {
        console.warn("Background ride-pool matching error:", err)
      }

      return docRef.id
    } finally {
      activeCreateRequests.delete(requestKey)
    }
  },

  async getRideById(rideId: string): Promise<Ride | null> {
    if (isPoolEngineEnabled()) {
      return await poolEngineAdapter.getHostRideAsWaymateRide(rideId)
    }

    try {
      const docRef = doc(db, "rides", rideId)
      const docSnap = await getDoc(docRef)

      if (docSnap.exists()) {
        const ride = { id: docSnap.id, ...docSnap.data() } as Ride
        // If departure time has passed and status is not already completed/cancelled/expired, update status
        if (
          ride.status !== RIDE_STATUS.CANCELLED &&
          ride.status !== RIDE_STATUS.COMPLETED &&
          ride.status !== RIDE_STATUS.EXPIRED &&
          isRideExpired(ride.date, ride.departureTime || (ride as any).time, ride.status)
        ) {
          const hasPassengers = Array.isArray(ride.acceptedPassengers) && ride.acceptedPassengers.length > 0
          const newStatus = hasPassengers ? RIDE_STATUS.COMPLETED : RIDE_STATUS.EXPIRED
          await updateDoc(docRef, {
            status: newStatus,
            updatedAt: serverTimestamp()
          }).catch(() => {})
          ride.status = newStatus
        }
        return ride
      }

      return null
    } catch (e) {
      return null
    }
  },

  async updateRide(
    rideId: string,
    data: Partial<Omit<Ride, "id" | "ownerId" | "createdAt" | "updatedAt">>
  ): Promise<void> {
    const docRef = doc(db, "rides", rideId)

    // Update fields with recursive undefined removal
    await updateDoc(docRef, removeUndefined({
      ...data,
      updatedAt: serverTimestamp()
    }))
  },

  async cancelRide(rideId: string, ownerId?: string, cancellationReason?: string): Promise<{ success: boolean; message: string }> {
    try {
      const rideRef = doc(db, "rides", rideId)
      const rideDoc = await getDoc(rideRef)
      if (!rideDoc.exists()) return { success: false, message: "Ride not found." }

      const rideData = rideDoc.data()
      const hostOwnerId = ownerId || rideData.ownerId

      if (ownerId && ownerId !== rideData.ownerId) {
        return { success: false, message: "Permission denied." }
      }

      const reason = cancellationReason || "Cancelled by host"

      // Core update: cancel the ride
      await updateDoc(rideRef, {
        status: "cancelled",
        cancelledBy: hostOwnerId,
        cancellationReason: reason,
        cancelledAt: serverTimestamp(),
        updatedAt: serverTimestamp()
      })

      // Cancellation and notification to passengers with pending or accepted requests
      try {
        const q = query(
          collection(db, "rideRequests"),
          where("rideId", "==", rideId),
          where("rideOwnerId", "==", hostOwnerId),
          where("status", "in", ["pending", "accepted"])
        )
        const reqsSnap = await getDocs(q)

        await Promise.all(
          reqsSnap.docs.map(async (reqDoc) => {
            const reqData = reqDoc.data()
            // Mark the request itself as cancelled
            await updateDoc(reqDoc.ref, {
              status: "cancelled",
              cancelledBy: hostOwnerId,
              cancellationReason: reason,
              cancelledAt: serverTimestamp(),
              updatedAt: serverTimestamp()
            }).catch(console.error)

            // Also update rideContacts if exists
            await updateDoc(doc(db, "rideContacts", reqDoc.id), {
              status: "cancelled",
              updatedAt: serverTimestamp()
            }).catch(() => {})

            // Send notification to the passenger
            await notificationService.createNotification({
              userId: reqData.requesterId,
              type: "ride_cancelled",
              title: "Ride cancelled",
              message: `The ride from ${rideData.from} to ${rideData.to} has been cancelled by the host. Reason: ${reason}`,
              rideId: rideId,
              rideRequestId: reqDoc.id
            }).catch(console.error)
          })
        )
      } catch (notifErr) {
        console.warn("Could not cancel requests or send cancellation notifications to passengers:", notifErr)
      }
      return { success: true, message: "Ride cancelled successfully." }
    } catch (e: any) {
      if (e?.code === "permission-denied" || e?.message?.includes("permission") || e?.message?.includes("Permission")) {
        return { success: false, message: "Permission denied." }
      }
      return { success: false, message: e?.message || "Failed to cancel ride." }
    }
  },

  async getMyRides(ownerId: string): Promise<Ride[]> {
    const ridesRef = collection(db, "rides")
    const q = query(
      ridesRef,
      where("ownerId", "==", ownerId),
      limit(30)
    )
    const snap = await getDocs(q)
    return snap.docs.map(doc => ({ id: doc.id, ...doc.data() } as Ride))
  },

  async startRide(rideId: string, userId: string): Promise<{ success: boolean; message: string }> {
    try {
      const rideRef = doc(db, "rides", rideId)
      const rideDoc = await getDoc(rideRef)
      if (!rideDoc.exists()) return { success: false, message: "Ride not found." }

      const rideData = rideDoc.data()
      const isParticipant = rideData.ownerId === userId || (
        Array.isArray(rideData.acceptedPassengers) &&
        rideData.acceptedPassengers.some((p: any) => p.uid === userId)
      )
      if (!isParticipant) {
        return { success: false, message: "Permission denied. Only confirmed participants can start this trip." }
      }
      if (rideData.status === "cancelled") {
        return { success: false, message: "Cancelled rides cannot be started." }
      }
      if (rideData.status === "completed") {
        return { success: false, message: "Completed rides cannot be restarted." }
      }

      await updateDoc(rideRef, {
        status: "started",
        startedAt: serverTimestamp(),
        updatedAt: serverTimestamp()
      })

      // Send notifications to accepted passengers
      try {
        const q = query(
          collection(db, "rideRequests"),
          where("rideId", "==", rideId),
          where("rideOwnerId", "==", rideData.ownerId),
          where("status", "==", "accepted")
        )
        const reqsSnap = await getDocs(q)
        await Promise.all(
          reqsSnap.docs.map(async (reqDoc) => {
            const reqData = reqDoc.data()
            await notificationService.createNotification({
              userId: reqData.requesterId,
              type: "ride_started",
              title: "Ride Started",
              message: `Your ride from ${rideData.from} to ${rideData.to} has started!`,
              rideId: rideId
            }).catch(console.error)
          })
        )
      } catch (notifErr) {
        console.warn("Could not notify passengers of started ride:", notifErr)
      }

      return { success: true, message: "Ride marked as started!" }
    } catch (e: any) {
      return { success: false, message: e?.message || "Failed to start ride." }
    }
  },

  async completeRide(rideId: string, userId: string): Promise<{ success: boolean; message: string }> {
    try {
      const rideRef = doc(db, "rides", rideId)
      const rideDoc = await getDoc(rideRef)
      if (!rideDoc.exists()) return { success: false, message: "Ride not found." }

      const rideData = rideDoc.data()
      const isParticipant = rideData.ownerId === userId || (
        Array.isArray(rideData.acceptedPassengers) &&
        rideData.acceptedPassengers.some((p: any) => p.uid === userId)
      )
      if (!isParticipant) {
        return { success: false, message: "Permission denied. Only confirmed participants can complete this trip." }
      }
      if (rideData.status === "cancelled") {
        return { success: false, message: "Cancelled rides cannot be completed." }
      }
      if (rideData.status === "completed") {
        return { success: true, message: "Ride is already completed." }
      }

      await updateDoc(rideRef, {
        status: "completed",
        completedAt: serverTimestamp(),
        updatedAt: serverTimestamp()
      })

      // Send notifications to accepted passengers and seal ride contacts
      try {
        const q = query(
          collection(db, "rideRequests"),
          where("rideId", "==", rideId),
          where("rideOwnerId", "==", rideData.ownerId),
          where("status", "==", "accepted")
        )
        const reqsSnap = await getDocs(q)
        await Promise.all(
          reqsSnap.docs.map(async (reqDoc) => {
            const reqData = reqDoc.data()
            await notificationService.createNotification({
              userId: reqData.requesterId,
              type: "ride_completed",
              title: "Ride Completed",
              message: `Your ride from ${rideData.from} to ${rideData.to} has ended. Thank you for riding with WayMate!`,
              rideId: rideId
            }).catch(console.error)

            // Seal contact details on completion for DPDPA privacy
            await updateDoc(doc(db, "rideContacts", reqDoc.id), {
              status: "completed",
              updatedAt: serverTimestamp()
            }).catch(() => {})
          })
        )
      } catch (notifErr) {
        console.warn("Could not notify passengers of completed ride:", notifErr)
      }

      return { success: true, message: "Ride marked as completed!" }
    } catch (e: any) {
      return { success: false, message: e?.message || "Failed to complete ride." }
    }
  },

  async getMyPassengerRides(passengerId: string): Promise<Ride[]> {
    try {
      const q = query(
        collection(db, "rideRequests"),
        where("requesterId", "==", passengerId),
        where("status", "==", "accepted"),
        limit(30)
      );
      const snap = await getDocs(q);

      const rideIds = snap.docs.map(doc => doc.data().rideId);
      if (rideIds.length === 0) return [];

      const rides = await Promise.all(
        rideIds.map(async (id) => {
          const r = await this.getRideById(id);
          return r;
        })
      );

      return rides.filter((r): r is Ride => r !== null);
    } catch (e) {
      console.error(e);
      return [];
    }
  },

  /**
   * Centralized evaluation of ride eligibility for a user with structured error codes.
   */
  isRideEligibleForUser(
    ride: Ride,
    user: UserProfile | null,
    options?: { isBlocked?: boolean }
  ): RideEligibilityResult {
    if (!user) {
      return { eligible: false, reason: "You must be signed in to request a seat.", code: "NOT_AUTHENTICATED" }
    }
    if (!user.gender) {
      return { eligible: false, reason: "Please select your gender on your profile before requesting a ride.", code: "GENDER_VERIFICATION_REQUIRED" }
    }
    if (user.accountStatus && user.accountStatus !== "active") {
      return { eligible: false, reason: "Your account currently has restricted access to rides.", code: "ACCOUNT_RESTRICTED" }
    }
    if (options?.isBlocked) {
      return { eligible: false, reason: "You cannot interact with this ride.", code: "BLOCKED_USER" }
    }
    if (ride.ownerId === user.uid) {
      return { eligible: false, reason: "You cannot request your own ride.", code: "SELF_REQUEST" }
    }
    if (normalizeRideStatus(ride.status) !== RIDE_STATUS.ACTIVE) {
      return { eligible: false, reason: "This ride is no longer active.", code: "RIDE_NOT_ACTIVE" }
    }
    if (isRideExpired(ride)) {
      return { eligible: false, reason: "This ride has already departed or expired.", code: "RIDE_EXPIRED" }
    }
    if (ride.availableSeats <= 0) {
      return { eligible: false, reason: "No available seats remaining on this ride.", code: "RIDE_FULL" }
    }

    const policy = ride.genderPolicy || "any"
    if (policy === "female_only" || policy === "female") {
      if (user.gender !== "female") {
        return {
          eligible: false,
          reason: "This ride is available only to female riders.",
          code: "GENDER_MISMATCH"
        }
      }
    }

    return { eligible: true }
  },

  async searchRides(filters: {
    from: string;
    to: string;
    date: string;
    time?: string;
    seats: number;
    userGender?: "male" | "female";
    userId?: string;
    matchedZoneId?: string;
    fromCoords?: { lat: number; lng: number };
  }): Promise<Ride[]> {
    const ridesRef = collection(db, "rides")
    const targetDate = filters.date || getLocalDateString()

    const qSearch = query(
      ridesRef,
      where("status", "in", ["active", "OPEN"]),
      where("date", "==", targetDate),
      limit(50)
    )

    try {
      const snap = await getDocs(qSearch).catch(async () => {
        // Fallback for emulator or unindexed queries: query by status active
        const qFallback = query(ridesRef, where("status", "==", "active"), limit(50))
        return getDocs(qFallback)
      })

      const seen = new Set<string>()
      const allRides: Ride[] = []
      for (const d of snap.docs) {
        if (!seen.has(d.id)) {
          seen.add(d.id)
          allRides.push({ id: d.id, ...d.data() } as Ride)
        }
      }

      let blockedSet = new Set<string>()
      if (filters.userId) {
        blockedSet = await blockService.getBlockedUserIds(filters.userId)
      }

      const filteredRides = allRides.filter(ride => {
        // Exclude rides owned by blocked users or self
        if (filters.userId) {
          if (ride.ownerId === filters.userId || blockedSet.has(ride.ownerId)) {
            return false
          }
        }

        // Enforce Gender Matching: only show female_only rides to female users
        if (filters.userGender) {
          const policy = ride.genderPolicy || "any"
          if (policy === "female_only" || policy === "female") {
            if (filters.userGender !== "female") return false
          }
        }

        // Exclude expired or completed/cancelled rides and update doc status
        if (isRideExpired(ride.date, ride.departureTime || (ride as any).time, ride.status)) {
          if (
            ride.status !== RIDE_STATUS.CANCELLED &&
            ride.status !== RIDE_STATUS.COMPLETED &&
            ride.status !== RIDE_STATUS.EXPIRED
          ) {
            const hasPassengers = Array.isArray(ride.acceptedPassengers) && ride.acceptedPassengers.length > 0
            const newStatus = hasPassengers ? RIDE_STATUS.COMPLETED : RIDE_STATUS.EXPIRED
            if (ride.id) {
              updateDoc(doc(db, "rides", ride.id), { status: newStatus, updatedAt: serverTimestamp() }).catch(() => {})
            }
          }
          return false
        }

        // Enforce strict time tolerance (±10 mins) if search time is provided
        if (filters.time) {
          const timeDiff = calculateTimeDifferenceMinutes(filters.time, ride.departureTime)
          if (timeDiff > MAX_TIME_DIFF_MINUTES) {
            return false
          }
        }

        // Normalize strings for reliable matching (e.g., "CET " === "cet")
        const offerFrom = ride.from?.trim().toLowerCase() || ""
        const searchFrom = filters.from?.trim().toLowerCase() || ""

        const offerTo = ride.to?.trim().toLowerCase() || ""
        const searchTo = filters.to?.trim().toLowerCase() || ""

        // Check matched campus zone ID (e.g. "cet-front-gate" or "cet")
        const isCetFrom = (str: string) => str.includes("cet") || str.includes("college of engineering")
        const rideZoneId = (ride.fromLocation as any)?.matchedZoneId || (isCetFrom(offerFrom) ? "cet-front-gate" : undefined)
        const searchZoneId = filters.matchedZoneId || (isCetFrom(searchFrom) ? "cet-front-gate" : undefined)
        const isZoneMatch = Boolean(
          rideZoneId && searchZoneId && (
            rideZoneId === searchZoneId ||
            (rideZoneId.startsWith("cet") && searchZoneId.startsWith("cet"))
          )
        )

        // Flexible route match (exact, substring, or shared campus zone)
        const isFromMatch = isZoneMatch || offerFrom === searchFrom || offerFrom.includes(searchFrom) || searchFrom.includes(offerFrom)
        const isToMatch = offerTo === searchTo || offerTo.includes(searchTo) || searchTo.includes(offerTo)
        const isRouteMatch = isFromMatch && isToMatch

        // Seat availability match (>=)
        const hasEnoughSeats = ride.availableSeats >= filters.seats

        if (!isRouteMatch || !hasEnoughSeats) {
          return false
        }

        return true
      })

      return filteredRides

    } catch (error) {
      console.error("Firestore query failed in searchRides:", error)
      throw error
    }
  }
}
