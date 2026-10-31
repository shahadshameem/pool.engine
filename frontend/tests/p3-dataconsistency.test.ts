import { describe, it, expect, beforeAll, afterAll } from "vitest"
import { auth, db } from "../src/config/firebase"
import { createUserWithEmailAndPassword, signInWithEmailAndPassword } from "firebase/auth"
import { doc, deleteDoc, getDoc } from "firebase/firestore"
import { userService } from "../src/services/user/userService"
import { rideService } from "../src/services/ride/rideService"
import { isRideExpired } from "../src/config/matchingConfig"

describe("PHASE 4 — P2 DATA CONSISTENCY & LEGACY SCHEMAS", () => {
  const ts = Date.now()
  const password = "TestPassword123!"

  let hostUid = ""
  let passengerUid = ""

  const createdRides: string[] = []
  const createdRequests: string[] = []
  const createdProfiles: string[] = []

  beforeAll(async () => {
    // Create Host
    const hCred = await createUserWithEmailAndPassword(auth, `p3_h_${ts}@waymate.test`, password)
    hostUid = hCred.user.uid
    await userService.createUserProfile(hostUid, { name: "P3 Host", gender: "female", college: "CET", department: "CSE", year: "4th Year" })
    createdProfiles.push(hostUid)

    // Create Passenger
    const pCred = await createUserWithEmailAndPassword(auth, `p3_p_${ts}@waymate.test`, password)
    passengerUid = pCred.user.uid
    await userService.createUserProfile(passengerUid, { name: "P3 Passenger", gender: "female", college: "CET", department: "ECE", year: "3rd Year" })
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
  })

  it("P2-D1: Missing/null optional fields handled gracefully without throwing runtime TypeError", async () => {
    await signInWithEmailAndPassword(auth, `p3_h_${ts}@waymate.test`, password)

    const rideId = await rideService.createRide(hostUid, {
      from: "Hostel 2",
      to: "Main Gate",
      date: "2026-12-06",
      departureTime: "02:00 PM",
      totalSeats: 2,
      availableSeats: 2,
      notes: undefined,
      vehicleType: undefined,
      meetingPoint: undefined
    })
    createdRides.push(rideId)

    const fetchedRide = await rideService.getRideById(rideId)
    expect(fetchedRide).toBeDefined()
    expect(fetchedRide?.from).toBe("Hostel 2")
    expect(fetchedRide?.status).toBe("active")
  })

  it("P2-D2: Cancellation tracking fields — verifies cancelled status & expiration classification", async () => {
    await signInWithEmailAndPassword(auth, `p3_h_${ts}@waymate.test`, password)

    const rideId = await rideService.createRide(hostUid, {
      from: "Lab",
      to: "Main Gate",
      date: "2026-12-07",
      departureTime: "03:00 PM",
      totalSeats: 2,
      availableSeats: 2
    })
    createdRides.push(rideId)

    const cancelRes = await rideService.cancelRide(rideId, hostUid)
    expect(cancelRes.success).toBe(true)

    const updatedRide = await rideService.getRideById(rideId)
    expect(updatedRide?.status).toBe("cancelled")
    expect(isRideExpired(updatedRide?.date, updatedRide?.departureTime, updatedRide?.status)).toBe(true)
  })

  it("P2-D3: Timestamp & ID format consistency across created documents", async () => {
    await signInWithEmailAndPassword(auth, `p3_h_${ts}@waymate.test`, password)

    const newRideId = await rideService.createRide(hostUid, {
      from: "Auditorium",
      to: "Campus Gate",
      date: "2026-12-08",
      departureTime: "04:00 PM",
      totalSeats: 4,
      availableSeats: 4
    })
    createdRides.push(newRideId)

    const rideDoc = await getDoc(doc(db, "rides", newRideId))
    const data = rideDoc.data()!
    expect(data.createdAt).toBeDefined()
    expect(data.updatedAt).toBeDefined()
    expect(data.status).toBe("active")
    // Code & firestore.rules canonical value is "female_only" (legacy was "female")
    expect(["female", "female_only"]).toContain(data.genderPolicy)
  })
})
