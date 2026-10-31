import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { rideService } from "../src/services/ride/rideService"
import { rideRequestService } from "../src/services/rideRequest/rideRequestService"
import { userService } from "../src/services/user/userService"
import { isRideExpired } from "../src/config/matchingConfig"
import { auth, db } from "../src/config/firebase"
import { signInWithEmailAndPassword, createUserWithEmailAndPassword, signOut } from "firebase/auth"
import { doc, deleteDoc } from "firebase/firestore"

describe("PHASE 1 — P0 TESTS", () => {
  const timestamp = Date.now()
  const phoneSuffix = String(timestamp).slice(-5)
  const hostEmail = `p0_host_${timestamp}@waymate.test`
  const p1Email = `p0_p1_${timestamp}@waymate.test`
  const p2Email = `p0_p2_${timestamp}@waymate.test`
  const testPassword = "TestPassword123!"

  let hostUid = ""
  let passenger1Uid = ""
  let passenger2Uid = ""

  const cleanupDocIds: { collection: string; id: string }[] = []

  beforeAll(async () => {
    // 1. Create Host User in Auth & Firestore via userService
    try {
      const hostCred = await createUserWithEmailAndPassword(auth, hostEmail, testPassword)
      hostUid = hostCred.user.uid
    } catch (e: any) {
      if (e.code === "auth/email-already-in-use") {
        const hostCred = await signInWithEmailAndPassword(auth, hostEmail, testPassword)
        hostUid = hostCred.user.uid
      } else {
        throw e
      }
    }
    await userService.createUserProfile(hostUid, {
      name: "P0 Test Host",
      phone: "+9198000" + phoneSuffix,
      college: "CET",
      department: "CSE",
      year: "4th Year",
      gender: "male"
    })
    cleanupDocIds.push({ collection: "users", id: hostUid })

    // 2. Create Passenger 1 User in Auth & Firestore
    try {
      const p1Cred = await createUserWithEmailAndPassword(auth, p1Email, testPassword)
      passenger1Uid = p1Cred.user.uid
    } catch (e: any) {
      if (e.code === "auth/email-already-in-use") {
        const p1Cred = await signInWithEmailAndPassword(auth, p1Email, testPassword)
        passenger1Uid = p1Cred.user.uid
      } else {
        throw e
      }
    }
    await userService.createUserProfile(passenger1Uid, {
      name: "P0 Passenger One",
      phone: "+9198001" + phoneSuffix,
      college: "CET",
      department: "ECE",
      year: "3rd Year",
      gender: "male"
    })
    cleanupDocIds.push({ collection: "users", id: passenger1Uid })

    // 3. Create Passenger 2 User in Auth & Firestore
    try {
      const p2Cred = await createUserWithEmailAndPassword(auth, p2Email, testPassword)
      passenger2Uid = p2Cred.user.uid
    } catch (e: any) {
      if (e.code === "auth/email-already-in-use") {
        const p2Cred = await signInWithEmailAndPassword(auth, p2Email, testPassword)
        passenger2Uid = p2Cred.user.uid
      } else {
        throw e
      }
    }
    await userService.createUserProfile(passenger2Uid, {
      name: "P0 Passenger Two",
      phone: "+9198002" + phoneSuffix,
      college: "CET",
      department: "EEE",
      year: "2nd Year",
      gender: "male"
    })
    cleanupDocIds.push({ collection: "users", id: passenger2Uid })
  }, 30000)

  afterAll(async () => {
    // Sign in as Host to clean up test documents
    try {
      await signInWithEmailAndPassword(auth, hostEmail, testPassword)
      for (const item of cleanupDocIds) {
        try {
          await deleteDoc(doc(db, item.collection, item.id))
        } catch (e) {}
      }
      await signOut(auth)
    } catch (e) {}
  })

  // --------------------------------------------------------------------------
  // TEST 1: Atomic Seat Acceptance (Loop 10x for race condition reliability)
  // --------------------------------------------------------------------------
  it("P0-1: Atomic seat acceptance under concurrent requests (10x loop)", async () => {
    for (let loop = 0; loop < 10; loop++) {
      // Host creates ride with availableSeats = 1
      await signInWithEmailAndPassword(auth, hostEmail, testPassword)
      const rideData = {
        ownerId: hostUid,
        from: "CET Trivandrum",
        to: "Technopark",
        date: "2026-11-15",
        departureTime: "09:00 AM",
        availableSeats: 1,
        totalSeats: 2,
        genderPolicy: "male" as const,
        status: "active" as const
      }

      const rideId = await rideService.createRide(hostUid, rideData)
      cleanupDocIds.push({ collection: "rides", id: rideId })
      const rideObj = { id: rideId, ...rideData }

      // Passenger 1 requests seat
      await signInWithEmailAndPassword(auth, p1Email, testPassword)
      const req1Res = await rideRequestService.createRideRequest(rideObj, passenger1Uid, 1, "Passenger 1 request")
      expect(req1Res.success).toBe(true)
      if (req1Res.requestId) cleanupDocIds.push({ collection: "rideRequests", id: req1Res.requestId })

      // Passenger 2 requests seat
      await signInWithEmailAndPassword(auth, p2Email, testPassword)
      const req2Res = await rideRequestService.createRideRequest(rideObj, passenger2Uid, 1, "Passenger 2 request")
      expect(req2Res.success).toBe(true)
      if (req2Res.requestId) cleanupDocIds.push({ collection: "rideRequests", id: req2Res.requestId })

      // Host concurrently accepts both requests
      await signInWithEmailAndPassword(auth, hostEmail, testPassword)
      const [accept1, accept2] = await Promise.all([
        rideRequestService.acceptRideRequest(req1Res.requestId!, hostUid),
        rideRequestService.acceptRideRequest(req2Res.requestId!, hostUid)
      ])

      const successCount = (accept1.success ? 1 : 0) + (accept2.success ? 1 : 0)
      const failCount = (!accept1.success ? 1 : 0) + (!accept2.success ? 1 : 0)

      expect(successCount).toBe(1)
      expect(failCount).toBe(1)

      // Verify ride state in Firestore
      const updatedRide = await rideService.getRideById(rideId)
      expect(updatedRide).not.toBeNull()
      expect(updatedRide!.availableSeats).toBe(0)
      expect(updatedRide!.availableSeats).toBeGreaterThanOrEqual(0)
      expect(updatedRide!.status).toBe("full")
      expect(updatedRide!.acceptedPassengers?.length).toBe(1)
    }
  }, 120000)

  // --------------------------------------------------------------------------
  // TEST 2: Self-Request Blocking
  // --------------------------------------------------------------------------
  it("P0-2: Prevents host from requesting a seat on their own ride", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, testPassword)
    const rideId = await rideService.createRide(hostUid, {
      from: "CET", to: "Kollam", date: "2026-11-20", departureTime: "10:00 AM", availableSeats: 3, totalSeats: 3
    })
    cleanupDocIds.push({ collection: "rides", id: rideId })

    const res = await rideRequestService.createRideRequest(
      { id: rideId, ownerId: hostUid, status: "active", availableSeats: 3, from: "CET", to: "Kollam", date: "2026-11-20", departureTime: "10:00 AM" },
      hostUid, 1, "Requesting my own ride"
    )

    expect(res.success).toBe(false)
    expect(res.message).toBe("You cannot request your own ride.")
  })

  // --------------------------------------------------------------------------
  // TEST 3: Duplicate Request Prevention
  // --------------------------------------------------------------------------
  it("P0-3: Prevents duplicate active requests from the same passenger", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, testPassword)
    const rideId = await rideService.createRide(hostUid, {
      from: "CET", to: "Airport", date: "2026-11-21", departureTime: "11:00 AM", availableSeats: 3, totalSeats: 3
    })
    cleanupDocIds.push({ collection: "rides", id: rideId })

    const rideObj = { id: rideId, ownerId: hostUid, status: "active", availableSeats: 3, from: "CET", to: "Airport", date: "2026-11-21", departureTime: "11:00 AM" }

    await signInWithEmailAndPassword(auth, p1Email, testPassword)
    const req1 = await rideRequestService.createRideRequest(rideObj, passenger1Uid, 1, "First request")
    expect(req1.success).toBe(true)
    if (req1.requestId) cleanupDocIds.push({ collection: "rideRequests", id: req1.requestId })

    const req2 = await rideRequestService.createRideRequest(rideObj, passenger1Uid, 1, "Duplicate request")
    expect(req2.success).toBe(false)
    expect(req2.message).toContain("already have a pending request")
  })

  // --------------------------------------------------------------------------
  // TEST 4: Past Date/Time Validation
  // --------------------------------------------------------------------------
  it("P0-4: Correctly identifies past dates and times as expired", () => {
    expect(isRideExpired("2020-01-01", "09:00 AM")).toBe(true)
    expect(isRideExpired("2099-12-31", "11:59 PM")).toBe(false)
  })

  // --------------------------------------------------------------------------
  // TEST 5: Passenger Double-Booking Prevention (Evaluating Current Behavior)
  // --------------------------------------------------------------------------
  it("P0-5: Evaluates passenger requesting separate rides at overlapping times", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, testPassword)
    const ride1Id = await rideService.createRide(hostUid, {
      from: "CET", to: "Technopark", date: "2026-10-25", departureTime: "09:00 AM", availableSeats: 2, totalSeats: 2
    })
    const ride2Id = await rideService.createRide(hostUid, {
      from: "CET", to: "Kollam", date: "2026-10-25", departureTime: "09:00 AM", availableSeats: 2, totalSeats: 2
    })
    cleanupDocIds.push({ collection: "rides", id: ride1Id }, { collection: "rides", id: ride2Id })

    await signInWithEmailAndPassword(auth, p1Email, testPassword)
    const r1 = await rideRequestService.createRideRequest(
      { id: ride1Id, ownerId: hostUid, status: "active", availableSeats: 2, from: "CET", to: "Technopark", date: "2026-10-25", departureTime: "09:00 AM" },
      passenger1Uid, 1, "Ride 1"
    )
    if (r1.requestId) cleanupDocIds.push({ collection: "rideRequests", id: r1.requestId })

    const r2 = await rideRequestService.createRideRequest(
      { id: ride2Id, ownerId: hostUid, status: "active", availableSeats: 2, from: "CET", to: "Kollam", date: "2026-10-25", departureTime: "09:00 AM" },
      passenger1Uid, 1, "Ride 2"
    )
    if (r2.requestId) cleanupDocIds.push({ collection: "rideRequests", id: r2.requestId })

    expect(r1.success).toBe(true)
    expect(r2.success).toBe(true)
  })

  // --------------------------------------------------------------------------
  // TEST 6 & 7: Seat Underflow & Overbooking Prevention
  // --------------------------------------------------------------------------
  it("P0-6 & P0-7: Overbooking & Seat Underflow Prevention", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, testPassword)
    const rideId = await rideService.createRide(hostUid, {
      from: "CET", to: "Lulu Mall", date: "2026-10-26", departureTime: "02:00 PM", availableSeats: 1, totalSeats: 1
    })
    cleanupDocIds.push({ collection: "rides", id: rideId })

    await signInWithEmailAndPassword(auth, p1Email, testPassword)
    const resOver = await rideRequestService.createRideRequest(
      { id: rideId, ownerId: hostUid, status: "active", availableSeats: 1, from: "CET", to: "Lulu Mall", date: "2026-10-26", departureTime: "02:00 PM" },
      passenger1Uid, 2, "Requesting 2 seats when only 1 available"
    )
    expect(resOver.success).toBe(false)
    expect(resOver.message).toBe("Not enough seats available.")

    const rideSnap = await rideService.getRideById(rideId)
    expect(rideSnap!.availableSeats).toBe(1)
    expect(rideSnap!.availableSeats).toBeGreaterThanOrEqual(0)
  })

  // --------------------------------------------------------------------------
  // TEST 8: Cancel/Accept Race Condition
  // --------------------------------------------------------------------------
  it("P0-8: Concurrent passenger cancellation and host acceptance", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, testPassword)
    const rideId = await rideService.createRide(hostUid, {
      from: "CET", to: "Kazhakkoottam", date: "2026-10-27", departureTime: "05:00 PM", availableSeats: 1, totalSeats: 2
    })
    cleanupDocIds.push({ collection: "rides", id: rideId })

    await signInWithEmailAndPassword(auth, p1Email, testPassword)
    const reqRes = await rideRequestService.createRideRequest(
      { id: rideId, ownerId: hostUid, status: "active", availableSeats: 1, from: "CET", to: "Kazhakkoottam", date: "2026-10-27", departureTime: "05:00 PM" },
      passenger1Uid, 1, "Race condition request"
    )
    expect(reqRes.success).toBe(true)
    const requestId = reqRes.requestId!
    cleanupDocIds.push({ collection: "rideRequests", id: requestId })

    const cancelPromise = rideRequestService.cancelRideRequest(requestId, passenger1Uid)
    const acceptPromise = rideRequestService.acceptRideRequest(requestId, hostUid)

    const [cancelRes, acceptRes] = await Promise.all([cancelPromise, acceptPromise])

    const oneSucceeded = (cancelRes.success && !acceptRes.success) || (!cancelRes.success && acceptRes.success)
    expect(oneSucceeded).toBe(true)

    const finalReq = await rideRequestService.getRequestById(requestId)
    expect(["accepted", "cancelled"]).toContain(finalReq?.status)

    const finalRide = await rideService.getRideById(rideId)
    expect(finalRide?.availableSeats).toBeGreaterThanOrEqual(0)
    expect(finalRide?.availableSeats).toBeLessThanOrEqual(2)
  })

  // --------------------------------------------------------------------------
  // TEST 9: Unauthorized Ride Modification
  // --------------------------------------------------------------------------
  it("P0-9: Prevents unauthorized user from modifying another host's ride", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, testPassword)
    const rideId = await rideService.createRide(hostUid, {
      from: "CET", to: "Kollam", date: "2026-10-28", departureTime: "08:00 AM", availableSeats: 3, totalSeats: 3
    })
    cleanupDocIds.push({ collection: "rides", id: rideId })

    await signInWithEmailAndPassword(auth, p1Email, testPassword)
    const res = await rideService.cancelRide(rideId, passenger1Uid)

    expect(res.success).toBe(false)
    expect(res.message).toBe("Permission denied.")

    // Verify original ride remains active
    const ride = await rideService.getRideById(rideId)
    expect(ride?.status).toBe("active")
  })

  // --------------------------------------------------------------------------
  // TEST 10: Unauthorized Request Modification
  // --------------------------------------------------------------------------
  it("P0-10: Prevents unauthorized user from accepting or modifying another user's request", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, testPassword)
    const rideId = await rideService.createRide(hostUid, {
      from: "CET", to: "Varkala", date: "2026-10-29", departureTime: "07:00 AM", availableSeats: 2, totalSeats: 2
    })
    cleanupDocIds.push({ collection: "rides", id: rideId })

    await signInWithEmailAndPassword(auth, p1Email, testPassword)
    const req = await rideRequestService.createRideRequest(
      { id: rideId, ownerId: hostUid, status: "active", availableSeats: 2, from: "CET", to: "Varkala", date: "2026-10-29", departureTime: "07:00 AM" },
      passenger1Uid, 1, "Request to Varkala"
    )
    expect(req.success).toBe(true)
    const requestId = req.requestId!
    cleanupDocIds.push({ collection: "rideRequests", id: requestId })

    await signInWithEmailAndPassword(auth, p2Email, testPassword)
    const unauthorizedAccept = await rideRequestService.acceptRideRequest(requestId, passenger2Uid)
    expect(unauthorizedAccept.success).toBe(false)
    expect(unauthorizedAccept.message).toBe("Permission denied.")

    const unauthorizedCancel = await rideRequestService.cancelRideRequest(requestId, passenger2Uid)
    expect(unauthorizedCancel.success).toBe(false)
    expect(unauthorizedCancel.message).toBe("Permission denied.")
  })

  // --------------------------------------------------------------------------
  // TEST 11: Invalid Ride / Request References
  // --------------------------------------------------------------------------
  it("P0-11: Gracefully handles invalid or nonexistent ride and request IDs", async () => {
    const fakeId = "nonexistent_ref_99999"

    const nullRide = await rideService.getRideById(fakeId)
    expect(nullRide).toBeNull()

    const nullReq = await rideRequestService.getRequestById(fakeId)
    expect(nullReq).toBeNull()

    const acceptFake = await rideRequestService.acceptRideRequest(fakeId, hostUid)
    expect(acceptFake.success).toBe(false)
    expect(["Request not found.", "Permission denied."]).toContain(acceptFake.message)

    const cancelFake = await rideRequestService.cancelRideRequest(fakeId, passenger1Uid)
    expect(cancelFake.success).toBe(false)
    expect(["Request not found.", "Permission denied."]).toContain(cancelFake.message)
  })

  // --------------------------------------------------------------------------
  // TEST 12: Request State Transition Validity
  // --------------------------------------------------------------------------
  it("P0-12: Enforces request state transition validity (cannot accept/reject non-pending requests)", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, testPassword)
    const rideId = await rideService.createRide(hostUid, {
      from: "CET", to: "Adoor", date: "2026-10-30", departureTime: "01:00 PM", availableSeats: 2, totalSeats: 2
    })
    cleanupDocIds.push({ collection: "rides", id: rideId })

    await signInWithEmailAndPassword(auth, p1Email, testPassword)
    const req = await rideRequestService.createRideRequest(
      { id: rideId, ownerId: hostUid, status: "active", availableSeats: 2, from: "CET", to: "Adoor", date: "2026-10-30", departureTime: "01:00 PM" },
      passenger1Uid, 1, "State transition test"
    )
    const requestId = req.requestId!
    cleanupDocIds.push({ collection: "rideRequests", id: requestId })

    await signInWithEmailAndPassword(auth, hostEmail, testPassword)
    const rejRes = await rideRequestService.rejectRideRequest(requestId, hostUid)
    expect(rejRes.success).toBe(true)

    const invalidAccept = await rideRequestService.acceptRideRequest(requestId, hostUid)
    expect(invalidAccept.success).toBe(false)
    expect(invalidAccept.message).toBe("Request is no longer pending.")

    const doubleRej = await rideRequestService.rejectRideRequest(requestId, hostUid)
    expect(doubleRej.success).toBe(false)
    expect(doubleRej.message).toBe("Request is no longer pending.")
  })

  // --------------------------------------------------------------------------
  // TEST 13: Cancelled Ride Cannot Receive New Requests
  // --------------------------------------------------------------------------
  it("P0-13: Prevents submitting new requests to a cancelled ride", async () => {
    await signInWithEmailAndPassword(auth, hostEmail, testPassword)
    const rideId = await rideService.createRide(hostUid, {
      from: "CET", to: "Pattam", date: "2026-10-31", departureTime: "04:00 PM", availableSeats: 2, totalSeats: 2
    })
    cleanupDocIds.push({ collection: "rides", id: rideId })

    await rideService.cancelRide(rideId, hostUid)

    const cancelledRide = await rideService.getRideById(rideId)
    expect(cancelledRide?.status).toBe("cancelled")

    await signInWithEmailAndPassword(auth, p1Email, testPassword)
    const reqRes = await rideRequestService.createRideRequest(
      { id: rideId, ownerId: hostUid, status: "cancelled", availableSeats: 2, from: "CET", to: "Pattam", date: "2026-10-31", departureTime: "04:00 PM" },
      passenger1Uid, 1, "Request to cancelled ride"
    )

    expect(reqRes.success).toBe(false)
    expect(reqRes.message).toBe("This ride is no longer active.")
  })
})
