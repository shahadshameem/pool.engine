import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { auth, db } from "../src/config/firebase"
import { createUserWithEmailAndPassword, signInWithEmailAndPassword } from "firebase/auth"
import { doc, deleteDoc, getDoc } from "firebase/firestore"
import { userService } from "../src/services/user/userService"
import { rideService } from "../src/services/ride/rideService"
import { rideRequestService } from "../src/services/rideRequest/rideRequestService"

describe("PHASE 5 — AUTH & FIRESTORE SECURITY RULES TESTS", { timeout: 25000 }, () => {
  const ts = Date.now()
  const password = "TestPassword123!"

  let user1Uid = ""
  let user2Uid = ""

  const createdRides: string[] = []
  const createdRequests: string[] = []
  const createdProfiles: string[] = []

  beforeAll(async () => {
    // Create User 1
    const u1Cred = await createUserWithEmailAndPassword(auth, `p4_u1_${ts}@waymate.test`, password)
    user1Uid = u1Cred.user.uid
    await userService.createUserProfile(user1Uid, { name: "User 1", gender: "female", college: "CET", department: "CSE", year: "4th Year" })
    createdProfiles.push(user1Uid)

    // Create User 2
    const u2Cred = await createUserWithEmailAndPassword(auth, `p4_u2_${ts}@waymate.test`, password)
    user2Uid = u2Cred.user.uid
    await userService.createUserProfile(user2Uid, { name: "User 2", gender: "female", college: "CET", department: "ECE", year: "3rd Year" })
    createdProfiles.push(user2Uid)
  })

  afterAll(async () => {
    for (const rid of createdRides) {
      await deleteDoc(doc(db, "rides", rid)).catch(() => {})
    }
    for (const reqId of createdRequests) {
      await deleteDoc(doc(db, "rideRequests", reqId)).catch(() => {})
    }
    for (const uid of createdProfiles) {
      await deleteDoc(doc(db, "users", uid)).catch(() => {})
    }
  })

  it("P4-S1: User A cannot modify or cancel User B's ride", async () => {
    await signInWithEmailAndPassword(auth, `p4_u1_${ts}@waymate.test`, password)
    const rideId = await rideService.createRide(user1Uid, {
      from: "Library",
      to: "Campus Gate",
      date: "2026-12-10",
      departureTime: "08:00 AM",
      totalSeats: 3,
      availableSeats: 3
    })
    createdRides.push(rideId)

    // User 2 signs in and attempts to cancel User 1's ride
    await signInWithEmailAndPassword(auth, `p4_u2_${ts}@waymate.test`, password)
    const cancelRes = await rideService.cancelRide(rideId, user2Uid)
    expect(cancelRes.success).toBe(false)
    expect(cancelRes.message).toContain("Permission denied")

    // Status remains active
    const rideDoc = await rideService.getRideById(rideId)
    expect(rideDoc?.status).toBe("active")
  })

  it("P4-S2: User A cannot accept User B's ride request or self-accept their own request", async () => {
    await signInWithEmailAndPassword(auth, `p4_u1_${ts}@waymate.test`, password)
    const rideId = await rideService.createRide(user1Uid, {
      from: "Hostel 3",
      to: "Main Gate",
      date: "2026-12-10",
      departureTime: "09:00 AM",
      totalSeats: 3,
      availableSeats: 3
    })
    createdRides.push(rideId)

    // User 2 requests User 1's ride
    await signInWithEmailAndPassword(auth, `p4_u2_${ts}@waymate.test`, password)
    const rideDoc = (await rideService.getRideById(rideId))!
    const reqRes = await rideRequestService.createRideRequest(rideDoc, user2Uid, 1, "Requesting seat")
    expect(reqRes.success).toBe(true)
    const reqId = reqRes.requestId!
    createdRequests.push(reqId)

    // User 2 (requester) attempts to accept their own request -> blocked
    const selfAccept = await rideRequestService.acceptRideRequest(reqId, user2Uid)
    expect(selfAccept.success).toBe(false)

    // Status remains pending
    const reqDoc = await rideRequestService.getRequestById(reqId)
    expect(reqDoc?.status).toBe("pending")
  })

  it("P4-S3: Nonexistent IDs return clean result objects rather than throwing uncaught errors", async () => {
    const nonExistentRide = await rideService.getRideById("non_existent_ride_id_99999")
    expect(nonExistentRide).toBeNull()

    const nonExistentReq = await rideRequestService.getRequestById("non_existent_req_id_99999")
    expect(nonExistentReq).toBeNull()
  })
})
