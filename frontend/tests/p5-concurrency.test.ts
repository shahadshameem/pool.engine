import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { auth, db } from "../src/config/firebase"
import { createUserWithEmailAndPassword, signInWithEmailAndPassword } from "firebase/auth"
import { doc, deleteDoc, getDoc } from "firebase/firestore"
import { userService } from "../src/services/user/userService"
import { rideService } from "../src/services/ride/rideService"
import { rideRequestService } from "../src/services/rideRequest/rideRequestService"

describe("PHASE 6 — REPEATED CONCURRENCY TESTS (10x Loop)", () => {
  const ts = Date.now()
  const password = "TestPassword123!"

  let hostUid = ""
  let passAUid = ""
  let passBUid = ""

  const createdRides: string[] = []
  const createdRequests: string[] = []
  const createdProfiles: string[] = []

  beforeAll(async () => {
    // Create Host
    const hCred = await createUserWithEmailAndPassword(auth, `p5_h_${ts}@waymate.test`, password)
    hostUid = hCred.user.uid
    await userService.createUserProfile(hostUid, { name: "Conc Host", gender: "female", college: "CET", department: "CSE", year: "4th Year" })
    createdProfiles.push(hostUid)

    // Create Pass A
    const aCred = await createUserWithEmailAndPassword(auth, `p5_pa_${ts}@waymate.test`, password)
    passAUid = aCred.user.uid
    await userService.createUserProfile(passAUid, { name: "Pass A", gender: "female", college: "CET", department: "ECE", year: "3rd Year" })
    createdProfiles.push(passAUid)

    // Create Pass B
    const bCred = await createUserWithEmailAndPassword(auth, `p5_pb_${ts}@waymate.test`, password)
    passBUid = bCred.user.uid
    await userService.createUserProfile(passBUid, { name: "Pass B", gender: "female", college: "CET", department: "EEE", year: "2nd Year" })
    createdProfiles.push(passBUid)
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
  }, 60000)

  it("P5-C1: 10x repeated concurrency loop for single-seat race condition", async () => {
    let successCount = 0
    const iterations = 10

    for (let i = 1; i <= iterations; i++) {
      // Host creates ride with 1 seat
      await signInWithEmailAndPassword(auth, `p5_h_${ts}@waymate.test`, password)
      const rideId = await rideService.createRide(hostUid, {
        from: "Hostel 4",
        to: "Auditorium",
        date: "2026-12-15",
        departureTime: "10:00 AM",
        totalSeats: 1,
        availableSeats: 1
      })
      createdRides.push(rideId)

      const rideDoc = (await rideService.getRideById(rideId))!

      // Pass A requests seat
      await signInWithEmailAndPassword(auth, `p5_pa_${ts}@waymate.test`, password)
      const reqA = await rideRequestService.createRideRequest(rideDoc, passAUid, 1, "Pass A seat request")

      // Pass B requests seat
      await signInWithEmailAndPassword(auth, `p5_pb_${ts}@waymate.test`, password)
      const reqB = await rideRequestService.createRideRequest(rideDoc, passBUid, 1, "Pass B seat request")

      if (reqA.requestId) createdRequests.push(reqA.requestId)
      if (reqB.requestId) createdRequests.push(reqB.requestId)

      // Host fires concurrent accept requests for both passengers
      await signInWithEmailAndPassword(auth, `p5_h_${ts}@waymate.test`, password)
      const [resA, resB] = await Promise.all([
        rideRequestService.acceptRideRequest(reqA.requestId!, hostUid),
        rideRequestService.acceptRideRequest(reqB.requestId!, hostUid)
      ])

      const succeeded = [resA, resB].filter(r => r.success).length
      const failed = [resA, resB].filter(r => !r.success).length

      // Exactly one accept must succeed, one must fail
      expect(succeeded).toBe(1)
      expect(failed).toBe(1)

      const finalRide = await rideService.getRideById(rideId)
      expect(finalRide?.availableSeats).toBe(0)
      expect(finalRide?.acceptedPassengers?.length).toBe(1)

      successCount++
    }

    const passRate = (successCount / iterations) * 100
    console.log(`[CONCURRENCY SUMMARY] 10x Race Condition Test Pass Rate: ${passRate}% (${successCount}/${iterations})`)
    expect(passRate).toBe(100)
  }, 120000)
})
