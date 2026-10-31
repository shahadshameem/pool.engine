import {
  collection,
  query,
  where,
  getDocs,
  addDoc,
  serverTimestamp,
  doc,
  getDoc,
  runTransaction,
  updateDoc,
  setDoc
} from "firebase/firestore"
import { db, auth } from "../../config/firebase"
import { notificationService } from "../notification/notificationService"
import { userService, type UserProfile } from "../user/userService"
import { cabPoolService } from "../cabPool/cabPoolService"
import { rideService, type Ride } from "../ride/rideService"
import { blockService } from "../safety/blockService"
import { getDistanceInMeters } from "../../utils/locationService"

export type RideRequestStatus = "pending" | "accepted" | "rejected" | "cancelled"

export interface RideRequest {
  id?: string
  rideId: string
  requesterId: string
  rideOwnerId: string
  seatsRequested: number
  message?: string
  status: RideRequestStatus
  createdAt?: any
  updatedAt?: any
  requesterName?: string
  requesterCollege?: string
  requesterDepartment?: string
  requesterYear?: string
  requesterGender?: string
  pickupLocation?: {
    lat?: number
    lng?: number
    name?: string
    address?: string
  } | null
  pickupDistanceMeters?: number | null
}

export type RideRequestErrorCode =
  | "GENDER_VERIFICATION_REQUIRED"
  | "RIDE_GENDER_POLICY_RESTRICTED"
  | "GENDER_MISMATCH"
  | "REQUEST_COOLDOWN"
  | "DUPLICATE_REQUEST"
  | "RIDE_FULL"
  | "RIDE_NOT_ACTIVE"
  | "RIDE_EXPIRED"
  | "SELF_REQUEST"
  | "PAST_RIDE"
  | "BLOCKED_USER"
  | "ACCOUNT_RESTRICTED"
  | "INVALID_RIDE"

export interface CreateRideRequestResult {
  success: boolean
  requestId?: string
  code?: RideRequestErrorCode
  retryAfter?: number
  message: string
}

export const REJECTION_COOLDOWN_MS = 30 * 60 * 1000 // 30 minutes server-authoritative cooldown

export const rideRequestService = {
  /**
   * Submits a new ride request, checking for eligibility, duplicate active requests, and rejection cooldowns.
   */
  async createRideRequest(
    ride: { id: string; ownerId: string; status: string; availableSeats: number; from: string; to: string; date: string; departureTime: string; genderPolicy?: string; fromLocation?: any },
    requesterId: string,
    seatsRequested: number,
    message: string = "",
    pickupLocation?: { lat?: number; lng?: number; latitude?: number; longitude?: number; name?: string; address?: string } | null
  ): Promise<CreateRideRequestResult> {

    if (!ride.id) return { success: false, code: "INVALID_RIDE", message: "Invalid ride." }
    if (seatsRequested <= 0) {
      return { success: false, code: "INVALID_RIDE", message: "You must request at least 1 seat." }
    }

    // Always fetch authoritative requester profile directly from Firestore
    const requesterProfile = await userService.getUserProfile(requesterId, true)
    if (!requesterProfile) {
      return { success: false, code: "INVALID_RIDE", message: "User profile not found." }
    }

    // Fetch authoritative target ride doc from Firestore
    const rideDoc = await getDoc(doc(db, "rides", ride.id))
    if (!rideDoc.exists()) {
      return { success: false, code: "INVALID_RIDE", message: "Target ride not found." }
    }

    const fullRideData = { id: rideDoc.id, ...rideDoc.data() } as Ride

    // Check block relationship
    const isBlocked = await blockService.isBlockedRelationship(requesterId, fullRideData.ownerId)

    // Centralized eligibility check
    const eligibility = rideService.isRideEligibleForUser(fullRideData, requesterProfile, { isBlocked })
    if (!eligibility.eligible) {
      return {
        success: false,
        code: (eligibility.code as RideRequestErrorCode) || "INVALID_RIDE",
        message: eligibility.reason || "You are not eligible for this ride."
      }
    }

    if (seatsRequested > fullRideData.availableSeats) {
      return { success: false, code: "RIDE_FULL", message: "Not enough seats available." }
    }

    const reqsRef = collection(db, "rideRequests")
    const q = query(
      reqsRef,
      where("rideId", "==", ride.id),
      where("requesterId", "==", requesterId)
    )

    const snap = await getDocs(q)
    const existingRequests = snap.docs.map(d => ({ id: d.id, ...d.data() } as RideRequest & { rejectedAt?: any }))

    const existingActive = existingRequests.find(r => r.status === "pending" || r.status === "accepted")
    if (existingActive) {
      return {
        success: false,
        code: "DUPLICATE_REQUEST",
        message: `You already have a ${existingActive.status} request for this ride.`,
        requestId: existingActive.id
      }
    }

    // Server-authoritative 30-minute rejection cooldown check
    const rejectedReqs = existingRequests
      .filter(r => r.status === "rejected")
      .sort((a, b) => {
        const timeA = a.updatedAt?.toMillis?.() || a.createdAt?.toMillis?.() || 0
        const timeB = b.updatedAt?.toMillis?.() || b.createdAt?.toMillis?.() || 0
        return timeB - timeA
      })

    if (rejectedReqs.length > 0) {
      const lastRejected = rejectedReqs[0]
      const rejectedTime = lastRejected.updatedAt?.toMillis?.() || lastRejected.createdAt?.toMillis?.() || Date.now()
      const elapsed = Date.now() - rejectedTime
      if (elapsed < REJECTION_COOLDOWN_MS) {
        const remainingMs = REJECTION_COOLDOWN_MS - elapsed
        const remainingMins = Math.ceil(remainingMs / (60 * 1000))
        return {
          success: false,
          code: "REQUEST_COOLDOWN",
          retryAfter: Date.now() + remainingMs,
          message: `The host recently declined your previous request for this ride. You can try again after ${remainingMins} min.`
        }
      }
    }

    let reqPickup: any = null
    let reqDistMeters: number | null = null

    if (pickupLocation) {
      const pLat = pickupLocation.lat ?? pickupLocation.latitude
      const pLng = pickupLocation.lng ?? pickupLocation.longitude
      if (typeof pLat === "number" && typeof pLng === "number") {
        reqPickup = {
          lat: pLat,
          lng: pLng,
          name: pickupLocation.name || pickupLocation.address || "Pickup Point"
        }
        const hLat = fullRideData.fromLocation?.latitude ?? (fullRideData as any).source?.lat
        const hLng = fullRideData.fromLocation?.longitude ?? (fullRideData as any).source?.lng
        if (typeof hLat === "number" && typeof hLng === "number") {
          reqDistMeters = getDistanceInMeters(pLat, pLng, hLat, hLng)
        }
      }
    }

    const requestData: Omit<RideRequest, "id"> = {
      rideId: ride.id,
      requesterId,
      requesterName: requesterProfile?.name || "Student",
      requesterCollege: requesterProfile?.college || "CET",
      requesterDepartment: requesterProfile?.department || "",
      requesterYear: requesterProfile?.year || "",
      requesterGender: requesterProfile?.gender || "",
      rideOwnerId: ride.ownerId,
      seatsRequested,
      message: (message || "").trim(),
      pickupLocation: reqPickup,
      pickupDistanceMeters: reqDistMeters,
      status: "pending",
      createdAt: serverTimestamp(),
      updatedAt: serverTimestamp()
    }

    let docRef: any
    try {
      docRef = await addDoc(reqsRef, requestData)
    } catch (dbErr: any) {
      console.error("[rideRequestService] addDoc error:", dbErr)
      const isPermissionDenied = dbErr?.code === "permission-denied" || dbErr?.message?.includes("Missing or insufficient permissions")
      return {
        success: false,
        code: "INVALID_RIDE",
        message: isPermissionDenied
          ? "Permission denied. Please verify your profile setup and try again."
          : (dbErr?.message || "Failed to submit request. Please try again.")
      }
    }

    // Check for reciprocal pending request (mutual simultaneous requests)
    try {
      const qReciprocal = query(
        reqsRef,
        where("requesterId", "==", ride.ownerId),
        where("rideOwnerId", "==", requesterId),
        where("status", "==", "pending")
      )
      const reciprocalSnap = await getDocs(qReciprocal)
      if (!reciprocalSnap.empty) {
        const reciprocalDoc = reciprocalSnap.docs[0]
        console.log(`[MUTUAL CONCURRENCY] Reciprocal pending request detected (${reciprocalDoc.id}). Triggering autoConsolidateMutualRequests...`)
        const consolidateResult = await this.autoConsolidateMutualRequests(docRef.id, reciprocalDoc.id, requesterId)
        if (consolidateResult.success && consolidateResult.winningRideId) {
          return {
            success: true,
            requestId: docRef.id,
            message: "Mutual ride requests consolidated! Redirecting to confirmed ride..."
          }
        }
      }
    } catch (recipErr) {
      console.warn("Mutual request check warning:", recipErr)
    }

    // Use requester profile for actor snapshot
    const actorSnapshot = requesterProfile ? JSON.parse(JSON.stringify({
      name: requesterProfile.name || "Passenger",
      college: requesterProfile.college || "",
      department: requesterProfile.department || "",
      year: requesterProfile.year || "",
      verified: !!requesterProfile.collegeVerified
    })) : undefined

    const rideSnapshot = JSON.parse(JSON.stringify({
      from: ride.from || "",
      to: ride.to || "",
      date: ride.date || "",
      time: ride.departureTime || "",
      seats: seatsRequested
    }))

    // 1. Notification for Host (User B / Incoming Request)
    notificationService.createNotification({
      userId: ride.ownerId,
      type: "ride_request",
      title: "New ride request",
      message: `${requesterProfile?.name || "Someone"} requested a seat on your ride from ${ride.from} to ${ride.to}.`,
      rideId: ride.id,
      rideRequestId: docRef.id,
      actorId: requesterId,
      actorSnapshot,
      rideSnapshot
    }).catch(console.error)

    // 1b. Notification for all existing accepted passengers in the ride pool
    try {
      const freshRideDoc = await getDoc(doc(db, "rides", ride.id))
      if (freshRideDoc.exists()) {
        const freshRideData = freshRideDoc.data()
        const acceptedPassengers: any[] = Array.isArray(freshRideData.acceptedPassengers) ? freshRideData.acceptedPassengers : []
        acceptedPassengers.forEach((p: any) => {
          const pUid = p.uid || p.passengerId || p.requesterId
          if (pUid && pUid !== requesterId && pUid !== ride.ownerId) {
            notificationService.createNotification({
              userId: pUid,
              type: "ride_request",
              title: "New ride request for your pool",
              message: `${requesterProfile?.name || "Someone"} requested a seat on your ride pool from ${ride.from} to ${ride.to}.`,
              rideId: ride.id,
              rideRequestId: docRef.id,
              actorId: requesterId,
              actorSnapshot,
              rideSnapshot
            }).catch(console.error)
          }
        })
      }
    } catch (passNotifErr) {
      console.warn("Failed to notify accepted passengers of new request:", passNotifErr)
    }

    // Fetch host profile for User A's notification
    const hostProfile = await userService.getUserProfile(ride.ownerId)
    const hostActorSnapshot = hostProfile ? JSON.parse(JSON.stringify({
      name: hostProfile.name || "Host",
      college: hostProfile.college || "",
      department: hostProfile.department || "",
      year: hostProfile.year || "",
      verified: !!hostProfile.collegeVerified
    })) : undefined

    // 2. Notification for User A (Passenger / Request Sent)
    notificationService.createNotification({
      userId: requesterId,
      type: "ride_request_sent",
      title: "Ride request sent",
      message: `Your request for ${ride.from} → ${ride.to} has been sent to ${hostProfile?.name || "the host"}.`,
      rideId: ride.id,
      rideRequestId: docRef.id,
      actorId: ride.ownerId,
      actorSnapshot: hostActorSnapshot,
      rideSnapshot
    }).catch(console.error)

    // Auto-resolve originating ride_match_found notifications for requester regarding this target ride
    notificationService.resolveUserMatchNotifications(requesterId, ride.id).catch(console.error)

    // DPDPA 2023 & Privacy: Create pending contact document in rideContacts collection
    try {
      const privSnap = await getDoc(doc(db, "users", requesterId, "private", "contact")).catch(() => null)
      let passengerPhone = privSnap?.exists() ? privSnap.data()?.phone : ""
      if (!passengerPhone) {
        // Fallback for legacy accounts
        const uDoc = await getDoc(doc(db, "users", requesterId)).catch(() => null)
        passengerPhone = uDoc?.exists() ? (uDoc.data()?.phone || "") : ""
        if (passengerPhone) {
          setDoc(doc(db, "users", requesterId, "private", "contact"), {
            uid: requesterId,
            phone: passengerPhone,
            updatedAt: serverTimestamp()
          }, { merge: true }).catch(() => {})
        }
      }
      await setDoc(doc(db, "rideContacts", docRef.id), {
        requestId: docRef.id,
        rideId: ride.id,
        hostId: ride.ownerId,
        passengerId: requesterId,
        passengerPhone: passengerPhone || "",
        passengerName: requesterProfile?.name || "Passenger",
        hostPhone: null,
        status: "pending",
        createdAt: serverTimestamp()
      })
    } catch (contactErr) {
      console.warn("Failed to create pending rideContacts doc:", contactErr)
    }

    return { success: true, requestId: docRef.id, message: "Request sent successfully!" }
  },

  /**
   * Atomically resolves mutual simultaneous requests using serverTimestamp / UID tie-break inside runTransaction.
   */
  async autoConsolidateMutualRequests(reqAId: string, reqBId: string, currentUserId?: string): Promise<{ success: boolean; winningRideId?: string }> {
    try {
      let winningRideId = ""
      const activeUid = currentUserId || auth.currentUser?.uid

      await runTransaction(db, async (transaction) => {
        const refA = doc(db, "rideRequests", reqAId)
        const refB = doc(db, "rideRequests", reqBId)
        const snapA = await transaction.get(refA)
        const snapB = await transaction.get(refB)
        if (!snapA.exists() || !snapB.exists()) return

        const dataA = { id: snapA.id, ...snapA.data() } as RideRequest
        const dataB = { id: snapB.id, ...snapB.data() } as RideRequest

        if (dataA.status !== "pending" || dataB.status !== "pending") return

        // Prefer request where rideOwnerId matches activeUid to satisfy Firestore security rules
        let winner = dataA
        let loser = dataB

        if (activeUid && dataB.rideOwnerId === activeUid) {
          winner = dataB
          loser = dataA
        } else if (activeUid && dataA.rideOwnerId === activeUid) {
          winner = dataA
          loser = dataB
        } else {
          // Fallback tie-break: earliest createdAt serverTimestamp, or deterministic document ID / UID
          const timeA = dataA.createdAt?.toMillis ? dataA.createdAt.toMillis() : null
          const timeB = dataB.createdAt?.toMillis ? dataB.createdAt.toMillis() : null

          if (timeA !== null && timeB !== null && timeA !== timeB) {
            if (timeB < timeA) {
              winner = dataB
              loser = dataA
            }
          } else {
            const keyA = dataA.id || dataA.requesterId
            const keyB = dataB.id || dataB.requesterId
            if (keyB < keyA) {
              winner = dataB
              loser = dataA
            }
          }
        }

        // Fetch winning ride
        const rideRef = doc(db, "rides", winner.rideId)
        const rideSnap = await transaction.get(rideRef)
        if (!rideSnap.exists()) return
        const rideData = rideSnap.data()

        const newAvailableSeats = Math.max(0, (rideData.availableSeats || 1) - winner.seatsRequested)
        const newRideStatus = newAvailableSeats === 0 ? "full" : "active"

        const requesterProfile = await userService.getUserProfile(winner.requesterId)
        const currentPassengers: any[] = Array.isArray(rideData.acceptedPassengers) ? rideData.acceptedPassengers : []
        const passengerSnapshot = {
          uid: winner.requesterId,
          name: requesterProfile?.name || "Passenger",
          college: requesterProfile?.college || "",
          department: requesterProfile?.department || "",
          year: requesterProfile?.year || "",
          verified: !!requesterProfile?.collegeVerified,
          pickupLocation: (winner as any).pickupLocation || null,
          pickupDistanceMeters: (winner as any).pickupDistanceMeters || null,
          joinedAt: new Date().toISOString()
        }

        const updatedPassengers = [
          ...currentPassengers.filter((p: any) => p.uid !== winner.requesterId),
          passengerSnapshot
        ]

        // Atomic writes inside transaction
        transaction.update(rideRef, {
          availableSeats: newAvailableSeats,
          status: newRideStatus,
          acceptedPassengers: updatedPassengers,
          updatedAt: serverTimestamp()
        })

        transaction.update(doc(db, "rideRequests", winner.id!), {
          status: "accepted",
          updatedAt: serverTimestamp()
        })

        transaction.update(doc(db, "rideRequests", loser.id!), {
          status: "cancelled",
          updatedAt: serverTimestamp()
        })

        winningRideId = winner.rideId
      })

      if (winningRideId) {
        notificationService.resolveUserRequestNotifications(reqAId).catch(() => {})
        notificationService.resolveUserRequestNotifications(reqBId).catch(() => {})
      }

      return { success: true, winningRideId }
    } catch (e: any) {
      console.error("[autoConsolidateMutualRequests] Failed transaction:", e)
      return { success: false }
    }
  },

  async getRequestById(requestId: string): Promise<RideRequest | null> {
    try {
      const docRef = doc(db, "rideRequests", requestId)
      const docSnap = await getDoc(docRef)
      if (docSnap.exists()) {
        return { id: docSnap.id, ...docSnap.data() } as RideRequest
      }
      return null
    } catch (e) {
      return null
    }
  },

  async getUserRequestForRide(rideId: string, requesterId: string): Promise<RideRequest | null> {
    const q = query(
      collection(db, "rideRequests"),
      where("rideId", "==", rideId),
      where("requesterId", "==", requesterId)
    )
    const snap = await getDocs(q)
    if (!snap.empty) {
      const docs = snap.docs.map(doc => ({ id: doc.id, ...doc.data() } as RideRequest))
      const active = docs.find(r => r.status === "pending" || r.status === "accepted")
      return active || docs[0]
    }
    return null
  },

  async getMyRequests(requesterId: string): Promise<RideRequest[]> {
    const q = query(
      collection(db, "rideRequests"),
      where("requesterId", "==", requesterId)
    )
    const snap = await getDocs(q)
    return snap.docs.map(doc => ({ id: doc.id, ...doc.data() } as RideRequest))
  },

  async getRideRequests(rideId: string): Promise<RideRequest[]> {
    const q = query(
      collection(db, "rideRequests"),
      where("rideId", "==", rideId)
    )
    const snap = await getDocs(q)
    return snap.docs.map(doc => ({ id: doc.id, ...doc.data() } as RideRequest))
  },

  async getAcceptedRideRequests(rideId: string): Promise<RideRequest[]> {
    const q = query(
      collection(db, "rideRequests"),
      where("rideId", "==", rideId),
      where("status", "==", "accepted")
    )
    const snap = await getDocs(q)
    return snap.docs.map(doc => ({ id: doc.id, ...doc.data() } as RideRequest))
  },

  async rejectRideRequest(requestId: string, approverId: string): Promise<{ success: boolean; message: string }> {
    try {
      const docRef = doc(db, "rideRequests", requestId)
      const docSnap = await getDoc(docRef)
      if (!docSnap.exists()) return { success: false, message: "Request not found." }

      const reqData = docSnap.data() as RideRequest
      if (reqData.status !== "pending") return { success: false, message: "Request is no longer pending." }

      const rideDoc = await getDoc(doc(db, "rides", reqData.rideId))
      if (!rideDoc.exists()) return { success: false, message: "Ride not found." }
      const rideData = rideDoc.data()

      const isHost = rideData.ownerId === approverId
      const currentPassengers: any[] = Array.isArray(rideData.acceptedPassengers) ? rideData.acceptedPassengers : []
      const isAcceptedPassenger = currentPassengers.some((p: any) => (p.uid || p.requesterId) === approverId)

      if (!isHost && !isAcceptedPassenger) {
        return { success: false, message: "Permission denied." }
      }

      await updateDoc(docRef, {
        status: "rejected",
        rejectedAt: serverTimestamp(),
        updatedAt: serverTimestamp()
      })
      await updateDoc(doc(db, "rideContacts", requestId), {
        status: "rejected",
        updatedAt: serverTimestamp()
      }).catch(() => {})

      const approverProfile = await userService.getUserProfile(approverId)

      notificationService.createNotification({
        userId: reqData.requesterId,
        type: "request_rejected",
        title: "Ride request rejected",
        message: `Your request for the ride from ${rideData.from} to ${rideData.to} was rejected.`,
        rideId: reqData.rideId,
        rideRequestId: requestId,
        actorId: approverId,
        actorSnapshot: approverProfile ? {
          name: approverProfile.name,
          college: approverProfile.college,
          department: approverProfile.department,
          year: approverProfile.year,
          verified: approverProfile.collegeVerified
        } : undefined,
        rideSnapshot: {
          from: rideData.from,
          to: rideData.to,
          date: rideData.date,
          time: rideData.departureTime,
          seats: reqData.seatsRequested
        }
      }).catch(console.error)

      return { success: true, message: "Request rejected successfully." }
    } catch (e: any) {
      console.error(e)
      return { success: false, message: "Failed to reject request." }
    }
  },

  async acceptRideRequest(requestId: string, approverId: string): Promise<{ success: boolean; message: string }> {
    try {
      const reqRef = doc(db, "rideRequests", requestId)
      let notifyData: any = null

      let requesterProfile: UserProfile | null = null
      let hostPhone = ""
      let hostProfile: UserProfile | null = null
      const initialReqSnap = await getDoc(reqRef)
      if (initialReqSnap.exists()) {
        const reqInitData = initialReqSnap.data() as RideRequest
        try {
          requesterProfile = await userService.getUserProfile(reqInitData.requesterId)
        } catch (e) {}
        try {
          const hostPrivSnap = await getDoc(doc(db, "users", approverId, "private", "contact")).catch(() => null)
          hostPhone = (hostPrivSnap?.exists() && hostPrivSnap.data()?.phone) ? hostPrivSnap.data().phone : ""
          if (!hostPhone) {
            // Fallback for legacy accounts
            const hDoc = await getDoc(doc(db, "users", approverId)).catch(() => null)
            hostPhone = hDoc?.exists() ? (hDoc.data()?.phone || "") : ""
            if (hostPhone) {
              setDoc(doc(db, "users", approverId, "private", "contact"), {
                uid: approverId,
                phone: hostPhone,
                updatedAt: serverTimestamp()
              }, { merge: true }).catch(() => {})
            }
          }
          hostProfile = await userService.getUserProfile(approverId)
        } catch (e) {}
      }

      await runTransaction(db, async (transaction) => {
        const reqDoc = await transaction.get(reqRef)
        if (!reqDoc.exists()) throw new Error("Request not found.")
        const reqData = reqDoc.data() as RideRequest

        if (reqData.seatsRequested <= 0) throw new Error("Invalid request.")

        const rideRef = doc(db, "rides", reqData.rideId)
        const rideDoc = await transaction.get(rideRef)
        if (!rideDoc.exists()) throw new Error("Ride not found.")
        const rideData = rideDoc.data()

        const isHost = rideData.ownerId === approverId
        const currentPassengers: any[] = Array.isArray(rideData.acceptedPassengers) ? rideData.acceptedPassengers : []
        const isAcceptedPassenger = currentPassengers.some((p: any) => (p.uid || p.requesterId) === approverId)

        if (!isHost && !isAcceptedPassenger) {
          throw new Error("Permission denied for ride.")
        }
        const currentStatus = (rideData.status || "").toLowerCase()
        if (currentStatus === "full" || (rideData.availableSeats !== undefined && rideData.availableSeats < reqData.seatsRequested)) {
          throw new Error("There are not enough seats available for this request.")
        }
        if (currentStatus !== "active" && currentStatus !== "open") {
          throw new Error("Ride is no longer active.")
        }
        if (reqData.status !== "pending") throw new Error("Request is no longer pending.")

        const newAvailableSeats = rideData.availableSeats - reqData.seatsRequested
        const newRideStatus = newAvailableSeats === 0 ? "full" : "active"

        const passengerSnapshot = {
          uid: reqData.requesterId,
          name: requesterProfile?.name || "Passenger",
          college: requesterProfile?.college || "",
          department: requesterProfile?.department || "",
          year: requesterProfile?.year || "",
          verified: !!requesterProfile?.collegeVerified,
          pickupLocation: (reqData as any).pickupLocation || null,
          pickupDistanceMeters: (reqData as any).pickupDistanceMeters || null,
          joinedAt: new Date().toISOString()
        }

        const updatedPassengers = [
          ...currentPassengers.filter((p: any) => p.uid !== reqData.requesterId),
          passengerSnapshot
        ]

        transaction.update(rideRef, {
          availableSeats: newAvailableSeats,
          status: newRideStatus,
          acceptedPassengers: updatedPassengers,
          updatedAt: serverTimestamp()
        })

        transaction.update(reqRef, {
          status: "accepted",
          updatedAt: serverTimestamp()
        })

        // DPDPA & Privacy: Securely exchange contact info via rideContacts
        const contactRef = doc(db, "rideContacts", requestId)
        transaction.set(contactRef, {
          requestId,
          rideId: reqData.rideId,
          hostId: reqData.rideOwnerId,
          passengerId: reqData.requesterId,
          passengerName: requesterProfile?.name || "Passenger",
          hostPhone: hostPhone || "",
          hostName: hostProfile?.name || "Host",
          status: "accepted",
          acceptedAt: serverTimestamp()
        }, { merge: true })

        notifyData = {
          requesterId: reqData.requesterId,
          seatsRequested: reqData.seatsRequested,
          from: rideData.from,
          to: rideData.to,
          date: rideData.date,
          time: rideData.departureTime,
          rideId: reqData.rideId,
          rideOwnerId: rideData.ownerId,
          isFull: newRideStatus === "full",
          existingPassengers: currentPassengers
        }
      })

      if (notifyData) {
        const approverProfile = await userService.getUserProfile(approverId)
        const newPassengerName = requesterProfile?.name || "A new passenger"

        // 1. Notify the newly accepted requester
        notificationService.createNotification({
          userId: notifyData.requesterId,
          type: "request_accepted",
          title: "Ride request accepted",
          message: `Your request for the ride from ${notifyData.from} to ${notifyData.to} has been accepted.`,
          rideId: notifyData.rideId,
          rideRequestId: requestId,
          actorId: approverId,
          actorSnapshot: approverProfile ? {
            name: approverProfile.name,
            college: approverProfile.college,
            department: approverProfile.department,
            year: approverProfile.year,
            verified: approverProfile.collegeVerified
          } : undefined,
          rideSnapshot: {
            from: notifyData.from,
            to: notifyData.to,
            date: notifyData.date,
            time: notifyData.time,
            seats: notifyData.seatsRequested
          }
        }).catch(console.error)

        // 2. Notify all existing pool members (Host + existing passengers except actor and requester)
        const allMembers = [
          { uid: notifyData.rideOwnerId },
          ...(Array.isArray(notifyData.existingPassengers) ? notifyData.existingPassengers : [])
        ]
        allMembers.forEach((member: any) => {
          const mUid = member.uid || member.requesterId
          if (mUid && mUid !== notifyData.requesterId && mUid !== approverId) {
            notificationService.createNotification({
              userId: mUid,
              type: "request_accepted",
              title: "New co-rider joined your pool!",
              message: `${newPassengerName} has joined your ride pool from ${notifyData.from} to ${notifyData.to}.`,
              rideId: notifyData.rideId,
              rideRequestId: requestId,
              actorId: notifyData.requesterId,
              actorSnapshot: requesterProfile ? {
                name: requesterProfile.name,
                college: requesterProfile.college,
                department: requesterProfile.department,
                year: requesterProfile.year,
                verified: requesterProfile.collegeVerified
              } : undefined,
              rideSnapshot: {
                from: notifyData.from,
                to: notifyData.to,
                date: notifyData.date,
                time: notifyData.time,
                seats: notifyData.seatsRequested
              }
            }).catch(console.error)
          }
        })

        // Auto-resolve prior ride_request & ride_match_found notifications for all pool members & requester
        allMembers.forEach((member: any) => {
          const mUid = member.uid || member.requesterId
          if (mUid) {
            notificationService.resolveUserRequestNotifications(mUid, requestId, notifyData.rideId).catch(console.error)
          }
        })
        notificationService.resolveUserRequestNotifications(notifyData.requesterId, requestId, notifyData.rideId).catch(console.error)

        // If ride has reached capacity (full), auto-pool remaining pending requests into peer cab sharing groups
        if (notifyData.isFull) {
          try {
            const pendingQuery = query(
              collection(db, "rideRequests"),
              where("rideId", "==", notifyData.rideId),
              where("status", "==", "pending")
            )
            const pendingSnap = await getDocs(pendingQuery)
            if (!pendingSnap.empty) {
              const rejectedReqs = pendingSnap.docs.map((d) => ({ id: d.id, ...d.data() } as RideRequest))
              // Mark remaining requests as rejected
              await Promise.all(
                pendingSnap.docs.map((d) => updateDoc(d.ref, { status: "rejected", updatedAt: serverTimestamp() }))
              )
              // Group into 4-passenger cab sharing pools
              cabPoolService.createCabPoolsFromRejectedRequests(
                notifyData.rideId,
                notifyData.from,
                notifyData.to,
                notifyData.date,
                notifyData.time,
                rejectedReqs
              ).catch(console.error)
            }
          } catch (poolErr) {
            console.warn("[acceptRideRequest] Auto cab-pooling warning:", poolErr)
          }
        }
      }

      return { success: true, message: "Request accepted successfully." }
    } catch (e: any) {
      console.error("Transaction failed: ", e)
      if (e?.code === "permission-denied" || e?.message?.includes("permission") || e?.message?.includes("Permission") || e?.message?.includes("insufficient permissions")) {
        return { success: false, message: "Permission denied." }
      }
      return { success: false, message: e.message || "Failed to accept request." }
    }
  },

  async cancelRideRequest(requestId: string, requesterId: string): Promise<{ success: boolean; message: string }> {
    try {
      const reqRef = doc(db, "rideRequests", requestId)
      let notifyData: any = null

      await runTransaction(db, async (transaction) => {
        const reqDoc = await transaction.get(reqRef)
        if (!reqDoc.exists()) throw new Error("Request not found.")
        const reqData = reqDoc.data() as RideRequest

        if (reqData.requesterId !== requesterId) throw new Error("Permission denied.")
        if (reqData.status === "cancelled" || reqData.status === "rejected") {
          throw new Error(`Request is already ${reqData.status}.`)
        }

        const wasAccepted = reqData.status === "accepted"

        const rideRef = doc(db, "rides", reqData.rideId)
        const rideDoc = await transaction.get(rideRef)
        if (rideDoc.exists()) {
          const rideData = rideDoc.data()

          if (wasAccepted) {
            const rawNewSeats = (rideData.availableSeats || 0) + reqData.seatsRequested
            const maxSeats = rideData.totalSeats || rideData.seats || rawNewSeats
            const newAvailableSeats = Math.min(maxSeats, rawNewSeats)
            const newRideStatus = rideData.status === "full" ? "active" : rideData.status

            const currentPassengers: any[] = Array.isArray(rideData.acceptedPassengers) ? rideData.acceptedPassengers : []
            const updatedPassengers = currentPassengers.filter((p: any) => (p.uid || p.passengerId || p.requesterId) !== requesterId)

            transaction.update(rideRef, {
              availableSeats: newAvailableSeats,
              status: newRideStatus,
              acceptedPassengers: updatedPassengers,
              updatedAt: serverTimestamp()
            })
          }

          notifyData = {
            rideOwnerId: reqData.rideOwnerId,
            from: rideData.from,
            to: rideData.to,
            date: rideData.date,
            time: rideData.departureTime,
            rideId: reqData.rideId,
            seatsRequested: reqData.seatsRequested
          }
        }

        transaction.update(reqRef, {
          status: "cancelled",
          updatedAt: serverTimestamp()
        })
        transaction.set(doc(db, "rideContacts", requestId), {
          status: "cancelled",
          updatedAt: serverTimestamp()
        }, { merge: true })
      })

      if (notifyData) {
        const requesterProfile = await userService.getUserProfile(requesterId)

        notificationService.createNotification({
          userId: notifyData.rideOwnerId,
          type: "request_cancelled",
          title: "Ride request cancelled",
          message: `${requesterProfile?.name || "Passenger"} cancelled their request for your ride from ${notifyData.from} to ${notifyData.to}.`,
          rideId: notifyData.rideId,
          rideRequestId: requestId,
          actorId: requesterId,
          actorSnapshot: requesterProfile ? JSON.parse(JSON.stringify({
            name: requesterProfile.name || "Passenger",
            college: requesterProfile.college || "",
            department: requesterProfile.department || "",
            verified: !!requesterProfile.collegeVerified
          })) : undefined,
          rideSnapshot: JSON.parse(JSON.stringify({
            from: notifyData.from || "",
            to: notifyData.to || "",
            date: notifyData.date || "",
            time: notifyData.time || "",
            seats: notifyData.seatsRequested
          }))
        }).catch(console.error)
      }

      return { success: true, message: "Request cancelled successfully." }
    } catch (e: any) {
      console.error("Cancel request failed: ", e)
      if (e?.code === "permission-denied" || e?.message?.includes("permission") || e?.message?.includes("Permission") || e?.message?.includes("insufficient permissions")) {
        return { success: false, message: "Permission denied." }
      }
      return { success: false, message: e.message || "Failed to cancel request." }
    }
  }
}
