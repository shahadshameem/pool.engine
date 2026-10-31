import { collection, query, where, getDocs, doc, updateDoc } from "firebase/firestore"
import { db } from "../../config/firebase"
import type { Ride } from "../ride/rideService"
import { userService, type UserProfile } from "../user/userService"
import { FIXED_LOCATIONS } from "../../config/locations"
import {
  RIDE_MATCH_CONFIG,
  calculateHaversineDistance,
  calculateTimeDifferenceMinutes,
  isRideExpired
} from "../../config/matchingConfig"
import { notificationService } from "../notification/notificationService"

export interface RideMatchCandidate {
  ride: Ride
  hostProfile?: UserProfile | null
  originDistanceKm: number
  destinationDistanceKm: number
  timeDifferenceMinutes: number
}

/**
 * Resolves latitude and longitude for a given location name or location object.
 * Checks embedded coordinates first, then falls back to matching predefined FIXED_LOCATIONS.
 */
function resolveCoordinates(
  name?: string,
  locObj?: { latitude?: number; longitude?: number }
): { latitude: number; longitude: number } | null {
  if (locObj?.latitude && locObj?.longitude) {
    return { latitude: locObj.latitude, longitude: locObj.longitude }
  }
  if (name) {
    const norm = name.trim().toLowerCase()
    const found = FIXED_LOCATIONS.find(loc => {
      const locName = loc.name.toLowerCase()
      const locAddr = loc.address.toLowerCase()
      const locId = loc.id.toLowerCase()
      return locName === norm || locAddr === norm || locId === norm || norm.includes(locName) || locName.includes(norm)
    })
    if (found?.latitude && found?.longitude) {
      return { latitude: found.latitude, longitude: found.longitude }
    }
  }
  return null
}

export const rideMatchService = {
  /**
   * Finds all active candidate rides matching the given ride's date, genderPolicy, origin, destination, and departure time.
   * Performs bounded Firestore query followed by in-memory spatial/temporal distance checks and departure expiration check.
   */
  async findMatchingRides(newRide: Ride, excludeOwnerIds?: string[]): Promise<RideMatchCandidate[]> {
    if (!newRide.date || !newRide.ownerId) {
      console.warn("[RideMatchEngine] Missing required ride properties (date/ownerId) for matching", newRide)
      return []
    }

    const excludeSet = new Set<string>(excludeOwnerIds || [])

    // Derive genderPolicy if missing from ride object
    let targetGenderPolicy = newRide.genderPolicy
    if (!targetGenderPolicy) {
      try {
        const ownerProfile = await userService.getUserProfile(newRide.ownerId)
        targetGenderPolicy = ownerProfile?.gender === "female" ? "female_only" : "any"
      } catch (e) {}
    }

    try {
      const ridesRef = collection(db, "rides")

      // 1. Bounded candidate query
      const q = targetGenderPolicy ? query(
        ridesRef,
        where("status", "==", "active"),
        where("date", "==", newRide.date),
        where("genderPolicy", "==", targetGenderPolicy)
      ) : query(
        ridesRef,
        where("status", "==", "active"),
        where("date", "==", newRide.date)
      )

      const snap = await getDocs(q)

      const candidates: RideMatchCandidate[] = []
      const newOriginCoords = resolveCoordinates(newRide.from, newRide.fromLocation)
      const newDestCoords = resolveCoordinates(newRide.to, newRide.toLocation)

      // Retrieve all active requests sent by newRide.ownerId to avoid re-matching already requested rides
      const alreadyRequestedRideIds = new Set<string>()
      try {
        const qReqs = query(
          collection(db, "rideRequests"),
          where("requesterId", "==", newRide.ownerId)
        )
        const reqsSnap = await getDocs(qReqs)
        reqsSnap.docs.forEach(d => {
          const reqData = d.data()
          if (reqData.rideId && (reqData.status === "pending" || reqData.status === "accepted")) {
            alreadyRequestedRideIds.add(reqData.rideId)
          }
        })
      } catch (e) {
        console.warn("[RideMatchEngine] Failed to fetch existing rideRequests for requester filter:", e)
      }

      for (const docSnap of snap.docs) {
        const candidateRide = { id: docSnap.id, ...docSnap.data() } as Ride

        // Exclude self, same owner, accepted passengers, rides without available seats, or expired rides
        if (newRide.id && candidateRide.id === newRide.id) continue
        if (candidateRide.ownerId === newRide.ownerId) continue
        if (excludeSet.has(candidateRide.ownerId)) continue
        if (!candidateRide.availableSeats || candidateRide.availableSeats < 1) continue
        if (isRideExpired(candidateRide.date, candidateRide.departureTime)) continue
        // Exclude candidate rides for which the user already sent an active request
        if (candidateRide.id && alreadyRequestedRideIds.has(candidateRide.id)) continue

        // 2. Spatial Origin Distance Check
        let originDistKm = 999
        const candOriginCoords = resolveCoordinates(candidateRide.from, candidateRide.fromLocation)

        if (newOriginCoords && candOriginCoords) {
          originDistKm = calculateHaversineDistance(
            newOriginCoords.latitude,
            newOriginCoords.longitude,
            candOriginCoords.latitude,
            candOriginCoords.longitude
          )
        } else {
          // String fallback
          const newFrom = newRide.from?.trim().toLowerCase() || ""
          const candFrom = candidateRide.from?.trim().toLowerCase() || ""
          if (newFrom && candFrom && (newFrom === candFrom || newFrom.includes(candFrom) || candFrom.includes(newFrom))) {
            originDistKm = 0
          }
        }

        if (originDistKm > RIDE_MATCH_CONFIG.MAX_ORIGIN_DISTANCE_KM) {
          continue
        }

        // 3. Spatial Destination Distance Check
        let destDistKm = 999
        const candDestCoords = resolveCoordinates(candidateRide.to, candidateRide.toLocation)

        if (newDestCoords && candDestCoords) {
          destDistKm = calculateHaversineDistance(
            newDestCoords.latitude,
            newDestCoords.longitude,
            candDestCoords.latitude,
            candDestCoords.longitude
          )
        } else {
          // String fallback
          const newTo = newRide.to?.trim().toLowerCase() || ""
          const candTo = candidateRide.to?.trim().toLowerCase() || ""
          if (newTo && candTo && (newTo === candTo || newTo.includes(candTo) || candTo.includes(newTo))) {
            destDistKm = 0
          }
        }

        if (destDistKm > RIDE_MATCH_CONFIG.MAX_DESTINATION_DISTANCE_KM) {
          continue
        }

        // 4. Temporal Departure Time Gap Check
        const timeDiffMinutes = calculateTimeDifferenceMinutes(
          newRide.departureTime,
          candidateRide.departureTime
        )

        if (timeDiffMinutes > RIDE_MATCH_CONFIG.MAX_DEPARTURE_TIME_DIFFERENCE_MINUTES) {
          continue
        }

        // 5. Fetch Host Profile
        let hostProfile: UserProfile | null = null
        try {
          hostProfile = await userService.getUserProfile(candidateRide.ownerId)
        } catch (e) {
          console.warn(`[RideMatchEngine] Could not fetch host profile for ${candidateRide.ownerId}:`, e)
        }

        candidates.push({
          ride: candidateRide,
          hostProfile,
          originDistanceKm: Math.round(originDistKm * 10) / 10,
          destinationDistanceKm: Math.round(destDistKm * 10) / 10,
          timeDifferenceMinutes: timeDiffMinutes
        })
      }

      // Sort by smallest time gap first, then smallest total spatial gap
      candidates.sort((a, b) => {
        if (a.timeDifferenceMinutes !== b.timeDifferenceMinutes) {
          return a.timeDifferenceMinutes - b.timeDifferenceMinutes
        }
        const totalDistA = a.originDistanceKm + a.destinationDistanceKm
        const totalDistB = b.originDistanceKm + b.destinationDistanceKm
        return totalDistA - totalDistB
      })

      return candidates
    } catch (error) {
      console.error("[RideMatchEngine] Failed to find matching rides:", error)
      return []
    }
  },

  /**
   * Triggers background match detection when a ride is created and sends ride_match_found notifications.
   * Tag rides with shared matchGroupId and notifies existing owners when a pool grows to 3+ rides.
   */
  async triggerMatchNotifications(newRide: Ride): Promise<void> {
    try {
      const matches = await this.findMatchingRides(newRide)
      if (matches.length === 0) {
        return
      }

      // Determine or assign shared matchGroupId
      let matchGroupId = newRide.matchGroupId
      if (!matchGroupId) {
        const existingCandidateGroup = matches.find(c => !!c.ride.matchGroupId)
        matchGroupId = existingCandidateGroup?.ride.matchGroupId || `pool_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`
      }

      // Tag new ride and candidate rides with matchGroupId (best-effort)
      if (newRide.id) {
        try {
          await updateDoc(doc(db, "rides", newRide.id), { matchGroupId })
        } catch (e) {}
      }
      for (const candidate of matches) {
        if (candidate.ride.id && candidate.ride.matchGroupId !== matchGroupId) {
          try {
            await updateDoc(doc(db, "rides", candidate.ride.id), { matchGroupId })
          } catch (e) {}
        }
      }

      const totalPoolSize = matches.length + 1
      const newHostProfile = await userService.getUserProfile(newRide.ownerId)
      const newHostActorSnapshot = newHostProfile ? {
        name: newHostProfile.name || "Host",
        college: newHostProfile.college || "",
        department: newHostProfile.department || "",
        verified: !!newHostProfile.collegeVerified
      } : undefined

      for (const candidate of matches) {
        const candHostActorSnapshot = candidate.hostProfile ? {
          name: candidate.hostProfile.name || "Host",
          college: candidate.hostProfile.college || "",
          department: candidate.hostProfile.department || "",
          verified: !!candidate.hostProfile.collegeVerified
        } : undefined

        // Notification 1: Sent to New Ride Owner (User A - active creator)
        await notificationService.createNotification({
          userId: newRide.ownerId,
          type: "ride_match_found",
          subType: "active_creator_match",
          title: totalPoolSize >= 3 ? `Ride Pool Available (${totalPoolSize} Rides Match)` : "Compatible Ride Offer Found",
          message: totalPoolSize >= 3
            ? `${candidate.hostProfile?.name || "A student"} and ${matches.length - 1} other student(s) have posted compatible rides from ${candidate.ride.from} to ${candidate.ride.to}.`
            : `${candidate.hostProfile?.name || "A student"} has posted a similar ride from ${candidate.ride.from} to ${candidate.ride.to}.`,
          rideId: newRide.id,
          matchedRideId: candidate.ride.id,
          actorId: candidate.ride.ownerId,
          actorSnapshot: candHostActorSnapshot,
          rideSnapshot: {
            from: candidate.ride.from,
            to: candidate.ride.to,
            date: candidate.ride.date,
            time: candidate.ride.departureTime,
            seats: candidate.ride.availableSeats
          }
        })

        // Notification 2: Sent to Existing Candidate Ride Owner (User B - passive host)
        const isGroupGrowth = totalPoolSize >= 3
        await notificationService.createNotification({
          userId: candidate.ride.ownerId,
          type: "ride_match_found",
          subType: "passive_host_notification",
          title: isGroupGrowth ? `Ride Pool Grew! (${totalPoolSize} Rides Now Match)` : "New Matching Ride Offer Posted",
          message: isGroupGrowth
            ? `${newHostProfile?.name || "A student"} just joined your ride pool from ${newRide.from} to ${newRide.to}. ${totalPoolSize} rides are now available in your matching pool.`
            : `${newHostProfile?.name || "A student"} just posted a compatible ride offer from ${newRide.from} to ${newRide.to}.`,
          rideId: candidate.ride.id,
          matchedRideId: newRide.id,
          actorId: newRide.ownerId,
          actorSnapshot: newHostActorSnapshot,
          rideSnapshot: {
            from: newRide.from,
            to: newRide.to,
            date: newRide.date,
            time: newRide.departureTime,
            seats: newRide.availableSeats
          }
        })
      }
    } catch (error) {
      console.error("[RideMatchEngine] Failed to trigger match notifications:", error)
    }
  }
}
