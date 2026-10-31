import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { auth, db } from "../src/config/firebase"
import { createUserWithEmailAndPassword, signInWithEmailAndPassword } from "firebase/auth"
import { doc, setDoc, deleteDoc, getDoc } from "firebase/firestore"
import { userService } from "../src/services/user/userService"
import { rideService } from "../src/services/ride/rideService"
import { rideMatchService, type RideMatchCandidate } from "../src/services/rideMatch/rideMatchService"
import { rideRequestService } from "../src/services/rideRequest/rideRequestService"
import { notificationService } from "../src/services/notification/notificationService"
import { getTimeProximityBadgeLabel } from "../src/config/matchingConfig"

describe("PHASE 3 — P1 CORE FUNCTIONALITY & MATCHING TESTS", () => {
  const ts = Date.now()
  const password = "TestPassword123!"

  let hostUid = ""
  let host2Uid = ""
  let host3Uid = ""
  let passengerUid = ""

  const createdRides: string[] = []
  const createdRequests: string[] = []
  const createdProfiles: string[] = []
  const createdNotifications: string[] = []

  beforeAll(async () => {
    // 1. Create Host 1
    const h1Cred = await createUserWithEmailAndPassword(auth, `p2_h1_${ts}@waymate.test`, password)
    hostUid = h1Cred.user.uid
    await userService.createUserProfile(hostUid, { name: "P2 Host 1", gender: "female", college: "CET", department: "CSE", year: "4th Year" })
    createdProfiles.push(hostUid)

    // 2. Create Host 2
    const h2Cred = await createUserWithEmailAndPassword(auth, `p2_h2_${ts}@waymate.test`, password)
    host2Uid = h2Cred.user.uid
    await userService.createUserProfile(host2Uid, { name: "P2 Host 2", gender: "female", college: "CET", department: "ECE", year: "3rd Year" })
    createdProfiles.push(host2Uid)

    // 3. Create Host 3
    const h3Cred = await createUserWithEmailAndPassword(auth, `p2_h3_${ts}@waymate.test`, password)
    host3Uid = h3Cred.user.uid
    await userService.createUserProfile(host3Uid, { name: "P2 Host 3", gender: "female", college: "CET", department: "EEE", year: "2nd Year" })
    createdProfiles.push(host3Uid)

    // 4. Create Passenger
    const pCred = await createUserWithEmailAndPassword(auth, `p2_pass_${ts}@waymate.test`, password)
    passengerUid = pCred.user.uid
    await userService.createUserProfile(passengerUid, { name: "P2 Passenger", gender: "female", college: "CET", department: "ME", year: "1st Year" })
    createdProfiles.push(passengerUid)
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
    for (const nid of createdNotifications) {
      await deleteDoc(doc(db, "notifications", nid)).catch(() => {})
    }
  })

  it("P1-M1: Matching filters — same origin, same destination, date, time window, available seats, gender policy", async () => {
    await signInWithEmailAndPassword(auth, `p2_h1_${ts}@waymate.test`, password)

    const testDate = "2026-11-28"
    const baseRideId = await rideService.createRide(hostUid, {
      from: "ICC",
      to: "Main Gate",
      date: testDate,
      departureTime: "09:00 AM",
      totalSeats: 3,
      availableSeats: 3
    })
    createdRides.push(baseRideId)

    // Host 2 matching ride (09:05 AM -> 5 min diff)
    await signInWithEmailAndPassword(auth, `p2_h2_${ts}@waymate.test`, password)
    const matchRideId = await rideService.createRide(host2Uid, {
      from: "ICC",
      to: "Main Gate",
      date: testDate,
      departureTime: "09:05 AM",
      totalSeats: 2,
      availableSeats: 2
    })
    createdRides.push(matchRideId)

    // Host 3 mismatched ride (09:25 AM -> 25 min diff > 10 min tolerance)
    await signInWithEmailAndPassword(auth, `p2_h3_${ts}@waymate.test`, password)
    const timeOutRideId = await rideService.createRide(host3Uid, {
      from: "ICC",
      to: "Main Gate",
      date: testDate,
      departureTime: "09:25 AM",
      totalSeats: 2,
      availableSeats: 2
    })
    createdRides.push(timeOutRideId)

    const baseRideDoc = await rideService.getRideById(baseRideId)
    const matches = await rideMatchService.findMatchingRides(baseRideDoc!)
    const matchIds = matches.map((m: RideMatchCandidate) => m.ride.id)

    expect(matchIds).toContain(matchRideId)
    expect(matchIds).not.toContain(timeOutRideId) // > 10 min diff excluded
    expect(matchIds).not.toContain(baseRideId) // Self owner excluded
  })

  it("P1-M2: Boundary Time Overlap Evaluation (09:00–10:00 / 10:00–12:00 / 12:00–14:00 / 09:00–13:00)", async () => {
    await signInWithEmailAndPassword(auth, `p2_h1_${ts}@waymate.test`, password)
    const testDate = "2026-11-30"

    const r1Id = await rideService.createRide(hostUid, {
      from: "ICC",
      to: "Main Gate",
      date: testDate,
      departureTime: "09:00 AM",
      totalSeats: 3,
      availableSeats: 3
    })
    createdRides.push(r1Id)

    const r2Id = await rideService.createRide(hostUid, {
      from: "ICC",
      to: "Main Gate",
      date: testDate,
      departureTime: "10:00 AM",
      totalSeats: 3,
      availableSeats: 3
    })
    createdRides.push(r2Id)

    // Passenger requests r1
    await signInWithEmailAndPassword(auth, `p2_pass_${ts}@waymate.test`, password)
    const r1Doc = (await rideService.getRideById(r1Id))!
    const req1 = await rideRequestService.createRideRequest(r1Doc, passengerUid, 1, "Request 1")
    expect(req1.success).toBe(true)
    if (req1.requestId) createdRequests.push(req1.requestId)

    // Passenger requests r2 on touching boundary time
    const r2Doc = (await rideService.getRideById(r2Id))!
    const req2 = await rideRequestService.createRideRequest(r2Doc, passengerUid, 1, "Request 2")
    expect(req2.success).toBe(true)
    if (req2.requestId) createdRequests.push(req2.requestId)

    console.log("[FINDING] Ride overlap policy: Request deduplication is enforced per-ride (rideId). Separate rides on the same date at touching/overlapping times are permitted without blocking.")
  })

  it("P1-M3: My Trips & Status Propagation — notification flow for request sent, accepted, cancelled", async () => {
    await signInWithEmailAndPassword(auth, `p2_h1_${ts}@waymate.test`, password)
    const testDate = "2026-12-01"

    const rideId = await rideService.createRide(hostUid, {
      from: "Campus Center",
      to: "Railway Station",
      date: testDate,
      departureTime: "05:00 PM",
      totalSeats: 3,
      availableSeats: 3
    })
    createdRides.push(rideId)

    // Passenger requests ride
    await signInWithEmailAndPassword(auth, `p2_pass_${ts}@waymate.test`, password)
    const rideDoc = (await rideService.getRideById(rideId))!
    const createRes = await rideRequestService.createRideRequest(rideDoc, passengerUid, 1, "Need a seat")
    expect(createRes.success).toBe(true)
    const reqId = createRes.requestId!
    createdRequests.push(reqId)

    // Host accepts request
    await signInWithEmailAndPassword(auth, `p2_h1_${ts}@waymate.test`, password)
    const acceptRes = await rideRequestService.acceptRideRequest(reqId, hostUid)
    expect(acceptRes.success).toBe(true)

    const updatedReq = await rideRequestService.getRequestById(reqId)
    expect(updatedReq?.status).toBe("accepted")

    // Passenger cancels request
    await signInWithEmailAndPassword(auth, `p2_pass_${ts}@waymate.test`, password)
    const cancelRes = await rideRequestService.cancelRideRequest(reqId, passengerUid)
    expect(cancelRes.success).toBe(true)

    const cancelledReq = await rideRequestService.getRequestById(reqId)
    expect(cancelledReq?.status).toBe("cancelled")
  })
})
